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
