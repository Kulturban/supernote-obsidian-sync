"""Unit tests for Supsidian's page-level OCR cache core."""

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
    """Import a fresh backend module using an isolated HOME."""

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


def cached_page(page_hash: str, markdown: str | None = None) -> dict:
    return {
        "page_hash": page_hash,
        "markdown": markdown if markdown is not None else f"cached {page_hash}",
    }


@pytest.fixture
def fitz_module():
    return pytest.importorskip("fitz")


def write_simple_pdf(fitz, pdf_path: Path, page_texts: list[str]) -> None:
    document = fitz.open()
    try:
        for page_text in page_texts:
            page = document.new_page(width=240, height=240)
            page.insert_text((40, 80), page_text, fontsize=14)
        document.save(pdf_path)
    finally:
        document.close()


def test_reconcile_reuses_99_pages_when_one_middle_page_changes(load_sync_module) -> None:
    module = load_sync_module()
    fingerprint = "fingerprint"
    cached_hashes = [f"page-{page_number:03d}" for page_number in range(1, 101)]
    current_hashes = cached_hashes.copy()
    current_hashes[24] = "page-025-changed"

    result = module.reconcile_page_cache(
        current_hashes,
        [cached_page(page_hash) for page_hash in cached_hashes],
        fingerprint,
        cached_fingerprint=fingerprint,
    )

    assert result["reused_pages_count"] == 99
    assert result["pages_to_ocr_count"] == 1
    assert result["changed_pages"] == [25]
    assert result["deleted_pages_count"] == 0
    assert result["ordered_pages"][24]["markdown"] is None
    assert result["ordered_pages"][23]["markdown"] == "cached page-024"
    assert result["ordered_pages"][25]["markdown"] == "cached page-026"


def test_reconcile_inserted_page_reuses_shifted_pages_by_hash(load_sync_module) -> None:
    module = load_sync_module()
    fingerprint = "fingerprint"
    cached_hashes = ["a", "b", "c", "d"]
    current_hashes = ["a", "b", "new", "c", "d"]

    result = module.reconcile_page_cache(
        current_hashes,
        [cached_page(page_hash) for page_hash in cached_hashes],
        fingerprint,
        cached_fingerprint=fingerprint,
    )

    assert result["changed_pages"] == [3]
    assert result["reused_pages_count"] == 4
    assert result["pages_to_ocr_count"] == 1
    assert result["deleted_pages_count"] == 0
    assert [page["markdown"] for page in result["ordered_pages"]] == [
        "cached a",
        "cached b",
        None,
        "cached c",
        "cached d",
    ]


def test_reconcile_deleted_page_omits_deleted_page(load_sync_module) -> None:
    module = load_sync_module()
    fingerprint = "fingerprint"
    cached_hashes = ["a", "b", "c", "d"]
    current_hashes = ["a", "c", "d"]

    result = module.reconcile_page_cache(
        current_hashes,
        [cached_page(page_hash) for page_hash in cached_hashes],
        fingerprint,
        cached_fingerprint=fingerprint,
    )

    assert result["changed_pages"] == []
    assert result["reused_pages_count"] == 3
    assert result["pages_to_ocr_count"] == 0
    assert result["deleted_pages_count"] == 1
    assert [page["page_hash"] for page in result["ordered_pages"]] == current_hashes
    assert [page["markdown"] for page in result["ordered_pages"]] == [
        "cached a",
        "cached c",
        "cached d",
    ]


def test_reconcile_fingerprint_change_invalidates_all_pages(load_sync_module) -> None:
    module = load_sync_module()

    result = module.reconcile_page_cache(
        ["a", "b", "c"],
        [cached_page("a"), cached_page("b"), cached_page("c")],
        "new-fingerprint",
        cached_fingerprint="old-fingerprint",
    )

    assert result["changed_pages"] == [1, 2, 3]
    assert result["reused_pages_count"] == 0
    assert result["pages_to_ocr_count"] == 3
    assert all(page["markdown"] is None for page in result["ordered_pages"])


