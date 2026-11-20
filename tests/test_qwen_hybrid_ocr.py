"""Unit tests for Qwen3-VL Ollama optimization, sequential RAM unload, Marker visual cleanup, and Qwen visual fallback."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
MODULE_NAME = "supernote_obsidian_sync"


class FakeHTTPResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text if text else (json.dumps(json_data) if json_data is not None else "")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        if self._json_data is None:
            raise ValueError("No JSON")
        return self._json_data


@pytest.fixture
def load_sync_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
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


def write_test_pdf(pdf_path: Path, page_texts: list[str], draw_sketch_on_page_1: bool = False) -> None:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    try:
        for index, text in enumerate(page_texts, start=1):
            page = document.new_page(width=400, height=500)
            page.insert_text((40, 60), text, fontsize=14)
            if draw_sketch_on_page_1 and index == 1:
                page.draw_rect(fitz.Rect(80, 160, 300, 340), color=(0, 0, 0), width=3)
                page.draw_line((80, 160), (300, 340), color=(0, 0, 0), width=2)
        document.save(pdf_path)
    finally:
        document.close()


# ------------------------------------------------------------
# 1. QWEN3-VL /api/chat WITH think: false & <think> STRIPPING
# ------------------------------------------------------------


def test_qwen3_vl_uses_chat_endpoint_with_think_false_and_strips_think_blocks(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = load_sync_module(
        {
            "ocr_provider": "local_ollama",
            "local_ollama_url": "http://localhost:11434/api/generate",
            "local_ollama_model": "qwen3-vl:8b",
        }
    )
    pdf_file = tmp_path / "note.pdf"
    write_test_pdf(pdf_file, ["Hallo Welt"])

    captured: list[tuple[str, dict, dict | None, object]] = []

    def fake_post(url: str, json: dict, timeout, headers: dict | None = None):
        captured.append((url, json, headers, timeout))
        return FakeHTTPResponse(
            200,
            {
                "message": {
                    "role": "assistant",
                    "content": "<think>internal reasoning</think>\n\n# Titel\n\nHallo Welt",
                },
                "prompt_eval_count": 1420,
                "eval_count": 87,
                "done_reason": "stop",
            },
        )

    monkeypatch.setattr(module.requests, "post", fake_post)
    result = module.ollama_ocr_selected_pdf_pages(pdf_file, [1])

    assert len(captured) == 1
    url, payload, headers, timeout = captured[0]
    assert url == "http://localhost:11434/api/chat"
    assert headers == {"Connection": "close"}
    assert timeout == (10, 180)
    assert payload["model"] == "qwen3-vl:8b"
    assert payload["think"] is False
    assert payload["stream"] is False
    assert payload["options"]["num_ctx"] == 8192
    assert payload["options"]["num_predict"] == 2048
    assert payload["options"]["repeat_penalty"] == 1.08
    assert payload["messages"][0]["content"] == module.QWEN3_VL_OCR_PROMPT
    assert len(payload["messages"][0]["images"]) == 1
    assert result == {1: "# Titel\n\nHallo Welt"}

    output = capsys.readouterr().out
    assert "prompt_eval_count=1420" in output
    assert "eval_count=87" in output
    assert "finished in " in output


def test_switching_model_from_olmocr2_to_qwen3_vl_invalidates_cache_even_with_existing_md(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module(
        {
            "ocr_provider": "local_ollama",
            "local_ollama_model": "richardyoung/olmocr2:7b-q8",
        }
    )
    monkeypatch.setattr(module, "OBSIDIAN_NOTE_DIR", tmp_path / "vault" / "notes")
    note_file = tmp_path / "source" / "Bio.note"
    note_file.parent.mkdir(parents=True)
    note_file.write_bytes(b"note")
    pdf_file = tmp_path / "staged" / "Bio.pdf"
    pdf_file.parent.mkdir(parents=True)
    write_test_pdf(pdf_file, ["Page 1"])

    fp_olmocr = module.ocr_settings_fingerprint("local_ollama")

    # Seed an existing Obsidian .md and cache.json from olmocr2
    md_file = module.OBSIDIAN_NOTE_DIR / "Bio.md"
    md_file.parent.mkdir(parents=True, exist_ok=True)
    md_file.write_text("## Page 1\n\nOld olmocr2 text\n", encoding="utf-8")
    page_hashes = module.render_pdf_page_hashes(pdf_file)
    module.save_page_cache(
        note_file,
        {
            "schema_version": 1,
            "provider": "local_ollama",
            "model": "richardyoung/olmocr2:7b-q8",
            "ocr_fingerprint": fp_olmocr,
            "pages": [{"page_number": 1, "page_hash": page_hashes[0], "markdown": "Old olmocr2 text"}],
        },
    )

    # Switch to qwen3-vl:8b -> fingerprint changes and cache MUST be invalidated
    monkeypatch.setattr(module, "LOCAL_OLLAMA_MODEL", "qwen3-vl:8b")
    fp_qwen = module.ocr_settings_fingerprint("local_ollama")
    assert fp_qwen != fp_olmocr

    ocr_calls: list[list[int]] = []

    def fake_ollama_ocr(_pdf: Path, pages: list[int]) -> dict[int, str]:
        ocr_calls.append(pages)
        return {1: "Fresh Qwen3-VL transcription"}

    monkeypatch.setattr(module, "ollama_ocr_selected_pdf_pages", fake_ollama_ocr)
    _, existing_md_pages = module.parse_existing_markdown_note(md_file)
    transcriptions, reconciliation = module.incremental_ollama_page_transcriptions(
        pdf_file,
        note_file,
        "local_ollama",
        fp_qwen,
        existing_md_pages=existing_md_pages,
    )

    assert ocr_calls == [[1]]
    assert reconciliation["changed_pages"] == [1]
    assert transcriptions == ["Fresh Qwen3-VL transcription"]


# ------------------------------------------------------------
# 2. SEQUENTIAL OLLAMA UNLOAD (keep_alive: 0) BEFORE MARKER
# ------------------------------------------------------------


def test_hybrid_mode_unloads_ollama_via_keep_alive_zero_before_running_marker(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module(
        {
            "ocr_provider": "hybrid_marker_olmocr",
            "local_ollama_model": "qwen3-vl:8b",
            "local_ollama_unload_after_note": True,
            "hybrid_qwen_visual_fallback": False,
        }
    )
    monkeypatch.setattr(module, "OBSIDIAN_NOTE_DIR", tmp_path / "vault" / "notes")
    note_file = tmp_path / "source" / "Physics.note"
    note_file.parent.mkdir(parents=True)
    note_file.write_bytes(b"note")
    pdf_file = tmp_path / "staged" / "Physics.pdf"
    pdf_file.parent.mkdir(parents=True)
    write_test_pdf(pdf_file, ["Kinematics"])

    events: list[str] = []

    def fake_post(url: str, json: dict, timeout, headers: dict | None = None):
        if json.get("keep_alive") == 0:
            events.append(f"unload:{url}:{json['model']}")
            return FakeHTTPResponse(200, {"done": True})
        events.append(f"ocr:{url}:{json['model']}")
        return FakeHTTPResponse(200, {"message": {"content": "Kinematics text"}})

    def fake_marker_for_page(_pdf: Path, marker_dir: Path, page_number: int) -> None:
        events.append(f"marker:page-{page_number}")
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "result.md").write_text("Kinematics text", encoding="utf-8")

    monkeypatch.setattr(module.requests, "post", fake_post)
    monkeypatch.setattr(module, "run_hybrid_marker_for_page", fake_marker_for_page)

    module.hybrid_marker_olmocr_pdf(
        pdf_file,
        tmp_path / "staged",
        "Attachments/Physics",
        note_file=note_file,
    )

    assert events == [
        "ocr:http://localhost:11434/api/chat:qwen3-vl:8b",
        "unload:http://localhost:11434/api/chat:qwen3-vl:8b",
        "marker:page-1",
    ]


# ------------------------------------------------------------
# 3. MARKER VISUAL ARTIFACT FILTERING & WHITESPACE TRIMMING
# ------------------------------------------------------------


def test_copy_marker_visuals_filters_blank_and_tiny_artifacts_and_trims_valid_sketch(
    load_sync_module,
    tmp_path: Path,
) -> None:
    module = load_sync_module()
    marker_dir = tmp_path / "marker_out"
    marker_dir.mkdir()

    # 1. Tiny artifact (12x12) -> must be filtered out
    tiny = Image.new("RGB", (12, 12), color=(0, 0, 0))
    tiny.save(marker_dir / "_page_0_Picture_1.jpeg", format="JPEG")

    # 2. Pure white / near-blank crop (200x200) -> must be filtered out
    blank = Image.new("RGB", (200, 200), color=(255, 255, 255))
    blank.save(marker_dir / "_page_0_Picture_2.jpeg", format="JPEG")

    # 3. Valid sketch (100x80) inside a huge 500x500 white canvas -> kept and trimmed tightly
    valid = Image.new("RGB", (500, 500), color=(255, 255, 255))
    draw = ImageDraw.Draw(valid)
    draw.rectangle((200, 210, 300, 290), outline=(15, 15, 15), width=4)
    valid.save(marker_dir / "_page_0_Picture_3.jpeg", format="JPEG")

    (marker_dir / "result.md").write_text(
        "\n".join(
            [
                "![](_page_0_Picture_1.jpeg)",
                "![](_page_0_Picture_2.jpeg)",
                "Above sketch",
                "![](_page_0_Picture_3.jpeg)",
                "Below sketch",
            ]
        ),
        encoding="utf-8",
    )

    extracted_dir = tmp_path / "extracted_visuals"
    visuals = module.copy_marker_visuals(marker_dir, extracted_dir)

    assert len(visuals) == 1
    assert visuals[0]["copied_filename"] == "page-001-visual-001.jpeg"
    saved_path = extracted_dir / "page-001-visual-001.jpeg"
    assert saved_path.is_file()
    with Image.open(saved_path) as trimmed:
        # Original 500x500 canvas trimmed down to ~121x101 (10px margin around 101x81 rect)
        assert 105 <= trimmed.width <= 135
        assert 85 <= trimmed.height <= 115


# ------------------------------------------------------------
# 4. QWEN3-VL VISUAL FALLBACK (VALID BOXES + INVALID JSON FALLBACK)
# ------------------------------------------------------------


def test_hybrid_mode_qwen3_vl_visual_fallback_crops_and_places_sketch_when_marker_finds_none(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module(
        {
            "ocr_provider": "hybrid_marker_olmocr",
            "local_ollama_model": "qwen3-vl:8b",
            "hybrid_qwen_visual_fallback": True,
        }
    )
    monkeypatch.setattr(module, "OBSIDIAN_NOTE_DIR", tmp_path / "vault" / "notes")
    note_file = tmp_path / "source" / "Circuit.note"
    note_file.parent.mkdir(parents=True)
    note_file.write_bytes(b"note")
    pdf_file = tmp_path / "staged" / "Circuit.pdf"
    pdf_file.parent.mkdir(parents=True)
    write_test_pdf(pdf_file, ["Circuit diagram"], draw_sketch_on_page_1=True)

    call_log: list[str] = []

    def fake_post(url: str, json: dict, timeout, headers: dict | None = None):
        if json.get("keep_alive") == 0:
            call_log.append("unload")
            return FakeHTTPResponse(200, {"done": True})
        if json.get("format") == "json":
            call_log.append("qwen_fallback")
            assert json["think"] is False
            assert json["options"]["num_predict"] == 1024
            return FakeHTTPResponse(
                200,
                {
                    "message": {
                        "content": (
                            '{"visuals": [{"id": "VISUAL_1", '
                            '"box_2d": [300, 180, 700, 770], '
                            '"anchor_before": "Circuit intro", '
                            '"anchor_after": "Circuit conclusion"}]}'
                        )
                    }
                },
            )
        call_log.append("ocr")
        return FakeHTTPResponse(
            200,
            {"message": {"content": "Circuit intro\n\nCircuit conclusion"}},
        )

    def fake_marker_empty(_pdf: Path, marker_dir: Path, _page_number: int) -> None:
        call_log.append("marker")
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "result.md").write_text("Circuit intro\n\nCircuit conclusion", encoding="utf-8")

    monkeypatch.setattr(module.requests, "post", fake_post)
    monkeypatch.setattr(module, "run_hybrid_marker_for_page", fake_marker_empty)

    markdown = module.hybrid_marker_olmocr_pdf(
        pdf_file,
        tmp_path / "staged",
        "Attachments/Circuit",
        note_file=note_file,
    )

    assert call_log == ["ocr", "unload", "marker", "qwen_fallback"]
    visual_file = tmp_path / "staged" / "extracted_visuals" / "page-001-visual-001.jpeg"
    assert visual_file.is_file()
    assert (
        "Circuit intro\n\n![[Attachments/Circuit/extracted_visuals/page-001-visual-001.jpeg]]\n\nCircuit conclusion"
        in markdown
    )


def test_qwen_visual_fallback_handles_invalid_json_gracefully_without_crashing(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module(
        {
            "ocr_provider": "hybrid_marker_olmocr",
            "local_ollama_model": "qwen3-vl:8b",
            "hybrid_qwen_visual_fallback": True,
        }
    )
    pdf_file = tmp_path / "note.pdf"
    write_test_pdf(pdf_file, ["Plain text"], draw_sketch_on_page_1=True)

    def fake_post(url: str, json: dict, timeout, headers: dict | None = None):
        return FakeHTTPResponse(
            200,
            {"message": {"content": "NOT VALID JSON {{{ broken"}},
        )

    monkeypatch.setattr(module.requests, "post", fake_post)
    pages = ["Plain text only"]
    saved, placed = module.extract_qwen_fallback_visuals_for_pages(
        pdf_file,
        [1],
        pages,
        tmp_path / "extracted_visuals",
        "Attachments/Plain",
    )

    assert saved == 0
    assert placed == 0
    assert pages == ["Plain text only"]


def test_render_ollama_page_pixmap_caps_long_edge_to_limit_vision_tokens(
    load_sync_module,
    tmp_path: Path,
) -> None:
    fitz = pytest.importorskip("fitz")
    module = load_sync_module({"local_ollama_max_image_edge_px": 1680})

    pdf_file = tmp_path / "large.pdf"
    document = fitz.open()
    try:
        # 900x1200 pt at 200 DPI would be 2500x3333 px without capping
        page = document.new_page(width=900, height=1200)
        page.insert_text((50, 80), "High-res Supernote page", fontsize=18)
        document.save(pdf_file)
    finally:
        document.close()

    doc = fitz.open(pdf_file)
    try:
        pixmap = module.render_ollama_page_pixmap(doc[0], dpi=200)
        assert max(pixmap.width, pixmap.height) <= 1680
        assert max(pixmap.width, pixmap.height) >= 1670
    finally:
        doc.close()


def test_ollama_ocr_raises_clear_timeout_error(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module(
        {
            "ocr_provider": "local_ollama",
            "local_ollama_model": "qwen3-vl:8b",
            "local_ollama_page_timeout_seconds": 180,
        }
    )
    pdf_file = tmp_path / "slow.pdf"
    write_test_pdf(pdf_file, ["Slow page"])

    def fake_timeout(*_args, **_kwargs):
        raise module.requests.Timeout("read timed out")

    monkeypatch.setattr(module.requests, "post", fake_timeout)
    with pytest.raises(RuntimeError, match="Ollama timed out after 180s on page 1"):
        module.ollama_ocr_selected_pdf_pages(pdf_file, [1])
