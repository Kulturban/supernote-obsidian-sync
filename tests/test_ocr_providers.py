"""Unit tests for Supsidian's OCR provider helpers.

All imports use a temporary HOME so tests never load or write a user's real
Supsidian configuration, logs, vault, or processed-note state.
"""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
MODULE_NAME = "supernote_obsidian_sync"


@pytest.fixture
def load_sync_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import a fresh backend module configured entirely below ``tmp_path``."""

    test_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(test_home))
    monkeypatch.syspath_prepend(str(SRC_DIR))

    def load(config: dict | None = None):
        app_support = test_home / "Library" / "Application Support" / "Supernote Obsidian Sync"
        app_support.mkdir(parents=True, exist_ok=True)
        if config is not None:
            (app_support / "config.json").write_text(json.dumps(config), encoding="utf-8")

        sys.modules.pop(MODULE_NAME, None)
        importlib.invalidate_caches()
        return importlib.import_module(MODULE_NAME)

    yield load
    sys.modules.pop(MODULE_NAME, None)


@pytest.mark.parametrize(
    ("provider", "function_name"),
    [
        ("mistral", "mistral_ocr_pdf"),
        ("local_ollama", "local_ollama_ocr_pdf"),
        ("hybrid_marker_olmocr", "hybrid_marker_olmocr_pdf"),
    ],
)
def test_provider_dispatches_to_selected_provider(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    function_name: str,
) -> None:
    module = load_sync_module()
    calls: list[tuple[Path, Path, str]] = []

    def fake_provider(pdf_file: Path, image_dir: Path, obsidian_image_folder: str) -> str:
        calls.append((pdf_file, image_dir, obsidian_image_folder))
        return f"{provider} result"

    monkeypatch.setattr(module, function_name, fake_provider)
    monkeypatch.setattr(module, "OCR_PROVIDER", provider)

    assert module.ocr_pdf(Path("note.pdf"), Path("images"), "Attachments/Test") == f"{provider} result"
    assert calls == [(Path("note.pdf"), Path("images"), "Attachments/Test")]


def test_provider_dispatch_rejects_unknown_provider(load_sync_module, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_sync_module()
    monkeypatch.setattr(module, "OCR_PROVIDER", "unknown_provider")

    with pytest.raises(RuntimeError, match="Unsupported OCR provider 'unknown_provider'"):
        module.ocr_pdf(Path("note.pdf"), Path("images"), "Attachments/Test")


@pytest.mark.parametrize("configured_provider", [None, ""])
def test_legacy_or_empty_provider_effectively_defaults_to_mistral(
    load_sync_module,
    configured_provider: str | None,
) -> None:
    config = {} if configured_provider is None else {"ocr_provider": configured_provider}
    module = load_sync_module(config)

    assert module.OCR_PROVIDER == "mistral"


@pytest.mark.parametrize(
    ("config_existed", "raw_config", "expected_provider", "expected_default"),
    [
        (False, {}, "local_ollama", "1"),
        (True, {}, "mistral", "2"),
        (True, {"ocr_provider": "local_ollama"}, "local_ollama", "1"),
        (True, {"ocr_provider": "mistral"}, "mistral", "2"),
        (
            True,
            {"ocr_provider": "hybrid_marker_olmocr"},
            "hybrid_marker_olmocr",
            "3",
        ),
    ],
)
def test_setup_provider_defaults(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    config_existed: bool,
    raw_config: dict,
    expected_provider: str,
    expected_default: str,
) -> None:
    module = load_sync_module()
    prompts: list[tuple[str, str]] = []

    def choose_default(prompt: str, default: str = "") -> str:
        prompts.append((prompt, default))
        return default

    monkeypatch.setattr(module, "ask", choose_default)

    assert module.choose_setup_ocr_provider(config_existed, raw_config) == expected_provider
    assert prompts[-1][1] == expected_default


@pytest.mark.parametrize(
    ("choice", "expected_provider"),
    [
        ("3", "hybrid_marker_olmocr"),
        ("hybrid", "hybrid_marker_olmocr"),
    ],
)
def test_setup_provider_accepts_hybrid_choices(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
    expected_provider: str,
) -> None:
    module = load_sync_module()
    monkeypatch.setattr(module, "ask", lambda _prompt, _default="": choice)

    assert module.choose_setup_ocr_provider(False, {}) == expected_provider


def test_unknown_setup_provider_defaults_to_mistral(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_sync_module()
    defaults: list[str] = []

    def choose_default(_prompt: str, default: str = "") -> str:
        defaults.append(default)
        return default

    monkeypatch.setattr(module, "ask", choose_default)

    assert module.choose_setup_ocr_provider(True, {"ocr_provider": "unsupported"}) == "mistral"
    assert defaults == ["2"]
    assert "not selectable in setup" in capsys.readouterr().out


def test_hybrid_setup_saves_marker_command_and_reports_missing_marker(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_sync_module()

    def answer(prompt: str, default: str = "") -> str:
        if prompt.startswith("OCR strategy"):
            return "3"
        if prompt.startswith("Path or command for marker_single"):
            return "/custom/path/marker_single"
        return default

    monkeypatch.setattr(module, "ask", answer)
    monkeypatch.setattr(module, "ask_bool", lambda _prompt, default=False: default)
    monkeypatch.setattr(
        module,
        "local_ollama_diagnostics",
        lambda: (True, "available", True, "reachable", False, "missing"),
    )
    monkeypatch.setattr(module.shutil, "which", lambda _command: None)

    module.setup()

    saved_config = json.loads(module.CONFIG_FILE.read_text(encoding="utf-8"))
    assert saved_config["ocr_provider"] == "hybrid_marker_olmocr"
    assert saved_config["hybrid_marker_command"] == "/custom/path/marker_single"
    assert not module.ENV_FILE.exists()
    output = capsys.readouterr().out
    assert "Experimental provider selected" in output
    assert "absolute hybrid_marker_command path" in output


def test_format_ocr_pages_uses_provider_markdown_contract(load_sync_module) -> None:
    module = load_sync_module()

    assert module.format_ocr_pages(["one", "two"]) == (
        "## Page 1\n\n"
        "one\n\n"
        "---\n\n"
        "## Page 2\n\n"
        "two\n"
    )


def test_missing_marker_command_has_clear_error(load_sync_module, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = load_sync_module()
    monkeypatch.setattr(module.shutil, "which", lambda _: None)

    with pytest.raises(
        RuntimeError,
        match="hybrid_marker_olmocr requires marker_single.*ensure marker_single is on PATH",
    ):
        module.run_hybrid_marker(tmp_path / "note.pdf", tmp_path / "marker-output")


def test_copy_marker_visuals_filters_unsafe_and_unreferenced_assets(load_sync_module, tmp_path: Path) -> None:
    module = load_sync_module()
    marker_dir = tmp_path / "marker-output"
    marker_dir.mkdir()
    crop = marker_dir / "_page_0_Picture_6.jpeg"
    crop.write_bytes(b"cropped visual")
    (marker_dir / "page-001.png").write_bytes(b"full page")
    (marker_dir / "unreferenced.jpeg").write_bytes(b"not linked")
    outside_asset = tmp_path / "outside.jpeg"
    outside_asset.write_bytes(b"outside")
    (marker_dir / "result.md").write_text(
        "\n".join(
            [
                "![](_page_0_Picture_6.jpeg)",
                "![](https://example.com/external.jpeg)",
                "![](../outside.jpeg)",
                "![](missing.jpeg)",
                "![](page-001.png)",
            ]
        ),
        encoding="utf-8",
    )

    extracted_dir = tmp_path / "extracted_visuals"
    visuals = module.copy_marker_visuals(marker_dir, extracted_dir)

    assert len(visuals) == 1
    assert visuals[0]["copied_filename"] == "page-001-visual-001.jpeg"
    assert visuals[0]["assigned_page"] == 1
    assert visuals[0]["marker_page_index"] == 0
    assert (extracted_dir / "page-001-visual-001.jpeg").read_bytes() == b"cropped visual"
    assert not (extracted_dir / "page-001-visual-002.png").exists()
    assert not (extracted_dir / "unreferenced.jpeg").exists()


@pytest.mark.parametrize(
    ("filename", "marker_page_index", "human_page"),
    [
        ("_page_0_Picture_6.jpeg", 0, 1),
        ("_page_1_Picture_6.jpeg", 1, 2),
    ],
)
def test_marker_zero_based_filename_maps_to_human_page(
    load_sync_module,
    filename: str,
    marker_page_index: int,
    human_page: int,
) -> None:
    module = load_sync_module()

    assert module.marker_page_index_from_filename(Path(filename)) == marker_page_index

    marker_dir = Path(module.tempfile.mkdtemp())
    try:
        asset = marker_dir / filename
        asset.write_bytes(b"crop")
        (marker_dir / "result.md").write_text(f"![]({filename})", encoding="utf-8")
        visuals = module.copy_marker_visuals(marker_dir, marker_dir / "copied")
        assert visuals[0]["assigned_page"] == human_page
    finally:
        module.shutil.rmtree(marker_dir)


def test_hybrid_uses_obsidian_embed_for_copied_visual(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module()

    def fake_marker(_pdf_file: Path, marker_dir: Path) -> None:
        marker_dir.mkdir(parents=True)
        (marker_dir / "_page_0_Picture_6.jpeg").write_bytes(b"crop")
        (marker_dir / "result.md").write_text(
            "Drawing\n\n![](_page_0_Picture_6.jpeg)\n\nList",
            encoding="utf-8",
        )

    monkeypatch.setattr(module, "run_hybrid_marker", fake_marker)
    monkeypatch.setattr(module, "ollama_ocr_pdf_pages", lambda _: ["Drawing\n\nList"])

    markdown = module.hybrid_marker_olmocr_pdf(
        tmp_path / "note.pdf",
        tmp_path / "attachments" / "LocalOCR-Test",
        "Attachments/Supernote/Psychomotorik/LocalOCR-Test",
    )

    embed = "![[Attachments/Supernote/Psychomotorik/LocalOCR-Test/extracted_visuals/page-001-visual-001.jpeg]]"
    assert embed in markdown
    assert "![](extracted_visuals/" not in markdown
    assert markdown.index(embed) < markdown.index("List")


def test_marker_order_prefers_unique_following_then_previous_anchor(load_sync_module) -> None:
    module = load_sync_module()
    embed = "![[Attachments/Test/extracted_visuals/page-001-visual-001.jpeg]]"

    following_result, following_placed = module.place_visual_by_marker_order(
        "Drawing\n\nList\n- One",
        {"marker_text_before": "Drawing", "marker_text_after": "List"},
        embed,
    )
    assert following_placed is True
    assert following_result.count(embed) == 1
    assert following_result.index(embed) < following_result.index("List")

    previous_result, previous_placed = module.place_visual_by_marker_order(
        "Drawing\n\nDifferent section",
        {"marker_text_before": "Drawing", "marker_text_after": "Missing"},
        embed,
    )
    assert previous_placed is True
    assert previous_result.count(embed) == 1
    assert previous_result.index(embed) > previous_result.index("Drawing")


def test_marker_order_ambiguous_anchor_uses_page_local_fallback(load_sync_module) -> None:
    module = load_sync_module()
    embed = "![[Attachments/Test/extracted_visuals/page-001-visual-001.jpeg]]"
    page_text = "List\n- One\n\nList\n- Two"

    unchanged, placed = module.place_visual_by_marker_order(
        page_text,
        {"marker_text_before": None, "marker_text_after": "List"},
        embed,
    )
    fallback = module.append_extracted_visuals(unchanged, [embed])

    assert placed is False
    assert fallback.count(embed) == 1
    assert "### Extracted visuals" in fallback


def test_forgiving_html_table_conversion_pads_irregular_rows(load_sync_module) -> None:
    module = load_sync_module()
    html = (
        "<table><tr><th>1</th><th>2</th><th>3</th><th>4</th></tr>"
        "<tr><td>a</td><td><sup>2</sup></td><td></td><td></td><td>yes</td></tr>"
        "<tr><td>b</td><td>value|pipe</td></tr></table>"
    )

    converted, converted_count, unchanged_count = module.convert_html_tables(html, forgiving=True)

    assert converted_count == 1
    assert unchanged_count == 0
    assert "<table" not in converted
    assert "| 1 | 2 | 3 | 4 |  |" in converted
    assert "| --- | --- | --- | --- | --- |" in converted
    assert "| a | ^2 |  |  | yes |" in converted
    assert "| b | value\\|pipe |  |  |  |" in converted


def test_nested_html_table_is_left_unchanged(load_sync_module) -> None:
    module = load_sync_module()
    html = "<table><tr><td>outer <table><tr><td>inner</td></tr></table></td></tr></table>"

    converted, converted_count, unchanged_count = module.convert_html_tables(html, forgiving=True)

    assert converted == html
    assert converted_count == 0
    assert unchanged_count == 1