def test_reconcile_duplicate_hashes_are_consumed_once(load_sync_module) -> None:
    module = load_sync_module()
    fingerprint = "fingerprint"
    cached_pages = [
        cached_page("same", "cached same 1"),
        cached_page("different", "cached different"),
    ]

    result = module.reconcile_page_cache(
        ["new-first", "same", "same"],
        cached_pages,
        fingerprint,
        cached_fingerprint=fingerprint,
    )

    assert result["changed_pages"] == [1, 3]
    assert result["reused_pages_count"] == 1
    assert result["ordered_pages"][1]["markdown"] == "cached same 1"
    assert result["ordered_pages"][2]["markdown"] is None


def test_note_page_cache_id_is_stable_safe_and_collision_resistant(load_sync_module, tmp_path: Path) -> None:
    module = load_sync_module()
    first_path = tmp_path / "Folder A" / "Same Name.note"
    second_path = tmp_path / "Folder B" / "Same Name.note"

    first_id = module.note_page_cache_id(first_path)
    second_id = module.note_page_cache_id(second_path)

    assert first_id == module.note_page_cache_id(first_path)
    assert first_id != second_id
    assert first_id.startswith("same_name-")
    assert "/" not in first_id
    assert "\\" not in first_id
    assert " " not in first_id


def test_page_cache_save_load_round_trip_uses_temp_home(load_sync_module, tmp_path: Path) -> None:
    module = load_sync_module()
    note_file = tmp_path / "source" / "Notebook" / "Cache Test.note"
    cache = {
        "schema_version": module.PAGE_CACHE_SCHEMA_VERSION,
        "ocr_fingerprint": "fingerprint",
        "pages": [cached_page("a", "cached page")],
    }

    module.save_page_cache(note_file, cache)

    assert module.load_page_cache(note_file) == cache
    assert str(module.page_cache_path(note_file)).startswith(str(tmp_path / "home"))
    assert module.load_page_cache(tmp_path / "missing.note") is None

    module.page_cache_path(note_file).write_text("{not valid json", encoding="utf-8")
    assert module.load_page_cache(note_file) is None


def test_ocr_settings_fingerprint_is_deterministic(load_sync_module) -> None:
    module = load_sync_module(
        {
            "ocr_provider": "local_ollama",
            "local_ollama_model": "richardyoung/olmocr2:7b-q8",
            "local_ollama_num_ctx": 8192,
        }
    )

    assert module.ocr_settings_fingerprint() == module.ocr_settings_fingerprint()
    assert module.ocr_settings_fingerprint("local_ollama") != module.ocr_settings_fingerprint("mistral")


def test_render_pdf_page_hashes_is_deterministic(
    load_sync_module,
    fitz_module,
    tmp_path: Path,
) -> None:
    module = load_sync_module()
    pdf_path = tmp_path / "deterministic.pdf"
    write_simple_pdf(fitz_module, pdf_path, ["Page one"])

    first_hashes = module.render_pdf_page_hashes(pdf_path)
    second_hashes = module.render_pdf_page_hashes(pdf_path)

    assert first_hashes == second_hashes
    assert len(first_hashes) == 1
    assert first_hashes[0]


def test_render_pdf_page_hashes_returns_one_hash_per_page(
    load_sync_module,
    fitz_module,
    tmp_path: Path,
) -> None:
    module = load_sync_module()
    pdf_path = tmp_path / "two-pages.pdf"
    write_simple_pdf(fitz_module, pdf_path, ["Page one", "Page two"])

    page_hashes = module.render_pdf_page_hashes(pdf_path)

    assert len(page_hashes) == 2
    assert all(page_hashes)
    assert page_hashes[0] != page_hashes[1]


def test_render_pdf_page_hashes_only_changed_page_hash_changes(
    load_sync_module,
    fitz_module,
    tmp_path: Path,
) -> None:
    module = load_sync_module()
    original_pdf = tmp_path / "original.pdf"
    changed_pdf = tmp_path / "changed.pdf"
    write_simple_pdf(fitz_module, original_pdf, ["Page one", "Page two"])
    write_simple_pdf(fitz_module, changed_pdf, ["Page one", "Page two changed"])

    original_hashes = module.render_pdf_page_hashes(original_pdf)
    changed_hashes = module.render_pdf_page_hashes(changed_pdf)

    assert len(original_hashes) == 2
    assert original_hashes[0] == changed_hashes[0]
    assert original_hashes[1] != changed_hashes[1]


