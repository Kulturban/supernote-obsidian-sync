"""Unit tests for single-file sync (--file) and generalized custom OCR instruction tabs."""

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


def test_custom_ocr_instructions_apply_to_all_providers_and_fingerprints(
    load_sync_module,
) -> None:
    module = load_sync_module(
        {
            "custom_ocr_instructions": [
                {
                    "id": "task-conversion",
                    "name": "Task Conversion",
                    "enabled": True,
                    "instruction": "Convert # lines to tasks.",
                },
                {
                    "id": "math-rules",
                    "name": "Math Rules",
                    "enabled": True,
                    "instruction": "Use LaTeX for integrals.",
                },
                {
                    "id": "disabled-tab",
                    "name": "Disabled Tab",
                    "enabled": False,
                    "instruction": "NEVER INCLUDE THIS",
                },
            ]
        }
    )

    composed = module.compose_custom_ocr_instruction()
    assert "- Task Conversion: Convert # lines to tasks." in composed
    assert "- Math Rules: Use LaTeX for integrals." in composed
    assert "NEVER INCLUDE THIS" not in composed

    # Included in Cloud VLM prompt, Qwen3-VL prompt, AND olmocr2 prompt
    assert "Use LaTeX for integrals." in module.build_cloud_vlm_ocr_prompt()
    assert "Use LaTeX for integrals." in module.resolve_local_ollama_prompt("qwen3-vl:8b-instruct")
    assert "Use LaTeX for integrals." in module.resolve_local_ollama_prompt("richardyoung/olmocr2:7b-q8")

    # Changing instructions invalidates fingerprint across all providers
    fp_mistral_before = module.ocr_settings_fingerprint("mistral")
    fp_gemini_before = module.ocr_settings_fingerprint("gemini")
    fp_ollama_before = module.ocr_settings_fingerprint("local_ollama")
    fp_hybrid_before = module.ocr_settings_fingerprint("hybrid_marker_olmocr")

    module.CUSTOM_OCR_INSTRUCTIONS[1]["enabled"] = False

    assert module.ocr_settings_fingerprint("mistral") != fp_mistral_before
    assert module.ocr_settings_fingerprint("gemini") != fp_gemini_before
    assert module.ocr_settings_fingerprint("local_ollama") != fp_ollama_before
    assert module.ocr_settings_fingerprint("hybrid_marker_olmocr") != fp_hybrid_before


def test_disabling_task_conversion_tab_disables_hash_task_conversion(
    load_sync_module,
) -> None:
    module_enabled = load_sync_module(
        {
            "custom_ocr_instructions": [
                {
                    "id": "task-conversion",
                    "name": "Task Conversion",
                    "enabled": True,
                    "instruction": "Convert # lines to tasks.",
                }
            ]
        }
    )
    assert module_enabled.convert_hash_lines_to_tasks("# Buy milk") == "- [ ] #task Buy milk"

    module_disabled = load_sync_module(
        {
            "custom_ocr_instructions": [
                {
                    "id": "task-conversion",
                    "name": "Task Conversion",
                    "enabled": False,
                    "instruction": "Convert # lines to tasks.",
                }
            ]
        }
    )
    assert module_disabled.convert_hash_lines_to_tasks("# Buy milk") == "# Buy milk"


def test_scan_once_with_file_filter_syncs_only_selected_note(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "Supernote" / "Work"
    source_dir.mkdir(parents=True)
    note_a = source_dir / "Alpha.note"
    note_b = source_dir / "Beta.note"
    note_a.write_bytes(b"alpha-bytes")
    note_b.write_bytes(b"beta-bytes")

    vault_dir = tmp_path / "Vault"
    vault_dir.mkdir()

    module = load_sync_module(
        {
            "vault_dir": str(vault_dir),
            "open_requires_obsidian_running": False,
            "file_stability_wait_seconds": 0,
            "notebooks": [
                {
                    "name": "Work",
                    "source_dir": str(source_dir),
                    "obsidian_note_folder": "Work",
                    "attachment_folder": "Attachments/Work",
                    "state_file": "processed_work.json",
                }
            ],
        }
    )

    processed: list[Path] = []
    monkeypatch.setattr(module, "is_file_stable", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "process_note", lambda note: processed.append(note))

    module.scan_once(folder_name="Work", note_file_filter=str(note_b))
    assert processed == [note_b]

    # Also works by filename or stem
    processed.clear()
    module.scan_once(folder_name="Work", note_file_filter="Alpha")
    assert processed == [note_a]

    # Missing file raises a clear SystemExit
    with pytest.raises(SystemExit, match="Note file not found"):
        module.scan_once(folder_name="Work", note_file_filter="DoesNotExist.note")


def test_cloud_ocr_skips_blank_pages_locally_without_external_upload(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fitz = pytest.importorskip("fitz")
    module = load_sync_module(
        {
            "ocr_provider": "gemini",
            "gemini_api_key": "gem-test-key",
        }
    )

    pdf_file = tmp_path / "blank_and_written.pdf"
    doc = fitz.open()
    try:
        # Page 1: completely blank
        doc.new_page(width=400, height=500)
        # Page 2: has text
        p2 = doc.new_page(width=400, height=500)
        p2.insert_text((40, 80), "Written content on page 2", fontsize=16)
        doc.save(pdf_file)
    finally:
        doc.close()

    api_calls: list[int] = []

    def fake_call_cloud(provider: str, image_bytes: bytes, page_number: int, model: str, api_key: str):
        api_calls.append(page_number)
        return f"Transcribed page {page_number}", []

    monkeypatch.setattr(module, "call_cloud_vlm_ocr_page", fake_call_cloud)

    transcriptions, _ = module.cloud_vlm_ocr_selected_pdf_pages(
        pdf_file,
        [1, 2],
        "gemini",
        tmp_path / "extracted_visuals",
        "Attachments/Note",
    )

    # Page 1 was blank -> skipped locally without calling external cloud API!
    assert api_calls == [2]
    assert transcriptions[1] == ""
    assert transcriptions[2] == "Transcribed page 2"