def test_render_pdf_page_hashes_raises_useful_error_for_missing_or_non_pdf_file(
    load_sync_module,
    fitz_module,
    tmp_path: Path,
) -> None:
    module = load_sync_module()
    missing_pdf = tmp_path / "missing.pdf"
    not_pdf = tmp_path / "not-a-pdf.pdf"
    not_pdf.write_text("not actually a PDF", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Could not open PDF for page cache hashing"):
        module.render_pdf_page_hashes(missing_pdf)

    with pytest.raises(RuntimeError, match="Could not open PDF for page cache hashing"):
        module.render_pdf_page_hashes(not_pdf)


def run_fake_incremental_ocr(
    module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    page_hashes: list[str],
    ocr_calls: list[list[int]],
) -> str:
    monkeypatch.setattr(module, "render_pdf_page_hashes", lambda _pdf_file: page_hashes)

    def fake_selected_ocr(_pdf_file: Path, page_numbers: list[int]) -> dict[int, str]:
        ocr_calls.append(page_numbers)
        return {
            page_number: f"fresh page {page_number}"
            for page_number in page_numbers
        }

    monkeypatch.setattr(module, "ollama_ocr_selected_pdf_pages", fake_selected_ocr)
    return module.local_ollama_ocr_pdf_incremental(
        tmp_path / "note.pdf",
        tmp_path / "attachments",
        "Attachments/Test",
        tmp_path / "source" / "Incremental.note",
    )


def run_fake_hybrid_ocr(
    module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    page_hashes: list[str],
    ocr_calls: list[list[int]],
    marker_calls: list[str | None],
) -> str:
    monkeypatch.setattr(module, "render_pdf_page_hashes", lambda _pdf_file: page_hashes)

    def fake_selected_ocr(_pdf_file: Path, page_numbers: list[int]) -> dict[int, str]:
        ocr_calls.append(page_numbers)
        return {
            page_number: f"hybrid fresh page {page_number}"
            for page_number in page_numbers
        }

    def fake_marker(_pdf_file: Path, marker_dir: Path, page_range: str | None = None) -> None:
        marker_calls.append(page_range)
        marker_dir.mkdir(parents=True, exist_ok=True)
        (marker_dir / "result.md").write_text("No visuals", encoding="utf-8")

    monkeypatch.setattr(module, "ollama_ocr_selected_pdf_pages", fake_selected_ocr)
    monkeypatch.setattr(module, "run_hybrid_marker", fake_marker)

    return module.hybrid_marker_olmocr_pdf(
        tmp_path / "hybrid.pdf",
        tmp_path / "attachments",
        "Attachments/Test",
        tmp_path / "source" / "Hybrid.note",
    )


def run_fake_hybrid_ocr_with_marker_failure(
    module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    page_hashes: list[str],
    ocr_calls: list[list[int]],
    marker_calls: list[str | None],
) -> str:
    monkeypatch.setattr(module, "render_pdf_page_hashes", lambda _pdf_file: page_hashes)

    def fake_selected_ocr(_pdf_file: Path, page_numbers: list[int]) -> dict[int, str]:
        ocr_calls.append(page_numbers)
        return {
            page_number: f"hybrid fresh page {page_number}"
            for page_number in page_numbers
        }

    def failing_marker(_pdf_file: Path, _marker_dir: Path, page_range: str | None = None) -> None:
        marker_calls.append(page_range)
        raise RuntimeError("Invalid buffer size: 23.97 GiB")

    monkeypatch.setattr(module, "ollama_ocr_selected_pdf_pages", fake_selected_ocr)
    monkeypatch.setattr(module, "run_hybrid_marker", failing_marker)

    return module.hybrid_marker_olmocr_pdf(
        tmp_path / "hybrid.pdf",
        tmp_path / "attachments",
        "Attachments/Test",
        tmp_path / "source" / "Hybrid.note",
    )


def test_incremental_local_ollama_first_run_ocrs_all_pages(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "local_ollama"})
    ocr_calls: list[list[int]] = []

    markdown = run_fake_incremental_ocr(
        module,
        monkeypatch,
        tmp_path,
        ["a", "b", "c"],
        ocr_calls,
    )
    cache = module.load_page_cache(tmp_path / "source" / "Incremental.note")

    assert ocr_calls == [[1, 2, 3]]
    assert "## Page 1\n\nfresh page 1" in markdown
    assert "## Page 3\n\nfresh page 3" in markdown
    assert cache["last_run"]["pages_to_ocr_count"] == 3
    assert [page["page_hash"] for page in cache["pages"]] == ["a", "b", "c"]


def test_incremental_local_ollama_second_run_reuses_all_cached_pages(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "local_ollama"})
    first_calls: list[list[int]] = []
    second_calls: list[list[int]] = []

    run_fake_incremental_ocr(module, monkeypatch, tmp_path, ["a", "b"], first_calls)
    markdown = run_fake_incremental_ocr(module, monkeypatch, tmp_path, ["a", "b"], second_calls)
    cache = module.load_page_cache(tmp_path / "source" / "Incremental.note")

    assert first_calls == [[1, 2]]
    assert second_calls == []
    assert "fresh page 1" in markdown
    assert "fresh page 2" in markdown
    assert cache["last_run"]["reused_pages_count"] == 2
    assert cache["last_run"]["pages_to_ocr_count"] == 0


def test_incremental_local_ollama_changed_middle_page_ocrs_only_that_page(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "local_ollama"})
    first_calls: list[list[int]] = []
    second_calls: list[list[int]] = []

    run_fake_incremental_ocr(module, monkeypatch, tmp_path, ["a", "b", "c"], first_calls)
    markdown = run_fake_incremental_ocr(module, monkeypatch, tmp_path, ["a", "changed", "c"], second_calls)
    cache = module.load_page_cache(tmp_path / "source" / "Incremental.note")

    assert second_calls == [[2]]
    assert "## Page 1\n\nfresh page 1" in markdown
    assert "## Page 2\n\nfresh page 2" in markdown
    assert "## Page 3\n\nfresh page 3" in markdown
    assert cache["last_run"]["changed_pages"] == [2]
    assert cache["last_run"]["reused_pages_count"] == 2
    assert cache["last_run"]["deleted_pages_count"] == 0


def test_incremental_local_ollama_inserted_page_reuses_shifted_pages(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "local_ollama"})
    first_calls: list[list[int]] = []
    second_calls: list[list[int]] = []

    run_fake_incremental_ocr(module, monkeypatch, tmp_path, ["a", "b", "c"], first_calls)
    markdown = run_fake_incremental_ocr(module, monkeypatch, tmp_path, ["a", "new", "b", "c"], second_calls)
    cache = module.load_page_cache(tmp_path / "source" / "Incremental.note")

    assert second_calls == [[2]]
    assert "## Page 2\n\nfresh page 2" in markdown
    assert "## Page 3\n\nfresh page 2" in markdown
    assert "## Page 4\n\nfresh page 3" in markdown
    assert cache["last_run"]["changed_pages"] == [2]
    assert cache["last_run"]["reused_pages_count"] == 3
    assert cache["last_run"]["deleted_pages_count"] == 0


def test_incremental_local_ollama_deleted_page_is_removed(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "local_ollama"})
    first_calls: list[list[int]] = []
    second_calls: list[list[int]] = []

    run_fake_incremental_ocr(module, monkeypatch, tmp_path, ["a", "b", "c"], first_calls)
    markdown = run_fake_incremental_ocr(module, monkeypatch, tmp_path, ["a", "c"], second_calls)
    cache = module.load_page_cache(tmp_path / "source" / "Incremental.note")

    assert second_calls == []
    assert "## Page 1\n\nfresh page 1" in markdown
    assert "## Page 2\n\nfresh page 3" in markdown
    assert "## Page 3" not in markdown
    assert cache["last_run"]["deleted_pages_count"] == 1


def test_incremental_local_ollama_fingerprint_change_ocrs_all_pages(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "local_ollama"})
    note_file = tmp_path / "source" / "Incremental.note"
    module.save_page_cache(
        note_file,
        {
            "ocr_fingerprint": "old-fingerprint",
            "pages": [cached_page("a", "old a"), cached_page("b", "old b")],
        },
    )
    monkeypatch.setattr(module, "ocr_settings_fingerprint", lambda _provider=None: "new-fingerprint")
    ocr_calls: list[list[int]] = []

    markdown = run_fake_incremental_ocr(
        module,
        monkeypatch,
        tmp_path,
        ["a", "b"],
        ocr_calls,
    )
    cache = module.load_page_cache(note_file)

    assert ocr_calls == [[1, 2]]
    assert "old a" not in markdown
    assert "fresh page 1" in markdown
    assert cache["ocr_fingerprint"] == "new-fingerprint"
    assert cache["last_run"]["pages_to_ocr_count"] == 2


def test_incremental_local_ollama_helper_does_not_unload_model_directly(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "local_ollama"})
    ocr_calls: list[list[int]] = []
    monkeypatch.setattr(
        module,
        "unload_local_ollama_model_after_note",
        lambda: (_ for _ in ()).throw(AssertionError("lower-level local OCR should not unload")),
    )

    run_fake_incremental_ocr(
        module,
        monkeypatch,
        tmp_path,
        ["a"],
        ocr_calls,
    )

    assert ocr_calls == [[1]]


def test_incremental_hybrid_first_run_ocrs_all_pages_and_runs_marker(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "hybrid_marker_olmocr"})
    ocr_calls: list[list[int]] = []
    marker_calls: list[str | None] = []

    markdown = run_fake_hybrid_ocr(
        module,
        monkeypatch,
        tmp_path,
        ["a", "b", "c"],
        ocr_calls,
        marker_calls,
    )
    cache = module.load_page_cache(tmp_path / "source" / "Hybrid.note")

    assert ocr_calls == [[1, 2, 3]]
    assert marker_calls == ["0", "1", "2"]
    assert "## Page 1\n\nhybrid fresh page 1" in markdown
    assert cache["provider"] == "hybrid_marker_olmocr"
    assert cache["last_run"]["pages_to_ocr_count"] == 3


def test_incremental_hybrid_second_run_reuses_text_and_skips_marker_when_no_pages_changed(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "hybrid_marker_olmocr"})
    first_ocr_calls: list[list[int]] = []
    second_ocr_calls: list[list[int]] = []
    marker_calls: list[str | None] = []

    run_fake_hybrid_ocr(module, monkeypatch, tmp_path, ["a", "b"], first_ocr_calls, marker_calls)
    markdown = run_fake_hybrid_ocr(module, monkeypatch, tmp_path, ["a", "b"], second_ocr_calls, marker_calls)
    cache = module.load_page_cache(tmp_path / "source" / "Hybrid.note")

    assert first_ocr_calls == [[1, 2]]
    assert second_ocr_calls == []
    assert marker_calls == ["0", "1"]
    assert "hybrid fresh page 1" in markdown
    assert "hybrid fresh page 2" in markdown
    assert cache["last_run"]["reused_pages_count"] == 2
    assert cache["last_run"]["pages_to_ocr_count"] == 0


def test_incremental_hybrid_changed_middle_page_ocrs_only_that_page_and_runs_marker(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "hybrid_marker_olmocr"})
    first_ocr_calls: list[list[int]] = []
    second_ocr_calls: list[list[int]] = []
    marker_calls: list[str | None] = []

    run_fake_hybrid_ocr(module, monkeypatch, tmp_path, ["a", "b", "c"], first_ocr_calls, marker_calls)
    markdown = run_fake_hybrid_ocr(
        module,
        monkeypatch,
        tmp_path,
        ["a", "changed", "c"],
        second_ocr_calls,
        marker_calls,
    )
    cache = module.load_page_cache(tmp_path / "source" / "Hybrid.note")

    assert second_ocr_calls == [[2]]
    assert marker_calls == ["0", "1", "2", "1"]
    assert "## Page 1\n\nhybrid fresh page 1" in markdown
    assert "## Page 2\n\nhybrid fresh page 2" in markdown
    assert "## Page 3\n\nhybrid fresh page 3" in markdown
    assert cache["last_run"]["changed_pages"] == [2]
    assert cache["last_run"]["reused_pages_count"] == 2
    assert cache["last_run"]["deleted_pages_count"] == 0


def test_incremental_hybrid_does_not_reuse_local_ollama_cache(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "hybrid_marker_olmocr"})
    note_file = tmp_path / "source" / "Hybrid.note"
    module.save_page_cache(
        note_file,
        {
            "ocr_fingerprint": module.ocr_settings_fingerprint("local_ollama"),
            "provider": "local_ollama",
            "pages": [cached_page("a", "local cached a"), cached_page("b", "local cached b")],
        },
    )
    ocr_calls: list[list[int]] = []
    marker_calls: list[str | None] = []

    markdown = run_fake_hybrid_ocr(
        module,
        monkeypatch,
        tmp_path,
        ["a", "b"],
        ocr_calls,
        marker_calls,
    )
    cache = module.load_page_cache(note_file)

    assert ocr_calls == [[1, 2]]
    assert marker_calls == ["0", "1"]
    assert "local cached" not in markdown
    assert "hybrid fresh page 1" in markdown
    assert cache["provider"] == "hybrid_marker_olmocr"
    assert cache["last_run"]["pages_to_ocr_count"] == 2


def test_incremental_hybrid_helper_does_not_unload_model_directly(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "hybrid_marker_olmocr"})
    ocr_calls: list[list[int]] = []
    marker_calls: list[str | None] = []
    monkeypatch.setattr(
        module,
        "unload_local_ollama_model_after_note",
        lambda: (_ for _ in ()).throw(AssertionError("lower-level hybrid OCR should not unload")),
    )

    run_fake_hybrid_ocr(
        module,
        monkeypatch,
        tmp_path,
        ["a"],
        ocr_calls,
        marker_calls,
    )

    assert ocr_calls == [[1]]
    assert marker_calls == ["0"]


def test_incremental_hybrid_marker_failure_returns_ollama_text_and_saves_cache(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "hybrid_marker_olmocr"})
    ocr_calls: list[list[int]] = []
    marker_calls: list[str | None] = []

    markdown = run_fake_hybrid_ocr_with_marker_failure(
        module,
        monkeypatch,
        tmp_path,
        ["a", "b"],
        ocr_calls,
        marker_calls,
    )
    cache = module.load_page_cache(tmp_path / "source" / "Hybrid.note")

    assert ocr_calls == [[1, 2]]
    assert marker_calls == ["0", "1"]
    assert "## Page 1\n\nhybrid fresh page 1" in markdown
    assert "## Page 2\n\nhybrid fresh page 2" in markdown
    assert "extracted_visuals" not in markdown
    assert cache["provider"] == "hybrid_marker_olmocr"
    assert cache["last_run"]["pages_to_ocr_count"] == 2


def test_incremental_hybrid_marker_failure_on_second_run_still_ocrs_only_changed_page(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module({"ocr_provider": "hybrid_marker_olmocr"})
    first_ocr_calls: list[list[int]] = []
    second_ocr_calls: list[list[int]] = []
    marker_calls: list[str | None] = []

    run_fake_hybrid_ocr(module, monkeypatch, tmp_path, ["a", "b", "c"], first_ocr_calls, marker_calls)
    markdown = run_fake_hybrid_ocr_with_marker_failure(
        module,
        monkeypatch,
        tmp_path,
        ["a", "changed", "c"],
        second_ocr_calls,
        marker_calls,
    )
    cache = module.load_page_cache(tmp_path / "source" / "Hybrid.note")

    assert first_ocr_calls == [[1, 2, 3]]
    assert second_ocr_calls == [[2]]
    assert marker_calls == ["0", "1", "2", "1"]
    assert "## Page 1\n\nhybrid fresh page 1" in markdown
    assert "## Page 2\n\nhybrid fresh page 2" in markdown
    assert "## Page 3\n\nhybrid fresh page 3" in markdown
    assert cache["last_run"]["changed_pages"] == [2]
    assert cache["last_run"]["pages_to_ocr_count"] == 1
    assert cache["last_run"]["reused_pages_count"] == 2
    assert cache["last_run"]["deleted_pages_count"] == 0
