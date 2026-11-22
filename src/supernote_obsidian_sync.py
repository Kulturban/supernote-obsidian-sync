import argparse
import base64
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import requests
from dotenv import load_dotenv


# ------------------------------------------------------------
# SETTINGS PATHS
# ------------------------------------------------------------

APP_SUPPORT_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Supernote Obsidian Sync"
)

CONFIG_FILE = APP_SUPPORT_DIR / "config.json"
ENV_FILE = APP_SUPPORT_DIR / ".env"
LOG_FILE = APP_SUPPORT_DIR / "supernote_obsidian_sync.log"
PAGE_CACHE_SCHEMA_VERSION = 1
PAGE_CACHE_CODE_VERSION = "page-cache-v1"
PAGE_CACHE_DIR = APP_SUPPORT_DIR / "page_cache"
PAGE_HASH_DPI = 200
PAGE_HASH_ALPHA = False
PAGE_HASH_VERSION = "rendered-page-hash-v1"

LAUNCH_AGENT_LABEL = "com.kulturban.supernote-obsidian-sync"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LAUNCH_AGENT_FILE = LAUNCH_AGENTS_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
HOMEBREW_CLI_PATH = "/opt/homebrew/bin/supernote-obsidian-sync"
LAUNCH_AGENT_OUT_LOG = APP_SUPPORT_DIR / "launchagent.out.log"
LAUNCH_AGENT_ERR_LOG = APP_SUPPORT_DIR / "launchagent.err.log"

DEFAULT_CONFIG = {
    "source_dir": "",
    "vault_dir": "",
    "obsidian_note_folder": "Supernote",
    "attachment_folder": "Attachments/Supernote",
    "state_file": "processed_notes.json",
    "check_interval_seconds": 60,
    "file_stability_wait_seconds": 10,
    "supernote_tool_path": "",
    "task_marker": "#",
    "task_tag": "#task",
    "custom_ocr_instructions": [],
    "open_requires_obsidian_running": True,
    "ocr_provider": "mistral",
    "ocr_model": "",
    "ocr_reasoning_effort": "low",
    "gemini_api_key": "",
    "anthropic_api_key": "",
    "openai_api_key": "",
    "local_ollama_url": "http://localhost:11434/api/generate",
    "local_ollama_model": "richardyoung/olmocr2:7b-q8",
    "local_ollama_num_ctx": 8192,
    "local_ollama_num_predict": 2048,
    "local_ollama_repeat_penalty": 1.08,
    "local_ollama_max_image_edge_px": 1680,
    "local_ollama_page_timeout_seconds": 180,
    "local_ollama_unload_after_note": True,
    "hybrid_marker_command": "marker_single",
    "hybrid_marker_disable_multiprocessing": True,
    "hybrid_marker_layout_batch_size": 1,
    "hybrid_marker_detection_batch_size": 1,
    "hybrid_marker_recognition_batch_size": 1,
    "hybrid_marker_table_rec_batch_size": 1,
    "hybrid_marker_lowres_image_dpi": 72,
    "hybrid_marker_highres_image_dpi": 144,
    "hybrid_marker_disable_tqdm": True,
    "hybrid_qwen_visual_fallback": True,
}

APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def log(message: str) -> None:
    print(message)
    logging.info(message)


def progress_event(stage: str, **fields: object) -> dict:
    event = {"stage": stage, **fields}
    print(f"SUSPIDIAN_PROGRESS:{json.dumps(event, sort_keys=True)}", flush=True)
    return event


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

def expand_path(path_string: str) -> Path:
    """
    Expand ~ and return an absolute Path.
    """
    return Path(path_string).expanduser().resolve()


def load_config() -> dict:
    """
    Load user settings from the macOS Application Support folder.

    If config.json does not exist yet, return DEFAULT_CONFIG so that
    --setup can still run on a fresh installation.
    """
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()

    try:
        loaded_config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"Config file is invalid JSON:\n{CONFIG_FILE}\n\n{exc}"
        ) from exc

    config = DEFAULT_CONFIG.copy()
    config.update(loaded_config)
    return config


config = load_config()


def positive_int_or_default(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def slugify(value: str) -> str:
    """
    Create a safe lowercase name for generated state files.
    """
    safe = "".join(
        c.lower() if c.isalnum() else "_"
        for c in value.strip()
    )
    safe = "_".join(part for part in safe.split("_") if part)
    return safe or "notebook"


def is_placeholder_path(value: str) -> bool:
    """
    Detect example/template paths that should not be treated as real config.
    """
    if not value:
        return True

    placeholders = [
        "YOUR_USERNAME",
        "YOUR_SUPERNOTE_ID",
        "YOUR_NOTEBOOK_OR_FOLDER",
        "/path/to/",
        "CHANGE_ME",
    ]

    return any(token in value for token in placeholders)


def normalize_notebooks(raw_config: dict) -> list[dict]:
    """
    Normalize notebook configuration.

    Supports the new multi-folder format and the old single-folder format,
    but ignores empty/example placeholder paths so first-time users do not
    get fake diagnostic errors.
    """
    normalized: list[dict] = []

    configured_notebooks = raw_config.get("notebooks", [])

    if isinstance(configured_notebooks, list):
        for item in configured_notebooks:
            if not isinstance(item, dict):
                continue

            source_dir = str(item.get("source_dir", "")).strip()

            if is_placeholder_path(source_dir):
                continue

            name = str(item.get("name", "")).strip() or Path(source_dir).name or "Supernote"
            slug = slugify(name)

            normalized.append(
                {
                    "name": name,
                    "source_dir": source_dir,
                    "obsidian_note_folder": str(
                        item.get("obsidian_note_folder", name)
                    ).strip() or name,
                    "attachment_folder": str(
                        item.get("attachment_folder", f"Attachments/Supernote/{name}")
                    ).strip() or f"Attachments/Supernote/{name}",
                    "state_file": str(
                        item.get("state_file", f"processed_{slug}.json")
                    ).strip() or f"processed_{slug}.json",
                }
            )

    legacy_source_dir = str(raw_config.get("source_dir", "")).strip()

    if not normalized and not is_placeholder_path(legacy_source_dir):
        name = Path(legacy_source_dir).name or "Supernote"
        slug = slugify(name)

        normalized.append(
            {
                "name": name,
                "source_dir": legacy_source_dir,
                "obsidian_note_folder": str(
                    raw_config.get("obsidian_note_folder", name)
                ).strip() or name,
                "attachment_folder": str(
                    raw_config.get("attachment_folder", f"Attachments/Supernote/{name}")
                ).strip() or f"Attachments/Supernote/{name}",
                "state_file": str(
                    raw_config.get("state_file", f"processed_{slug}.json")
                ).strip() or f"processed_{slug}.json",
            }
        )

    return normalized


NOTEBOOKS = normalize_notebooks(config)

CHECK_INTERVAL_SECONDS = int(config.get("check_interval_seconds", 60))
FILE_STABILITY_WAIT_SECONDS = int(config.get("file_stability_wait_seconds", 10))

SUPERNOTE_TOOL_PATH = expand_path(config["supernote_tool_path"])

TASK_MARKER = config.get("task_marker", "#")
TASK_TAG = config.get("task_tag", "#task")

OPEN_REQUIRES_OBSIDIAN_RUNNING = bool(config.get("open_requires_obsidian_running", True))
CUSTOM_OCR_INSTRUCTION = str(config.get("custom_ocr_instruction", "")).strip()


def normalize_custom_ocr_instructions(raw_config: dict) -> list[dict]:
    raw_items = raw_config.get("custom_ocr_instructions")
    if not isinstance(raw_items, list):
        return []

    normalized: list[dict] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        instruction = str(item.get("instruction", "")).strip()
        name = str(item.get("name", "")).strip() or f"Instruction {index}"
        item_id = str(item.get("id", "")).strip() or f"{slugify(name)}-{index}"
        enabled = bool(item.get("enabled", True))
        normalized.append(
            {
                "id": item_id,
                "name": name,
                "enabled": enabled,
                "instruction": instruction,
            }
        )
    return normalized


CUSTOM_OCR_INSTRUCTIONS = normalize_custom_ocr_instructions(config)


def compose_custom_ocr_instruction(
    instructions: list[dict] | None = None,
    legacy_instruction: str | None = None,
) -> str:
    """
    Combine all enabled custom OCR instruction tabs (plus optional legacy
    custom_ocr_instruction) into a single instruction block applied to every
    OCR provider.
    """
    items = CUSTOM_OCR_INSTRUCTIONS if instructions is None else instructions
    legacy = CUSTOM_OCR_INSTRUCTION if legacy_instruction is None else str(legacy_instruction).strip()

    parts: list[str] = []
    seen_texts: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        text = str(item.get("instruction", "")).strip()
        if not text:
            continue
        name = str(item.get("name", "")).strip()
        seen_texts.add(text)
        parts.append(f"- {name}: {text}" if name else f"- {text}")

    if legacy and legacy not in seen_texts:
        parts.append(legacy)

    return "\n".join(parts).strip()


def should_run_hash_task_conversion() -> bool:
    """
    Run deterministic hash-line task conversion unless the user explicitly
    disabled the 'Task Conversion' instruction tab.
    """
    for item in CUSTOM_OCR_INSTRUCTIONS:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "")).strip().lower()
        name = str(item.get("name", "")).strip().lower()
        if item_id == "task-conversion" or name == "task conversion":
            return bool(item.get("enabled", True))
    return True


OCR_PROVIDER = str(config.get("ocr_provider", "mistral")).strip().lower() or "mistral"
OCR_MODEL = str(config.get("ocr_model", "")).strip()
OCR_REASONING_EFFORT_OPTIONS = ("minimal", "low", "medium", "high")


def normalize_ocr_reasoning_effort(value: object) -> str:
    cleaned = str(value or "").strip().lower()
    if cleaned in OCR_REASONING_EFFORT_OPTIONS:
        return cleaned
    return "low"


OCR_REASONING_EFFORT = normalize_ocr_reasoning_effort(config.get("ocr_reasoning_effort", "low"))
GEMINI_API_KEY = str(config.get("gemini_api_key", "")).strip()
ANTHROPIC_API_KEY = str(config.get("anthropic_api_key", "")).strip()
OPENAI_API_KEY = str(config.get("openai_api_key", "")).strip()

CLOUD_VLM_OCR_PROVIDERS = (
    "gemini",
    "claude",
    "openai",
)
CLOUD_OCR_DEFAULT_MODELS = {
    "gemini": "gemini-4-hydrogen",
    "claude": "claude-sonnet-5-5",
    "openai": "gpt-6.1-terra",
}
CLOUD_OCR_API_KEY_CONFIG_KEYS = {
    "gemini": "gemini_api_key",
    "claude": "anthropic_api_key",
    "openai": "openai_api_key",
}
CLOUD_OCR_API_KEY_ENV_VARS = {
    "gemini": "GEMINI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}
CLOUD_VISUAL_EXTRACTION_VERSION = "bbox-pillow-crop-v1"
CLOUD_VISUAL_PADDING_RATIO = 0.035
CLOUD_VISUAL_TRIM_MARGIN_PX = 8
CLOUD_VISUAL_WHITE_THRESHOLD = 248
CLOUD_OCR_MAX_IMAGE_EDGE_PX = positive_int_or_default(
    config.get("cloud_ocr_max_image_edge_px"), 1800
)
CLOUD_SKIP_BLANK_PAGES_LOCALLY = bool(config.get("cloud_skip_blank_pages_locally", True))
LOCAL_OLLAMA_URL = (
    str(config.get("local_ollama_url", "http://localhost:11434/api/generate")).strip()
    or "http://localhost:11434/api/generate"
)
LOCAL_OLLAMA_MODEL = (
    str(config.get("local_ollama_model", "richardyoung/olmocr2:7b-q8")).strip()
    or "richardyoung/olmocr2:7b-q8"
)
LOCAL_OLLAMA_NUM_CTX = positive_int_or_default(config.get("local_ollama_num_ctx"), 8192)
LOCAL_OLLAMA_NUM_PREDICT = positive_int_or_default(config.get("local_ollama_num_predict"), 2048)
try:
    _parsed_repeat_penalty = float(config.get("local_ollama_repeat_penalty", 1.08))
    LOCAL_OLLAMA_REPEAT_PENALTY = _parsed_repeat_penalty if _parsed_repeat_penalty > 0 else 1.08
except (TypeError, ValueError):
    LOCAL_OLLAMA_REPEAT_PENALTY = 1.08
LOCAL_OLLAMA_MAX_IMAGE_EDGE_PX = positive_int_or_default(
    config.get("local_ollama_max_image_edge_px"), 1680
)
LOCAL_OLLAMA_PAGE_TIMEOUT_SECONDS = positive_int_or_default(
    config.get("local_ollama_page_timeout_seconds"), 180
)
LOCAL_OLLAMA_UNLOAD_AFTER_NOTE = bool(config.get("local_ollama_unload_after_note", True))
HYBRID_MARKER_COMMAND = (
    str(config.get("hybrid_marker_command", "marker_single")).strip() or "marker_single"
)
HYBRID_MARKER_DISABLE_MULTIPROCESSING = bool(
    config.get("hybrid_marker_disable_multiprocessing", True)
)
HYBRID_MARKER_LAYOUT_BATCH_SIZE = positive_int_or_default(
    config.get("hybrid_marker_layout_batch_size"), 1
)
HYBRID_MARKER_DETECTION_BATCH_SIZE = positive_int_or_default(
    config.get("hybrid_marker_detection_batch_size"), 1
)
HYBRID_MARKER_RECOGNITION_BATCH_SIZE = positive_int_or_default(
    config.get("hybrid_marker_recognition_batch_size"), 1
)
HYBRID_MARKER_TABLE_REC_BATCH_SIZE = positive_int_or_default(
    config.get("hybrid_marker_table_rec_batch_size"), 1
)
HYBRID_MARKER_LOWRES_IMAGE_DPI = positive_int_or_default(
    config.get("hybrid_marker_lowres_image_dpi"), 72
)
HYBRID_MARKER_HIGHRES_IMAGE_DPI = positive_int_or_default(
    config.get("hybrid_marker_highres_image_dpi"), 144
)
HYBRID_MARKER_DISABLE_TQDM = bool(config.get("hybrid_marker_disable_tqdm", True))
HYBRID_QWEN_VISUAL_FALLBACK = bool(config.get("hybrid_qwen_visual_fallback", True))
LOCAL_OLLAMA_PIPELINE_VERSION = "ollama-pipeline-v2"
MARKER_VISUAL_MIN_WIDTH_PX = 24
MARKER_VISUAL_MIN_HEIGHT_PX = 24
MARKER_VISUAL_MIN_INK_RATIO = 0.002
MARKER_VISUAL_TRIM_MARGIN_PX = 10
QWEN_FALLBACK_PADDING_RATIO = 0.045
DISABLED_OCR_PROVIDERS = (
    "none",
    "disabled",
    "no_ocr",
    "off",
    "pdf_only",
)
SUPPORTED_OCR_PROVIDERS = (
    "mistral",
    "gemini",
    "claude",
    "openai",
    "local_ollama",
    "hybrid_marker_olmocr",
    "none",
)

ACTIVE_NOTEBOOK = {}
ACTIVE_ATTACHMENT_FOLDER = ""

SOURCE_DIR = Path.home()
VAULT_DIR = expand_path(config["vault_dir"])
OBSIDIAN_NOTE_DIR = VAULT_DIR
PDF_DIR = VAULT_DIR
STATE_FILE = APP_SUPPORT_DIR / "processed_notes.json"


def use_notebook(notebook: dict) -> None:
    """
    Set active paths for the notebook currently being scanned.
    This keeps the existing processing functions simple while allowing
    multiple Supernote source folders.
    """
    global ACTIVE_NOTEBOOK
    global ACTIVE_ATTACHMENT_FOLDER
    global SOURCE_DIR
    global OBSIDIAN_NOTE_DIR
    global PDF_DIR
    global STATE_FILE

    ACTIVE_NOTEBOOK = notebook

    SOURCE_DIR = expand_path(notebook["source_dir"])
    OBSIDIAN_NOTE_DIR = VAULT_DIR / notebook["obsidian_note_folder"]
    PDF_DIR = VAULT_DIR / notebook["attachment_folder"]
    ACTIVE_ATTACHMENT_FOLDER = notebook["attachment_folder"]

    state_file_path = Path(notebook["state_file"]).expanduser()

    if state_file_path.is_absolute():
        STATE_FILE = state_file_path
    else:
        STATE_FILE = APP_SUPPORT_DIR / state_file_path


if NOTEBOOKS:
    use_notebook(NOTEBOOKS[0])

load_dotenv(ENV_FILE)


# ------------------------------------------------------------
# APP CHECKS
# ------------------------------------------------------------

def is_obsidian_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-x", "Obsidian"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


# ------------------------------------------------------------
# STATE
# ------------------------------------------------------------

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"State file is invalid JSON:\n{STATE_FILE}\n\n{exc}"
        ) from exc


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def _file_stability_snapshot(path: Path) -> tuple[int, int, str] | None:
    try:
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return (stat.st_size, stat.st_mtime_ns, digest)


def is_file_stable(path: Path, wait_seconds: int, max_attempts: int = 5) -> bool:
    previous = _file_stability_snapshot(path)
    if previous is None:
        return False

    attempts = max(1, int(max_attempts))
    for _ in range(attempts):
        time.sleep(max(0, wait_seconds))
        current = _file_stability_snapshot(path)
        if current is None:
            return False
        if current == previous:
            return True
        previous = current

    return False


def note_state_signature(note_file: Path) -> str:
    stat = note_file.stat()
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def write_text_atomically(destination: Path, content: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path_str = tempfile.mkstemp(
        prefix=".supsidian-tmp-",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def replace_file_atomically(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path_str = tempfile.mkstemp(
        prefix=".supsidian-tmp-",
        suffix=".tmp",
        dir=str(destination.parent),
    )
    os.close(fd)
    temp_path = Path(temp_path_str)
    try:
        shutil.copy2(source, temp_path)
        os.replace(temp_path, destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def safe_name(note_file: Path) -> str:
    folder_name = note_file.parent.name
    file_name = note_file.stem

    if folder_name == SOURCE_DIR.name:
        name = file_name
    else:
        name = f"{folder_name} - {file_name}"

    name = "".join(c for c in name if c not in r'\/:*?"<>|').strip()
    return name or "Untitled Supernote"


def convert_note_to_pdf(note_file: Path, pdf_file: Path) -> None:
    pdf_file.parent.mkdir(parents=True, exist_ok=True)

    if not SUPERNOTE_TOOL_PATH.exists():
        raise FileNotFoundError(f"supernote-tool not found: {SUPERNOTE_TOOL_PATH}")

    log(f"Converting note to PDF: {note_file}")

    subprocess.run(
        [
            str(SUPERNOTE_TOOL_PATH),
            "convert",
            "-t",
            "pdf",
            "-a",
            str(note_file),
            str(pdf_file),
        ],
        check=True,
    )

    log(f"PDF created: {pdf_file}")


# ------------------------------------------------------------
# PAGE OCR CACHE CORE
# ------------------------------------------------------------

def note_page_cache_id(note_file: Path) -> str:
    """
    Return a stable, filesystem-safe cache id for a note path.

    The visible stem keeps cache folders recognizable, while the hash prevents
    collisions between same-named notes in different source folders.
    """
    normalized_path = str(note_file.expanduser().resolve())
    path_hash = hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:12]
    return f"{slugify(note_file.stem)}-{path_hash}"


def page_cache_path(note_file: Path) -> Path:
    return PAGE_CACHE_DIR / note_page_cache_id(note_file) / "cache.json"


def ocr_settings_fingerprint(provider: str | None = None) -> str:
    """
    Fingerprint OCR settings that can materially change cached page text.
    """
    selected_provider = (provider or OCR_PROVIDER).strip().lower() or "mistral"
    fingerprint_data: dict[str, object] = {
        "schema_version": PAGE_CACHE_SCHEMA_VERSION,
        "code_version": PAGE_CACHE_CODE_VERSION,
        "provider": selected_provider,
    }

    if selected_provider == "mistral":
        fingerprint_data["mistral"] = {
            "model": "mistral-ocr-latest",
            "custom_ocr_instruction": compose_custom_ocr_instruction(),
        }
    elif selected_provider in CLOUD_VLM_OCR_PROVIDERS:
        fingerprint_data["cloud_vlm"] = {
            "ocr_provider": selected_provider,
            "ocr_model": resolve_cloud_ocr_model(selected_provider),
            "ocr_reasoning_effort": resolve_ocr_reasoning_effort(),
            "visual_extraction": CLOUD_VISUAL_EXTRACTION_VERSION,
            "custom_ocr_instruction": compose_custom_ocr_instruction(),
            "prompt": build_cloud_vlm_ocr_prompt(),
            "rendering": {
                "dpi": PAGE_HASH_DPI,
                "alpha": PAGE_HASH_ALPHA,
            },
        }
    elif selected_provider == "local_ollama":
        fingerprint_data["local_ollama"] = {
            "model": LOCAL_OLLAMA_MODEL,
            "num_ctx": LOCAL_OLLAMA_NUM_CTX,
            "pipeline_version": LOCAL_OLLAMA_PIPELINE_VERSION,
            "qwen3_vl_chat_nothink": is_qwen3_vl_model(LOCAL_OLLAMA_MODEL),
            "prompt": resolve_local_ollama_prompt(LOCAL_OLLAMA_MODEL),
            "rendering": {
                "dpi": 200,
                "alpha": False,
            },
        }
    elif selected_provider == "hybrid_marker_olmocr":
        fingerprint_data["hybrid_marker_olmocr"] = {
            "model": LOCAL_OLLAMA_MODEL,
            "num_ctx": LOCAL_OLLAMA_NUM_CTX,
            "pipeline_version": LOCAL_OLLAMA_PIPELINE_VERSION,
            "qwen3_vl_chat_nothink": is_qwen3_vl_model(LOCAL_OLLAMA_MODEL),
            "prompt": resolve_local_ollama_prompt(LOCAL_OLLAMA_MODEL),
            "marker_command": HYBRID_MARKER_COMMAND,
            "marker_low_memory_profile": {
                "disable_multiprocessing": HYBRID_MARKER_DISABLE_MULTIPROCESSING,
                "layout_batch_size": HYBRID_MARKER_LAYOUT_BATCH_SIZE,
                "detection_batch_size": HYBRID_MARKER_DETECTION_BATCH_SIZE,
                "recognition_batch_size": HYBRID_MARKER_RECOGNITION_BATCH_SIZE,
                "table_rec_batch_size": HYBRID_MARKER_TABLE_REC_BATCH_SIZE,
                "lowres_image_dpi": HYBRID_MARKER_LOWRES_IMAGE_DPI,
                "highres_image_dpi": HYBRID_MARKER_HIGHRES_IMAGE_DPI,
                "disable_tqdm": HYBRID_MARKER_DISABLE_TQDM,
            },
            "table_conversion": "forgiving-html-v1",
            "visual_placement": "marker-order-v2",
            "qwen_visual_fallback": should_run_qwen_visual_fallback(),
            "rendering": {
                "dpi": 200,
                "alpha": False,
            },
        }
    else:
        fingerprint_data["unsupported_provider"] = selected_provider

    serialized = json.dumps(fingerprint_data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _cached_page_is_reusable(page: dict) -> bool:
    return bool(page.get("page_hash")) and isinstance(page.get("markdown"), str)


def reconcile_page_cache(
    current_page_hashes: list[str],
    cached_pages: list[dict],
    fingerprint: str,
    cached_fingerprint: str | None = None,
) -> dict:
    """
    Match current rendered page hashes against cached OCR pages.

    Same-position matches are preferred, then remaining pages are matched by
    hash so inserted/deleted pages can still reuse shifted cached OCR.
    """
    if cached_fingerprint is not None and cached_fingerprint != fingerprint:
        ordered_pages = [
            {
                "page_number": page_number,
                "page_hash": page_hash,
                "markdown": None,
                "reused": False,
            }
            for page_number, page_hash in enumerate(current_page_hashes, start=1)
        ]
        return {
            "ordered_pages": ordered_pages,
            "changed_pages": [page["page_number"] for page in ordered_pages],
            "reused_pages_count": 0,
            "pages_to_ocr_count": len(ordered_pages),
            "deleted_pages_count": max(0, len(cached_pages) - len(current_page_hashes)),
        }

    ordered_pages: list[dict] = []
    used_cached_indexes: set[int] = set()

    for current_index, page_hash in enumerate(current_page_hashes):
        cached_page = cached_pages[current_index] if current_index < len(cached_pages) else None
        if (
            isinstance(cached_page, dict)
            and _cached_page_is_reusable(cached_page)
            and cached_page.get("page_hash") == page_hash
        ):
            used_cached_indexes.add(current_index)
            ordered_pages.append(
                {
                    "page_number": current_index + 1,
                    "page_hash": page_hash,
                    "markdown": cached_page["markdown"],
                    "reused": True,
                }
            )
        else:
            ordered_pages.append(
                {
                    "page_number": current_index + 1,
                    "page_hash": page_hash,
                    "markdown": None,
                    "reused": False,
                }
            )

    cached_pages_by_hash: dict[str, list[tuple[int, dict]]] = {}
    for cached_index, cached_page in enumerate(cached_pages):
        if cached_index in used_cached_indexes:
            continue
        if not isinstance(cached_page, dict) or not _cached_page_is_reusable(cached_page):
            continue
        cached_pages_by_hash.setdefault(str(cached_page["page_hash"]), []).append(
            (cached_index, cached_page)
        )

    for ordered_page in ordered_pages:
        if ordered_page["reused"]:
            continue
        candidates = cached_pages_by_hash.get(ordered_page["page_hash"], [])
        while candidates and candidates[0][0] in used_cached_indexes:
            candidates.pop(0)
        if not candidates:
            continue
        cached_index, cached_page = candidates.pop(0)
        used_cached_indexes.add(cached_index)
        ordered_page["markdown"] = cached_page["markdown"]
        ordered_page["reused"] = True

    changed_pages = [
        page["page_number"]
        for page in ordered_pages
        if not page["reused"]
    ]
    return {
        "ordered_pages": ordered_pages,
        "changed_pages": changed_pages,
        "reused_pages_count": len(ordered_pages) - len(changed_pages),
        "pages_to_ocr_count": len(changed_pages),
        "deleted_pages_count": max(0, len(cached_pages) - len(current_page_hashes)),
    }


def load_page_cache(note_file: Path) -> dict | None:
    cache_file = page_cache_path(note_file)
    if not cache_file.exists():
        return None

    try:
        loaded_cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    return loaded_cache if isinstance(loaded_cache, dict) else None


def save_page_cache(note_file: Path, cache: dict) -> None:
    cache_file = page_cache_path(note_file)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_pixmap_for_cache(pixmap) -> str:
    """
    Hash stable visual pixmap data for page-level OCR cache matching.
    """
    colorspace = getattr(pixmap, "colorspace", None)
    colorspace_name = getattr(colorspace, "name", "") if colorspace is not None else ""
    hash_parts = [
        PAGE_HASH_VERSION,
        f"width={getattr(pixmap, 'width', '')}",
        f"height={getattr(pixmap, 'height', '')}",
        f"n={getattr(pixmap, 'n', '')}",
        f"alpha={getattr(pixmap, 'alpha', '')}",
        f"stride={getattr(pixmap, 'stride', '')}",
        f"colorspace={colorspace_name}",
    ]

    hasher = hashlib.sha256()
    hasher.update("\n".join(hash_parts).encode("utf-8"))
    hasher.update(b"\n")
    hasher.update(bytes(pixmap.samples))
    return hasher.hexdigest()


def render_pdf_page_hashes(pdf_file: Path) -> list[str]:
    """
    Render a PDF at fixed settings and return stable visual hashes per page.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "Page cache hashing requires PyMuPDF. Install it in the active Supsidian Python environment."
        ) from exc

    render_scale = PAGE_HASH_DPI / 72

    try:
        document = fitz.open(pdf_file)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF for page cache hashing: {pdf_file}: {exc}") from exc

    try:
        page_hashes = []
        for page_number, page in enumerate(document, start=1):
            try:
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(render_scale, render_scale),
                    alpha=PAGE_HASH_ALPHA,
                )
            except Exception as exc:
                raise RuntimeError(
                    f"Could not render page {page_number} for page cache hashing: {pdf_file}: {exc}"
                ) from exc
            page_hashes.append(hash_pixmap_for_cache(pixmap))
    finally:
        document.close()

    return page_hashes


# ------------------------------------------------------------
# MISTRAL OCR
# ------------------------------------------------------------

LOCAL_OLLAMA_PROMPT = """You are doing OCR on handwritten school notes.
Preserve the handwriting as exactly as possible.
Do not correct spelling, grammar, wording, or mathematical notation.
Keep line breaks where they help readability.

Tables:
If there is a table, convert it to a Markdown table.
Do not use HTML tables.
Do not use <table>, <tr>, <td>, or <th>.
If a table cell is empty, leave the Markdown cell empty.
If the table structure is unclear, write [unclear table] and then transcribe visible text line by line.

Math:
Only write mathematical notation when it is completely clear.
Use plain text math where possible, for example x^2, sqrt(3), 7/3.
Do not use LaTeX unless the handwriting clearly contains LaTeX.
If a formula, symbol, exponent, fraction, root, or variable is uncertain, write [unclear formula].
Do not guess.

Drawings:
If there is a drawing, write [drawing visible] and a short neutral label if obvious.
Do not invent details.

Do not invent missing content.
Do not summarize.
Return only the transcription."""

def mistral_ocr_pdf(pdf_file: Path, image_dir: Path, obsidian_image_folder: str) -> str:
    api_key = os.environ.get("MISTRAL_API_KEY")

    if not api_key:
        raise RuntimeError(
            f"MISTRAL_API_KEY not found. Check your env file: {ENV_FILE}"
        )

    image_dir.mkdir(parents=True, exist_ok=True)

    log(f"Starting Mistral OCR: {pdf_file}")

    encoded_pdf = base64.b64encode(pdf_file.read_bytes()).decode("utf-8")

    payload = {
        "model": "mistral-ocr-latest",
        "document": {
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{encoded_pdf}",
        },
        "include_image_base64": True,
    }

    effective_custom_instruction = compose_custom_ocr_instruction()
    if effective_custom_instruction:
        payload["document_annotation_prompt"] = effective_custom_instruction
        payload["document_annotation_format"] = {"type": "text"}

    response = requests.post(
        "https://api.mistral.ai/v1/ocr",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
    )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Mistral OCR request failed: {response.status_code} {response.text}"
        ) from exc

    data = response.json()
    markdown_parts = []

    for page in data.get("pages", []):
        page_number = int(page.get("index", 0)) + 1
        page_markdown = page.get("markdown", "")

        for image in page.get("images", []) or []:
            image_id = image.get("id")
            image_base64 = image.get("image_base64")

            if not image_id or not image_base64:
                continue

            if "," in image_base64:
                image_base64 = image_base64.split(",", 1)[1]

            image_bytes = base64.b64decode(image_base64)
            image_filename = f"page-{page_number}-{image_id}.png"
            image_path = image_dir / image_filename
            image_path.write_bytes(image_bytes)

            page_markdown = page_markdown.replace(
                f"![{image_id}]({image_id})",
                f"![[{obsidian_image_folder}/{image_filename}]]",
            )
            page_markdown = page_markdown.replace(
                f"![{image_id}]({image_id}.png)",
                f"![[{obsidian_image_folder}/{image_filename}]]",
            )
            page_markdown = page_markdown.replace(
                f"![{image_id}]({image_id}.jpg)",
                f"![[{obsidian_image_folder}/{image_filename}]]",
            )
            page_markdown = page_markdown.replace(
                f"![{image_id}]({image_id}.jpeg)",
                f"![[{obsidian_image_folder}/{image_filename}]]",
            )

        if page_number == 1:
            markdown_parts.append(f"## Page {page_number}\n\n")
        else:
            markdown_parts.append(f"\n\n---\n\n## Page {page_number}\n\n")

        markdown_parts.append(page_markdown)

    log(f"Mistral OCR finished: {pdf_file}")

    return "".join(markdown_parts).strip() + "\n"


QWEN3_VL_OCR_PROMPT = """Transcribe the handwritten notes on this page into clean Markdown.
Rules:
- Keep the original language, spelling, wording, headings, bullet lists, and meaningful line breaks exactly as written.
- Convert tables to Markdown tables (never use HTML tables).
- Transcribe clear mathematical notation accurately without guessing.
- Do not add any introduction, explanation, commentary, or summary.
- Return ONLY the transcribed Markdown text."""

QWEN3_VL_VISUAL_FALLBACK_PROMPT = """Inspect this handwritten note page for genuine hand-drawn sketches, diagrams, charts, or graphical tables.
Do NOT include normal body text, headings, bullet lists, or single underlines.
For each genuine drawing/diagram, return its tight bounding box `box_2d` as [ymin, xmin, ymax, xmax] in normalized integer coordinates from 0 to 1000 relative to page height and width, plus optional `anchor_before` and `anchor_after` (short exact text lines immediately above or below the drawing).
If there are no genuine drawings or diagrams on this page, return {"visuals": []}.
Return ONLY valid JSON:
{"visuals": [{"id": "VISUAL_1", "box_2d": [ymin, xmin, ymax, xmax], "anchor_before": "", "anchor_after": ""}]}"""

THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)


def is_qwen3_vl_model(model_name: str | None = None) -> bool:
    candidate = (model_name if model_name is not None else LOCAL_OLLAMA_MODEL).strip().lower()
    return "qwen3-vl" in candidate


def is_qwen3_vl_thinking_model(model_name: str | None = None) -> bool:
    candidate = (model_name if model_name is not None else LOCAL_OLLAMA_MODEL).strip().lower()
    return "qwen3-vl" in candidate and "-instruct" not in candidate


def should_run_qwen_visual_fallback(model_name: str | None = None) -> bool:
    return bool(HYBRID_QWEN_VISUAL_FALLBACK) and is_qwen3_vl_model(model_name)


def resolve_local_ollama_prompt(model_name: str | None = None) -> str:
    base_prompt = QWEN3_VL_OCR_PROMPT if is_qwen3_vl_model(model_name) else LOCAL_OLLAMA_PROMPT
    effective_custom_instruction = compose_custom_ocr_instruction()
    if effective_custom_instruction:
        return f"{base_prompt}\n\nAdditional user instructions:\n{effective_custom_instruction}"
    return base_prompt


def local_ollama_chat_url(url: str | None = None) -> str:
    target = (url or LOCAL_OLLAMA_URL).strip() or "http://localhost:11434/api/generate"
    parsed = urlsplit(target)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid local_ollama_url: {target}")
    path = parsed.path.rstrip("/")
    if path.endswith("/api/generate"):
        chat_path = path[: -len("/api/generate")] + "/api/chat"
    elif path.endswith("/api/chat"):
        chat_path = path
    else:
        chat_path = "/api/chat"
    return urlunsplit((parsed.scheme, parsed.netloc, chat_path, "", ""))


def strip_thinking_blocks(text: str) -> str:
    return THINK_BLOCK_PATTERN.sub("", text).strip()


def render_ollama_page_pixmap(
    page,
    dpi: int = 200,
    max_long_edge_px: int | None = None,
):
    """
    Render a PDF page for local Ollama vision models, capping the longest edge
    to keep vision token counts bounded on 16 GB Macs while preserving legibility.
    """
    import fitz  # PyMuPDF

    render_scale = dpi / 72.0
    cap = LOCAL_OLLAMA_MAX_IMAGE_EDGE_PX if max_long_edge_px is None else int(max_long_edge_px)
    rect = getattr(page, "rect", None)
    if cap > 0 and rect is not None:
        long_edge_pt = max(float(getattr(rect, "width", 0.0)), float(getattr(rect, "height", 0.0)))
        if long_edge_pt > 0 and long_edge_pt * render_scale > cap:
            render_scale = cap / long_edge_pt

    return page.get_pixmap(
        matrix=fitz.Matrix(render_scale, render_scale),
        alpha=False,
    )


def unload_local_ollama_model_via_api(model_name: str | None = None) -> bool:
    target_model = (model_name or LOCAL_OLLAMA_MODEL).strip()
    if not target_model:
        return False

    try:
        if is_qwen3_vl_model(target_model):
            endpoint = local_ollama_chat_url(LOCAL_OLLAMA_URL)
            payload: dict[str, object] = {
                "model": target_model,
                "messages": [],
                "stream": False,
                "keep_alive": 0,
            }
        else:
            endpoint = LOCAL_OLLAMA_URL
            payload = {
                "model": target_model,
                "prompt": "",
                "stream": False,
                "keep_alive": 0,
            }

        started = time.monotonic()
        response = requests.post(
            endpoint,
            headers={"Connection": "close"},
            json=payload,
            timeout=(10, 30),
        )
        elapsed = time.monotonic() - started
        if response.ok:
            log(f"Unloaded Ollama model via keep_alive=0 in {elapsed:.1f}s: {target_model}")
            return True

        detail = response.text.strip().replace("\n", " ")[:300]
        log(
            f"Could not unload Ollama model via keep_alive=0 "
            f"({target_model}, HTTP {response.status_code}): {detail}"
        )
        return False
    except Exception as exc:
        log(f"Could not unload Ollama model via keep_alive=0 ({target_model}): {exc}")
        return False


def ollama_ocr_selected_pdf_pages(pdf_file: Path, page_numbers: list[int]) -> dict[int, str]:
    if not page_numbers:
        return {}

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "local_ollama requires PyMuPDF. Install it in the active Supsidian Python environment."
        ) from exc

    render_scale = 200 / 72
    selected_pages = sorted(set(page_numbers))
    page_transcriptions: dict[int, str] = {}

    try:
        document = fitz.open(pdf_file)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF for local_ollama OCR: {pdf_file}: {exc}") from exc

    try:
        if len(document) == 0:
            raise RuntimeError(f"PDF has no pages for local_ollama OCR: {pdf_file}")
        invalid_pages = [
            page_number
            for page_number in selected_pages
            if page_number < 1 or page_number > len(document)
        ]
        if invalid_pages:
            raise RuntimeError(
                f"Invalid local_ollama OCR page number(s) for {pdf_file}: {invalid_pages}"
            )

        with tempfile.TemporaryDirectory(prefix="supsidian-local-ocr-") as temporary_directory:
            temporary_dir = Path(temporary_directory)
            changed_index = 0

            for page_number, page in enumerate(document, start=1):
                if page_number not in selected_pages:
                    continue

                changed_index += 1
                progress_event(
                    "ocr",
                    provider=OCR_PROVIDER,
                    page=page_number,
                    total_pages=len(document),
                    changed_index=changed_index,
                    changed_count=len(selected_pages),
                )
                page_path = temporary_dir / f"page-{page_number:03d}.png"
                pixmap = render_ollama_page_pixmap(page, dpi=200)
                pixmap.save(page_path)

                encoded_image = base64.b64encode(page_path.read_bytes()).decode("ascii")
                use_qwen_chat = is_qwen3_vl_model(LOCAL_OLLAMA_MODEL)
                ollama_options: dict[str, object] = {
                    "num_ctx": LOCAL_OLLAMA_NUM_CTX,
                    "num_predict": LOCAL_OLLAMA_NUM_PREDICT,
                    "repeat_penalty": LOCAL_OLLAMA_REPEAT_PENALTY,
                }
                if use_qwen_chat:
                    request_url = local_ollama_chat_url(LOCAL_OLLAMA_URL)
                    payload = {
                        "model": LOCAL_OLLAMA_MODEL,
                        "messages": [
                            {
                                "role": "user",
                                "content": resolve_local_ollama_prompt(LOCAL_OLLAMA_MODEL),
                                "images": [encoded_image],
                            }
                        ],
                        "stream": False,
                        "think": False,
                        "options": ollama_options,
                    }
                else:
                    request_url = LOCAL_OLLAMA_URL
                    payload = {
                        "model": LOCAL_OLLAMA_MODEL,
                        "prompt": resolve_local_ollama_prompt(LOCAL_OLLAMA_MODEL),
                        "stream": False,
                        "images": [encoded_image],
                        "options": ollama_options,
                    }

                page_started = time.monotonic()
                try:
                    response = requests.post(
                        request_url,
                        headers={"Connection": "close"},
                        json=payload,
                        timeout=(10, LOCAL_OLLAMA_PAGE_TIMEOUT_SECONDS),
                    )
                except requests.Timeout as exc:
                    raise RuntimeError(
                        f"Ollama timed out after {LOCAL_OLLAMA_PAGE_TIMEOUT_SECONDS}s "
                        f"on page {page_number} (model='{LOCAL_OLLAMA_MODEL}')."
                    ) from exc
                except requests.ConnectionError as exc:
                    raise RuntimeError(
                        f"Could not connect to Ollama at {request_url}. "
                        "Start Ollama, then ensure the model is installed with: "
                        f"ollama pull {LOCAL_OLLAMA_MODEL}"
                    ) from exc
                except requests.RequestException as exc:
                    raise RuntimeError(
                        f"Ollama request failed for page {page_number}: {exc}"
                    ) from exc
                page_elapsed = time.monotonic() - page_started

                if not response.ok:
                    detail = response.text.strip()
                    lower_detail = detail.lower()
                    if response.status_code == 400 and "context" in lower_detail:
                        raise RuntimeError(
                            f"Ollama context overflow on page {page_number}: {detail}. "
                            "Increase local_ollama_num_ctx."
                        )
                    if response.status_code == 404 or (
                        "model" in lower_detail
                        and any(
                            message in lower_detail
                            for message in ("not found", "unavailable", "does not exist", "unknown")
                        )
                    ):
                        raise RuntimeError(
                            f"Ollama model '{LOCAL_OLLAMA_MODEL}' is missing or unavailable. "
                            f"Run: ollama pull {LOCAL_OLLAMA_MODEL}"
                        )
                    raise RuntimeError(
                        f"Ollama returned HTTP {response.status_code} for page {page_number}: {detail}"
                    )

                try:
                    response_data = response.json()
                except ValueError as exc:
                    raise RuntimeError(
                        f"Ollama returned invalid JSON for page {page_number}: {response.text}"
                    ) from exc

                prompt_eval_count = response_data.get("prompt_eval_count")
                eval_count = response_data.get("eval_count")
                done_reason = response_data.get("done_reason")
                log(
                    f"Ollama OCR page {page_number}/{len(document)} finished in {page_elapsed:.1f}s "
                    f"(model={LOCAL_OLLAMA_MODEL}, prompt_eval_count={prompt_eval_count}, "
                    f"eval_count={eval_count}, done_reason={done_reason}, "
                    f"image={pixmap.width}x{pixmap.height})"
                )

                message_obj = response_data.get("message") if use_qwen_chat else None
                if use_qwen_chat:
                    page_markdown = (
                        message_obj.get("content")
                        if isinstance(message_obj, dict)
                        else response_data.get("response")
                    )
                else:
                    page_markdown = response_data.get("response")

                if not isinstance(page_markdown, str):
                    raise RuntimeError(
                        f"Ollama did not return OCR text for page {page_number}: "
                        f"{json.dumps(response_data)}"
                    )

                cleaned_markdown = strip_thinking_blocks(page_markdown)
                if not cleaned_markdown:
                    thinking_text = (
                        message_obj.get("thinking")
                        if isinstance(message_obj, dict)
                        else response_data.get("thinking")
                    )
                    has_thinking = isinstance(thinking_text, str) and bool(thinking_text.strip())
                    eval_count_int = eval_count if isinstance(eval_count, int) else 0
                    hit_length = str(done_reason or "").strip().lower() == "length"
                    if eval_count_int > 0 or has_thinking or hit_length:
                        suggestion = (
                            " Use 'qwen3-vl:8b-instruct' instead of 'qwen3-vl:8b' to avoid thinking-only output."
                            if is_qwen3_vl_thinking_model(LOCAL_OLLAMA_MODEL)
                            else " Use a non-thinking instruct model or increase local_ollama_num_predict."
                        )
                        raise RuntimeError(
                            f"Ollama returned empty OCR content on page {page_number} after generating "
                            f"{eval_count_int} token(s) (done_reason={done_reason}, model='{LOCAL_OLLAMA_MODEL}'). "
                            f"The model spent its output tokens in thinking mode.{suggestion}"
                        )

                page_transcriptions[page_number] = cleaned_markdown
    finally:
        document.close()

    return page_transcriptions


def ollama_ocr_pdf_pages(pdf_file: Path) -> list[str]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "local_ollama requires PyMuPDF. Install it in the active Supsidian Python environment."
        ) from exc

    try:
        document = fitz.open(pdf_file)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF for local_ollama OCR: {pdf_file}: {exc}") from exc

    try:
        page_numbers = list(range(1, len(document) + 1))
    finally:
        document.close()

    page_transcriptions = ollama_ocr_selected_pdf_pages(pdf_file, page_numbers)
    return [page_transcriptions[page_number] for page_number in page_numbers]


EXISTING_PAGE_HEADING_PATTERN = re.compile(r"^## Page (\d+)\s*$")
ORIGINAL_PDF_FOOTER_PATTERN = re.compile(
    r"\n*---\n+## Original PDF\n+!\[\[.*?\]\]\s*\Z",
    re.DOTALL,
)


def parse_existing_markdown_note(md_file: Path) -> tuple[str, dict[int, str]]:
    """
    Parse an existing Obsidian Markdown note into (preamble, {page_number: page_markdown}).
    Preserves manual edits on unchanged pages when updating a note in place.
    """
    if not md_file.exists():
        return "", {}

    try:
        raw_text = md_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", {}

    body_text = ORIGINAL_PDF_FOOTER_PATTERN.sub("", raw_text).strip("\n")
    if not body_text.strip():
        return "", {}

    lines = body_text.splitlines()
    heading_positions: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = EXISTING_PAGE_HEADING_PATTERN.match(line.strip())
        if match:
            heading_positions.append((index, int(match.group(1))))

    if not heading_positions:
        return "", {}

    first_heading_line = heading_positions[0][0]
    preamble = "\n".join(lines[:first_heading_line]).strip()
    pages: dict[int, str] = {}

    for pos_index, (start_line, page_number) in enumerate(heading_positions):
        end_line = (
            heading_positions[pos_index + 1][0]
            if pos_index + 1 < len(heading_positions)
            else len(lines)
        )
        section_lines = lines[start_line + 1 : end_line]
        while section_lines and not section_lines[-1].strip():
            section_lines.pop()
        if (
            pos_index + 1 < len(heading_positions)
            and section_lines
            and section_lines[-1].strip() == "---"
        ):
            section_lines.pop()
            while section_lines and not section_lines[-1].strip():
                section_lines.pop()
        while section_lines and not section_lines[0].strip():
            section_lines.pop(0)

        pages[page_number] = "\n".join(section_lines)

    return preamble, pages


def format_ocr_pages(page_transcriptions: list[str], preamble: str = "") -> str:
    markdown_parts = []
    clean_preamble = preamble.strip()
    if clean_preamble:
        markdown_parts.append(f"{clean_preamble}\n\n")

    for page_number, page_markdown in enumerate(page_transcriptions, start=1):
        if page_number == 1:
            markdown_parts.append(f"## Page {page_number}\n\n")
        else:
            markdown_parts.append(f"\n\n---\n\n## Page {page_number}\n\n")
        markdown_parts.append(page_markdown)

    return "".join(markdown_parts).strip() + "\n"


def local_ollama_ocr_pdf(
    pdf_file: Path,
    image_dir: Path,
    obsidian_image_folder: str,
) -> str:
    log(f"Starting local Ollama OCR: {pdf_file}")
    page_transcriptions = ollama_ocr_pdf_pages(pdf_file)
    log(f"Local Ollama OCR finished: {pdf_file}")
    return format_ocr_pages(page_transcriptions)


def unload_local_ollama_model_after_note() -> None:
    if not LOCAL_OLLAMA_UNLOAD_AFTER_NOTE:
        return

    try:
        result = subprocess.run(
            ["ollama", "stop", LOCAL_OLLAMA_MODEL],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        log("Could not unload Ollama model after note: ollama command not found")
        return
    except Exception as exc:
        log(f"Could not unload Ollama model after note: {exc}")
        return

    if result.returncode == 0:
        log(f"Unloaded Ollama model after note: {LOCAL_OLLAMA_MODEL}")
    else:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        detail = detail[:1000] or "no output"
        log(
            f"Could not unload Ollama model after note "
            f"({LOCAL_OLLAMA_MODEL}): {detail}"
        )


def incremental_ollama_page_transcriptions(
    pdf_file: Path,
    note_file: Path,
    provider: str,
    fingerprint: str,
    existing_md_pages: dict[int, str] | None = None,
) -> tuple[list[str], dict]:
    current_page_hashes = render_pdf_page_hashes(pdf_file)
    cache = load_page_cache(note_file) or {}
    cached_pages = cache.get("pages", [])
    if not isinstance(cached_pages, list):
        cached_pages = []
    cached_fingerprint = cache.get("ocr_fingerprint")
    cached_fingerprint = cached_fingerprint if isinstance(cached_fingerprint, str) else None

    # Bootstrap cache from an existing Obsidian .md note when pages were appended
    # and no page cache file existed yet.
    if (
        not cached_pages
        and existing_md_pages
        and len(current_page_hashes) > len(existing_md_pages)
        and all(page_num in existing_md_pages for page_num in range(1, len(existing_md_pages) + 1))
    ):
        cached_pages = [
            {
                "page_number": page_num,
                "page_hash": current_page_hashes[page_num - 1],
                "markdown": existing_md_pages[page_num],
            }
            for page_num in range(1, len(existing_md_pages) + 1)
        ]
        cached_fingerprint = fingerprint

    # When an existing Obsidian note is already present on disk, keep page-hash
    # baselines across minor settings/version fingerprint updates as long as the
    # provider and Ollama model did not change. Switching models (e.g. olmocr2 ->
    # qwen3-vl:8b) cleanly invalidates the cache so pages are reprocessed.
    cached_provider = cache.get("provider")
    cached_model = cache.get("model")
    same_provider_and_model = (
        (not cached_provider or cached_provider == provider)
        and (not cached_model or cached_model == LOCAL_OLLAMA_MODEL)
    )
    effective_cached_fingerprint = (
        fingerprint
        if (existing_md_pages and cached_pages and same_provider_and_model)
        else cached_fingerprint
    )

    if cached_fingerprint and effective_cached_fingerprint != fingerprint:
        log(f"{provider} page cache invalidated due to OCR settings fingerprint change")

    reconciliation = reconcile_page_cache(
        current_page_hashes,
        cached_pages,
        fingerprint,
        cached_fingerprint=effective_cached_fingerprint,
    )
    pages_to_ocr = reconciliation["changed_pages"]
    new_page_markdown = (
        ollama_ocr_selected_pdf_pages(pdf_file, pages_to_ocr)
        if pages_to_ocr
        else {}
    )

    page_transcriptions: list[str] = []
    updated_pages: list[dict] = []
    updated_at = utc_now_iso()

    for ordered_page in reconciliation["ordered_pages"]:
        page_number = ordered_page["page_number"]
        if ordered_page["reused"]:
            same_position_hash = (
                page_number - 1 < len(cached_pages)
                and isinstance(cached_pages[page_number - 1], dict)
                and cached_pages[page_number - 1].get("page_hash") == ordered_page["page_hash"]
            )
            if (
                existing_md_pages
                and same_position_hash
                and page_number in existing_md_pages
            ):
                markdown = existing_md_pages[page_number]
            else:
                markdown = ordered_page["markdown"]
        else:
            if page_number not in new_page_markdown:
                raise RuntimeError(
                    f"{provider} did not return Ollama OCR text for changed page {page_number}"
                )
            markdown = new_page_markdown[page_number]

        page_transcriptions.append(markdown)
        updated_pages.append(
            {
                "page_number": page_number,
                "page_hash": ordered_page["page_hash"],
                "markdown": markdown,
                "assets": [],
                "updated_at": updated_at,
            }
        )

    cache_data = {
        "schema_version": PAGE_CACHE_SCHEMA_VERSION,
        "note_path": str(note_file.expanduser().resolve()),
        "note_cache_id": note_page_cache_id(note_file),
        "ocr_fingerprint": fingerprint,
        "provider": provider,
        "model": LOCAL_OLLAMA_MODEL,
        "updated_at": updated_at,
        "pages": updated_pages,
        "last_run": {
            "page_count": len(current_page_hashes),
            "changed_pages": pages_to_ocr,
            "reused_pages_count": reconciliation["reused_pages_count"],
            "pages_to_ocr_count": reconciliation["pages_to_ocr_count"],
            "deleted_pages_count": reconciliation["deleted_pages_count"],
        },
    }
    save_page_cache(note_file, cache_data)

    log(
        f"{provider} page cache: "
        f"reused {reconciliation['reused_pages_count']} page(s), "
        f"OCRed {reconciliation['pages_to_ocr_count']} page(s), "
        f"changed pages: {pages_to_ocr}"
    )
    return page_transcriptions, reconciliation


def update_page_cache_markdown(note_file: Path, page_transcriptions: list[str]) -> None:
    """
    Update cached page Markdown after provider-specific enrichment.

    Incremental Ollama caches raw page text first. Hybrid Marker + Ollama can then
    add silent image embeds to changed pages. Persisting that final page Markdown
    lets unchanged pages keep their previously extracted visuals on later syncs.
    """
    cache = load_page_cache(note_file)
    if not cache:
        return

    cached_pages = cache.get("pages")
    if not isinstance(cached_pages, list) or len(cached_pages) != len(page_transcriptions):
        return

    updated_at = utc_now_iso()
    for page, page_markdown in zip(cached_pages, page_transcriptions):
        if isinstance(page, dict):
            page["markdown"] = page_markdown
            page["updated_at"] = updated_at

    cache["updated_at"] = updated_at
    save_page_cache(note_file, cache)


def local_ollama_ocr_pdf_incremental(
    pdf_file: Path,
    image_dir: Path,
    obsidian_image_folder: str,
    note_file: Path,
) -> str:
    log(f"Starting incremental local Ollama OCR: {pdf_file}")
    md_file = OBSIDIAN_NOTE_DIR / f"{safe_name(note_file)}.md"
    preamble, existing_md_pages = parse_existing_markdown_note(md_file)
    page_transcriptions, reconciliation = incremental_ollama_page_transcriptions(
        pdf_file,
        note_file,
        "local_ollama",
        ocr_settings_fingerprint("local_ollama"),
        existing_md_pages=existing_md_pages,
    )
    changed_set = set(reconciliation["changed_pages"])
    for index, page_text in enumerate(page_transcriptions):
        if (index + 1) in changed_set or not existing_md_pages:
            page_transcriptions[index] = convert_hash_lines_to_tasks(page_text)
    update_page_cache_markdown(note_file, page_transcriptions)
    log(f"Incremental local Ollama OCR finished: {pdf_file}")
    return format_ocr_pages(page_transcriptions, preamble=preamble)


HTML_TABLE_PATTERN = re.compile(r"<table\b[^>]*>.*?</table\s*>", re.IGNORECASE | re.DOTALL)
MARKER_IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
OBSIDIAN_IMAGE_EMBED_PATTERN = re.compile(r"!\[\[[^\]]+\]\]")
GENERATED_VISUAL_DESCRIPTION_PATTERN = re.compile(
    r"^(?:"
    r"\[drawing visible\].*|"
    r"(?:this|the)\s+(?:image|drawing|diagram|picture|visual)\s+"
    r"(?:shows|contains|depicts|is)\b.*"
    r")$",
    re.IGNORECASE,
)
GENERATED_VISUAL_HEADING_PATTERN = re.compile(
    r"^#{1,6}\s+Extracted visuals\s*$",
    re.IGNORECASE,
)
MARKER_PAGE_FILENAME_PATTERN = re.compile(
    r"(?:^|[-_ ])page[-_ ]?0*(\d+)(?:[-_ ].*)?$",
    re.IGNORECASE,
)
MARKER_PAGE_HEADING_PATTERN = re.compile(r"^#{1,6}\s+.*?\bpage\s+(\d+)\b", re.IGNORECASE)
MARKER_SUSPICIOUS_FULL_PAGE_PATTERN = re.compile(
    r"(?:^|[-_ ])(?:full[-_ ]?page|page[-_ ]?render|rendered[-_ ]?page)(?:[-_ ]|$)",
    re.IGNORECASE,
)
MARKER_NUMBERED_PAGE_RENDER_PATTERN = re.compile(
    r"^[-_ ]*page[-_ ]?0*\d+[-_ ]*$",
    re.IGNORECASE,
)


class SimpleHTMLTableParser(HTMLParser):
    """Parse flat HTML tables conservatively, with an optional forgiving mode."""

    def __init__(self, forgiving: bool = False) -> None:
        super().__init__(convert_charrefs=True)
        self.forgiving = forgiving
        self.rows: list[list[tuple[str, list[str]]]] = []
        self.current_row: list[tuple[str, list[str]]] | None = None
        self.current_cell: list[str] | None = None
        self.formatting_tags: list[str] = []
        self.table_depth = 0
        self.valid = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attribute_names = {name.lower() for name, _ in attrs}

        if tag == "table":
            self.table_depth += 1
            if self.table_depth != 1:
                self.valid = False
            return
        if tag in {"thead", "tbody", "tfoot"}:
            return
        if tag == "tr":
            if self.current_row is not None or self.table_depth != 1:
                self.valid = False
            self.current_row = []
            return
        if tag in {"th", "td"}:
            if self.current_row is None or self.current_cell is not None:
                self.valid = False
                return
            if {"rowspan", "colspan"} & attribute_names:
                self.valid = False
                return
            self.current_cell = []
            self.current_row.append((tag, self.current_cell))
            return
        if tag == "br" and self.current_cell is not None:
            self.current_cell.append("\n")
            return
        if self.forgiving and tag in {"i", "em", "b", "strong"} and self.current_cell is not None:
            self.formatting_tags.append(tag)
            return
        if self.forgiving and tag == "sup" and self.current_cell is not None:
            self.current_cell.append("^")
            self.formatting_tags.append(tag)
            return
        self.valid = False

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "table":
            self.table_depth -= 1
            if self.table_depth < 0:
                self.valid = False
            return
        if tag in {"thead", "tbody", "tfoot"}:
            return
        if tag in {"th", "td"}:
            if self.current_cell is None:
                self.valid = False
            self.current_cell = None
            return
        if tag == "tr":
            if self.current_row is None or self.current_cell is not None:
                self.valid = False
                return
            self.rows.append(self.current_row)
            self.current_row = None
            return
        if self.forgiving and tag in {"i", "em", "b", "strong", "sup"}:
            if not self.formatting_tags or self.formatting_tags.pop() != tag:
                self.valid = False
            return
        if tag != "br":
            self.valid = False

    def handle_data(self, data: str) -> None:
        if self.current_cell is not None:
            self.current_cell.append(data)
        elif data.strip():
            self.valid = False

    def close(self) -> None:
        super().close()
        if (
            self.table_depth != 0
            or self.current_row is not None
            or self.current_cell is not None
            or self.formatting_tags
        ):
            self.valid = False


def markdown_cell(cell_parts: list[str]) -> str:
    lines = [" ".join(part.split()) for part in "".join(cell_parts).splitlines()]
    value = " / ".join(part for part in lines if part)
    return value.replace("|", "\\|")


def html_table_to_markdown(html_table: str, forgiving: bool = False) -> str | None:
    parser = SimpleHTMLTableParser(forgiving=forgiving)
    try:
        parser.feed(html_table)
        parser.close()
    except Exception:
        return None

    if not parser.valid or not parser.rows:
        return None

    column_count = max(len(row) for row in parser.rows)
    if column_count == 0 or (not forgiving and any(len(row) != column_count for row in parser.rows)):
        return None

    header_index = next(
        (index for index, row in enumerate(parser.rows) if all(tag == "th" for tag, _ in row)),
        None,
    )
    if forgiving:
        for index, row in enumerate(parser.rows):
            padding_tag = "th" if index == header_index else "td"
            row.extend((padding_tag, []) for _ in range(column_count - len(row)))

    if header_index is None:
        header = [""] * column_count
        body_rows = parser.rows
    else:
        header = [markdown_cell(cell) for _, cell in parser.rows[header_index]]
        body_rows = parser.rows[:header_index] + parser.rows[header_index + 1 :]

    markdown_lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join("---" for _ in range(column_count)) + " |",
    ]
    for row in body_rows:
        markdown_lines.append("| " + " | ".join(markdown_cell(cell) for _, cell in row) + " |")
    return "\n".join(markdown_lines)


def convert_html_tables(text: str, forgiving: bool = False) -> tuple[str, int, int]:
    converted_count = 0
    unchanged_count = 0

    def replace_table(match: re.Match[str]) -> str:
        nonlocal converted_count, unchanged_count
        markdown_table = html_table_to_markdown(match.group(0), forgiving=forgiving)
        if markdown_table is None:
            unchanged_count += 1
            return match.group(0)
        converted_count += 1
        return markdown_table

    return HTML_TABLE_PATTERN.sub(replace_table, text), converted_count, unchanged_count


def is_path_inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def marker_page_index_from_filename(path: Path) -> int | None:
    match = MARKER_PAGE_FILENAME_PATTERN.match(path.stem)
    return int(match.group(1)) if match else None


def nearby_marker_text(lines: list[str], image_line_index: int, step: int) -> str | None:
    index = image_line_index + step
    while 0 <= index < len(lines):
        candidate = lines[index].strip()
        if candidate and not MARKER_IMAGE_LINK_PATTERN.search(candidate):
            return candidate
        index += step
    return None


def run_hybrid_marker(
    pdf_file: Path,
    marker_output_dir: Path,
    page_range: str | None = None,
) -> None:
    marker_command = shutil.which(HYBRID_MARKER_COMMAND)
    if not marker_command:
        raise RuntimeError(
            "hybrid_marker_olmocr requires marker_single. Install Marker and ensure "
            "marker_single is on PATH."
        )

    marker_output_dir.mkdir(parents=True, exist_ok=True)
    marker_args = [
        marker_command,
        str(pdf_file),
        "--output_dir",
        str(marker_output_dir),
        "--output_format",
        "markdown",
        "--force_ocr",
    ]

    if HYBRID_MARKER_DISABLE_MULTIPROCESSING:
        marker_args.append("--disable_multiprocessing")

    marker_args.extend(
        [
            "--layout_batch_size",
            str(HYBRID_MARKER_LAYOUT_BATCH_SIZE),
            "--detection_batch_size",
            str(HYBRID_MARKER_DETECTION_BATCH_SIZE),
            "--recognition_batch_size",
            str(HYBRID_MARKER_RECOGNITION_BATCH_SIZE),
            "--table_rec_batch_size",
            str(HYBRID_MARKER_TABLE_REC_BATCH_SIZE),
            "--lowres_image_dpi",
            str(HYBRID_MARKER_LOWRES_IMAGE_DPI),
            "--highres_image_dpi",
            str(HYBRID_MARKER_HIGHRES_IMAGE_DPI),
        ]
    )

    if HYBRID_MARKER_DISABLE_TQDM:
        marker_args.append("--disable_tqdm")

    if page_range is not None:
        marker_args.extend(["--page_range", page_range])

    result = subprocess.run(
        marker_args,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        detail = detail[:1000] or "no output"
        raise RuntimeError(f"Marker failed with exit status {result.returncode}: {detail}")


def run_hybrid_marker_for_page(
    pdf_file: Path,
    marker_output_dir: Path,
    page_number: int,
) -> None:
    run_hybrid_marker(
        pdf_file,
        marker_output_dir,
        page_range=str(page_number - 1),
    )


def clean_and_save_marker_visual(
    source_path: Path,
    destination_path: Path,
    min_width: int = MARKER_VISUAL_MIN_WIDTH_PX,
    min_height: int = MARKER_VISUAL_MIN_HEIGHT_PX,
    min_ink_ratio: float = MARKER_VISUAL_MIN_INK_RATIO,
    trim_margin_px: int = MARKER_VISUAL_TRIM_MARGIN_PX,
    white_threshold: int = CLOUD_VISUAL_WHITE_THRESHOLD,
) -> bool:
    """
    Filter out mini-artifacts / nearly blank Marker crops and gently trim whitespace.

    Falls back to raw file copy if Pillow is unavailable or the file is not a raster image
    (preserving compatibility with synthetic unit-test placeholders).
    """
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        shutil.copy2(source_path, destination_path)
        return True

    try:
        with Image.open(source_path) as raw_image:
            width, height = raw_image.size
            if width < min_width or height < min_height:
                return False

            rgb_image = raw_image.convert("RGB")
            gray = rgb_image.convert("L")
            non_white_mask = gray.point(lambda pixel: 255 if pixel < white_threshold else 0)
            content_bbox = non_white_mask.getbbox()
            if content_bbox is None:
                return False

            non_white_pixels = non_white_mask.histogram()[255]
            ink_ratio = non_white_pixels / float(max(1, width * height))
            c_left, c_top, c_right, c_bottom = content_bbox
            if ink_ratio < min_ink_ratio or (c_right - c_left) < 16 or (c_bottom - c_top) < 16:
                return False

            margin = max(0, int(trim_margin_px))
            trimmed_box = (
                max(0, c_left - margin),
                max(0, c_top - margin),
                min(width, c_right + margin),
                min(height, c_bottom + margin),
            )
            trimmed = rgb_image.crop(trimmed_box)

            destination_path.parent.mkdir(parents=True, exist_ok=True)
            suffix = destination_path.suffix.lower()
            if suffix in {".jpg", ".jpeg"}:
                trimmed.save(destination_path, format="JPEG", quality=90)
            elif suffix == ".png":
                trimmed.save(destination_path, format="PNG")
            elif suffix == ".webp":
                trimmed.save(destination_path, format="WEBP", quality=90)
            else:
                trimmed.save(destination_path)
            return True
    except UnidentifiedImageError:
        shutil.copy2(source_path, destination_path)
        return True


def copy_marker_visuals(
    marker_dir: Path,
    extracted_visual_dir: Path,
    assigned_page_override: int | None = None,
) -> list[dict]:
    """Copy only Marker-declared local image assets into the note attachment folder."""
    visuals: list[dict] = []
    copied_sources: set[Path] = set()
    page_visual_counts: dict[int, int] = {}
    unassigned_visual_count = 0
    extracted_visual_dir.mkdir(parents=True, exist_ok=True)

    for markdown_file in sorted(marker_dir.rglob("*.md")):
        markdown_text = markdown_file.read_text(encoding="utf-8", errors="replace")
        markdown_lines = markdown_text.splitlines()
        current_page: int | None = None

        for line_number, line in enumerate(markdown_lines, start=1):
            heading_match = MARKER_PAGE_HEADING_PATTERN.match(line.strip())
            if heading_match:
                current_page = int(heading_match.group(1))

            for link_match in MARKER_IMAGE_LINK_PATTERN.finditer(line):
                raw_link = link_match.group(1).strip()
                if raw_link.startswith(("http://", "https://", "data:", "#")):
                    continue

                source_path = (markdown_file.parent / raw_link).resolve()
                if (
                    not is_path_inside(source_path, marker_dir)
                    or not source_path.is_file()
                    or source_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}
                    or MARKER_SUSPICIOUS_FULL_PAGE_PATTERN.search(source_path.stem)
                    or MARKER_NUMBERED_PAGE_RENDER_PATTERN.match(source_path.stem)
                    or source_path in copied_sources
                ):
                    continue

                marker_page_index = marker_page_index_from_filename(source_path)
                assigned_page = marker_page_index + 1 if marker_page_index is not None else current_page
                if assigned_page_override is not None and assigned_page in {None, 1}:
                    assigned_page = assigned_page_override

                if assigned_page is not None:
                    page_visual_counts[assigned_page] = page_visual_counts.get(assigned_page, 0) + 1
                    visual_index = page_visual_counts[assigned_page]
                    destination_name = (
                        f"page-{assigned_page:03d}-visual-{visual_index:03d}{source_path.suffix.lower()}"
                    )
                else:
                    unassigned_visual_count += 1
                    destination_name = (
                        f"marker-visual-{unassigned_visual_count:03d}{source_path.suffix.lower()}"
                    )

                destination = extracted_visual_dir / destination_name
                while destination.exists():
                    visual_index = page_visual_counts.get(assigned_page, unassigned_visual_count) + 1
                    if assigned_page is not None:
                        page_visual_counts[assigned_page] = visual_index
                        destination = extracted_visual_dir / (
                            f"page-{assigned_page:03d}-visual-{visual_index:03d}"
                            f"{source_path.suffix.lower()}"
                        )
                    else:
                        unassigned_visual_count = visual_index
                        destination = extracted_visual_dir / (
                            f"marker-visual-{visual_index:03d}{source_path.suffix.lower()}"
                        )

                copied_sources.add(source_path)
                if not clean_and_save_marker_visual(source_path, destination):
                    if assigned_page is not None:
                        page_visual_counts[assigned_page] = max(0, page_visual_counts.get(assigned_page, 1) - 1)
                    else:
                        unassigned_visual_count = max(0, unassigned_visual_count - 1)
                    log(f"Filtered out blank or tiny Marker visual artifact: {source_path.name}")
                    continue

                visuals.append(
                    {
                        "copied_filename": destination.name,
                        "assigned_page": assigned_page,
                        "marker_page_index": marker_page_index,
                        "marker_text_before": nearby_marker_text(markdown_lines, line_number - 1, -1),
                        "marker_text_after": nearby_marker_text(markdown_lines, line_number - 1, 1),
                    }
                )

    return visuals


def normalize_anchor(value: str) -> str:
    return " ".join(value.casefold().split())


def unique_anchor_line_index(lines: list[str], anchor: str | None) -> int | None:
    if not anchor:
        return None
    normalized_anchor = normalize_anchor(anchor)
    if not normalized_anchor:
        return None
    matches = [
        index for index, line in enumerate(lines) if normalize_anchor(line) == normalized_anchor
    ]
    return matches[0] if len(matches) == 1 else None


def insert_markdown_image(lines: list[str], position: int, image_embed: str) -> list[str]:
    insertion = [image_embed]
    if position > 0 and lines[position - 1].strip():
        insertion.insert(0, "")
    if position < len(lines) and lines[position].strip():
        insertion.append("")
    return lines[:position] + insertion + lines[position:]


def place_visual_by_marker_order(page_text: str, visual: dict, image_embed: str) -> tuple[str, bool]:
    lines = page_text.splitlines()

    following_index = unique_anchor_line_index(lines, visual.get("marker_text_after"))
    if following_index is not None:
        return "\n".join(insert_markdown_image(lines, following_index, image_embed)), True

    previous_index = unique_anchor_line_index(lines, visual.get("marker_text_before"))
    if previous_index is not None:
        return "\n".join(insert_markdown_image(lines, previous_index + 1, image_embed)), True

    return page_text, False


def remove_generated_visual_description_lines(page_text: str) -> str:
    """
    Remove conservative, machine-generated visual description lines.

    Marker visuals are embedded silently. Obvious generated visual labels from OCR
    should not become captions, headings, or task-conversion input.
    """
    kept_lines = []
    for line in page_text.splitlines():
        clean = line.strip()
        if GENERATED_VISUAL_HEADING_PATTERN.match(clean):
            continue
        if GENERATED_VISUAL_DESCRIPTION_PATTERN.match(clean):
            continue
        kept_lines.append(line)
    return "\n".join(kept_lines)


def append_extracted_visuals(page_text: str, image_embeds: list[str]) -> str:
    if not image_embeds:
        return page_text
    return page_text.rstrip() + "\n\n" + "\n\n".join(image_embeds)


def _visual_file_referenced(filename: str, text: str) -> bool:
    return (
        f"/extracted_visuals/{filename}]]" in text
        or f"![[{filename}]]" in text
    )


def remove_stale_page_visual_files(
    extracted_visual_dir: Path,
    page_number: int,
    page_transcriptions: list[str],
) -> None:
    """Remove old visual files for a reprocessed page unless referenced by another page."""
    if not extracted_visual_dir.exists():
        return

    referenced_other_pages = "\n".join(
        page_text
        for index, page_text in enumerate(page_transcriptions, start=1)
        if index != page_number
    )
    prefix = f"page-{page_number:03d}-visual-"
    for existing_file in sorted(extracted_visual_dir.iterdir()):
        if not existing_file.is_file() or not existing_file.name.startswith(prefix):
            continue
        if _visual_file_referenced(existing_file.name, referenced_other_pages):
            continue
        existing_file.unlink(missing_ok=True)


def remove_unreferenced_extracted_visual_files(
    extracted_visual_dir: Path,
    page_transcriptions: list[str],
) -> None:
    """Remove extracted visual files that are no longer referenced by any current page."""
    if not extracted_visual_dir.exists():
        return

    referenced_all_pages = "\n".join(page_transcriptions)
    for existing_file in sorted(extracted_visual_dir.iterdir()):
        if not existing_file.is_file():
            continue
        if not (
            existing_file.name.startswith("page-")
            or existing_file.name.startswith("marker-visual-")
        ):
            continue
        if _visual_file_referenced(existing_file.name, referenced_all_pages):
            continue
        existing_file.unlink(missing_ok=True)


def apply_marker_visuals_to_pages(
    page_transcriptions: list[str],
    visuals: list[dict],
    obsidian_image_folder: str,
) -> int:
    fallback_embeds: dict[int, list[str]] = {}
    placed_count = 0

    for visual in visuals:
        assigned_page = visual["assigned_page"]
        if assigned_page is None and len(page_transcriptions) == 1:
            assigned_page = 1
            visual["assigned_page"] = assigned_page

        if assigned_page is None or not 1 <= assigned_page <= len(page_transcriptions):
            log(f"Skipping unassigned Marker visual embed: {visual['copied_filename']}")
            continue

        image_embed = (
            f"![[{obsidian_image_folder}/extracted_visuals/{visual['copied_filename']}]]"
        )
        page_index = assigned_page - 1
        page_transcriptions[page_index] = remove_generated_visual_description_lines(
            page_transcriptions[page_index]
        )
        updated_text, was_placed = place_visual_by_marker_order(
            page_transcriptions[page_index],
            visual,
            image_embed,
        )
        if was_placed:
            page_transcriptions[page_index] = updated_text
            placed_count += 1
        else:
            fallback_embeds.setdefault(assigned_page, []).append(image_embed)

    for page_number, image_embeds in fallback_embeds.items():
        page_index = page_number - 1
        page_transcriptions[page_index] = append_extracted_visuals(
            page_transcriptions[page_index],
            image_embeds,
        )

    return placed_count


def qwen_detect_page_visuals(page_image_bytes: bytes, page_number: int) -> list[dict]:
    """
    Ask Qwen3-VL via Ollama /api/chat (think=false) to detect genuine drawings/diagrams
    and return normalized 0..1000 bounding boxes. Returns [] cleanly on any error or invalid JSON.
    """
    encoded_image = base64.b64encode(page_image_bytes).decode("ascii")
    request_url = local_ollama_chat_url(LOCAL_OLLAMA_URL)
    payload = {
        "model": LOCAL_OLLAMA_MODEL,
        "messages": [
            {
                "role": "user",
                "content": QWEN3_VL_VISUAL_FALLBACK_PROMPT,
                "images": [encoded_image],
            }
        ],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "num_ctx": LOCAL_OLLAMA_NUM_CTX,
            "num_predict": min(384, LOCAL_OLLAMA_NUM_PREDICT),
            "repeat_penalty": LOCAL_OLLAMA_REPEAT_PENALTY,
        },
    }

    started = time.monotonic()
    try:
        response = requests.post(
            request_url,
            headers={"Connection": "close"},
            json=payload,
            timeout=(10, LOCAL_OLLAMA_PAGE_TIMEOUT_SECONDS),
        )
        elapsed = time.monotonic() - started
        if not response.ok:
            log(
                f"Qwen3-VL visual fallback HTTP {response.status_code} on page {page_number} "
                f"after {elapsed:.1f}s; continuing with text only."
            )
            return []
        response_data = response.json()
        log(
            f"Qwen3-VL visual fallback page {page_number} finished in {elapsed:.1f}s "
            f"(prompt_eval_count={response_data.get('prompt_eval_count')}, "
            f"eval_count={response_data.get('eval_count')})"
        )
    except Exception as exc:
        log(f"Qwen3-VL visual fallback request failed on page {page_number}: {exc}")
        return []

    message_obj = response_data.get("message")
    raw_content = (
        message_obj.get("content")
        if isinstance(message_obj, dict)
        else response_data.get("response")
    )
    if not isinstance(raw_content, str) or not raw_content.strip():
        return []

    cleaned = _strip_json_code_fences(strip_thinking_blocks(raw_content))
    try:
        parsed = json.loads(cleaned)
    except ValueError:
        log(f"Qwen3-VL visual fallback returned invalid JSON on page {page_number}; ignoring.")
        return []

    if not isinstance(parsed, dict):
        return []

    raw_visuals = parsed.get("visuals", [])
    if not isinstance(raw_visuals, list):
        return []

    valid_entries: list[dict] = []
    for entry in raw_visuals:
        if not isinstance(entry, dict):
            continue
        box_2d = entry.get("box_2d")
        if normalize_visual_box_2d(box_2d) is None:
            continue
        valid_entries.append(
            {
                "id": str(entry.get("id", "")).strip(),
                "box_2d": list(box_2d),
                "marker_text_before": str(entry.get("anchor_before", "")).strip() or None,
                "marker_text_after": str(entry.get("anchor_after", "")).strip() or None,
            }
        )
    return valid_entries


def extract_qwen_fallback_visuals_for_pages(
    pdf_file: Path,
    page_numbers: list[int],
    page_transcriptions: list[str],
    extracted_visual_dir: Path,
    obsidian_image_folder: str,
) -> tuple[int, int]:
    """
    Run Qwen3-VL bounding-box detection + Pillow cropping for pages where Marker
    extracted no usable visuals. Never raises on malformed model output.
    """
    if not page_numbers:
        return 0, 0

    try:
        import fitz  # PyMuPDF
        from PIL import Image
    except ImportError as exc:
        log(f"Qwen3-VL visual fallback skipped (missing dependency): {exc}")
        return 0, 0

    render_scale = PAGE_HASH_DPI / 72
    total_saved = 0
    total_placed = 0

    try:
        document = fitz.open(pdf_file)
    except Exception as exc:
        log(f"Qwen3-VL visual fallback could not open PDF {pdf_file}: {exc}")
        return 0, 0

    try:
        extracted_visual_dir.mkdir(parents=True, exist_ok=True)
        target_pages = [
            page_number
            for page_number in sorted(set(page_numbers))
            if 1 <= page_number <= len(document) and page_number <= len(page_transcriptions)
        ]
        for fallback_index, page_number in enumerate(target_pages, start=1):
            progress_event(
                "visual_fallback",
                provider="hybrid_marker_olmocr",
                page=page_number,
                total_pages=len(document),
                changed_index=fallback_index,
                changed_count=len(target_pages),
            )
            page = document[page_number - 1]
            pixmap = render_ollama_page_pixmap(page, dpi=PAGE_HASH_DPI)
            page_image_bytes = pixmap.tobytes("png")
            detected = qwen_detect_page_visuals(page_image_bytes, page_number)
            if not detected:
                continue

            remove_stale_page_visual_files(
                extracted_visual_dir,
                page_number,
                page_transcriptions,
            )
            saved_visuals: list[dict] = []
            visual_index = 0
            with Image.open(io.BytesIO(page_image_bytes)) as raw_image:
                page_image = raw_image.convert("RGB")
                for item in detected:
                    candidate_index = visual_index + 1
                    filename = f"page-{page_number:03d}-visual-{candidate_index:03d}.jpeg"
                    destination = extracted_visual_dir / filename
                    if crop_and_save_visual_box(
                        page_image,
                        item["box_2d"],
                        destination,
                        padding_ratio=QWEN_FALLBACK_PADDING_RATIO,
                        trim_margin_px=CLOUD_VISUAL_TRIM_MARGIN_PX,
                    ):
                        visual_index = candidate_index
                        saved_visuals.append(
                            {
                                "copied_filename": filename,
                                "assigned_page": page_number,
                                "marker_text_before": item.get("marker_text_before"),
                                "marker_text_after": item.get("marker_text_after"),
                            }
                        )

            if saved_visuals:
                total_saved += len(saved_visuals)
                total_placed += apply_marker_visuals_to_pages(
                    page_transcriptions,
                    saved_visuals,
                    obsidian_image_folder,
                )
    finally:
        document.close()

    return total_saved, total_placed


def hybrid_marker_olmocr_pdf(
    pdf_file: Path,
    image_dir: Path,
    obsidian_image_folder: str,
    note_file: Path | None = None,
) -> str:
    log(f"Starting hybrid Marker + Ollama OCR: {pdf_file}")

    reconciliation = None
    preamble = ""
    existing_md_pages: dict[int, str] = {}
    if note_file is not None:
        md_file = OBSIDIAN_NOTE_DIR / f"{safe_name(note_file)}.md"
        preamble, existing_md_pages = parse_existing_markdown_note(md_file)
        page_transcriptions, reconciliation = incremental_ollama_page_transcriptions(
            pdf_file,
            note_file,
            "hybrid_marker_olmocr",
            ocr_settings_fingerprint("hybrid_marker_olmocr"),
            existing_md_pages=existing_md_pages,
        )
    else:
        page_transcriptions = ollama_ocr_pdf_pages(pdf_file)

    changed_set = set(reconciliation["changed_pages"]) if reconciliation is not None else set(
        range(1, len(page_transcriptions) + 1)
    )
    page_transcriptions = [
        convert_html_tables(page_text, forgiving=True)[0]
        if ((index + 1) in changed_set or not existing_md_pages)
        else page_text
        for index, page_text in enumerate(page_transcriptions)
    ]

    extracted_visual_dir = image_dir / "extracted_visuals"
    should_unload_before_marker = (
        LOCAL_OLLAMA_UNLOAD_AFTER_NOTE or HYBRID_MARKER_DISABLE_MULTIPROCESSING
    )

    if reconciliation is not None:
        marker_pages_to_process = reconciliation["changed_pages"]
        if not marker_pages_to_process:
            log("Hybrid Marker page-scope: no changed pages; skipping Marker")
            remove_unreferenced_extracted_visual_files(
                extracted_visual_dir,
                page_transcriptions,
            )
            update_page_cache_markdown(note_file, page_transcriptions)
            return format_ocr_pages(page_transcriptions, preamble=preamble)

        if should_unload_before_marker:
            log("Hybrid Marker + Ollama: unloading Ollama model before starting Marker (keep_alive=0)")
            unload_local_ollama_model_via_api(LOCAL_OLLAMA_MODEL)

        log(f"Hybrid Marker page-scope: processing changed pages {marker_pages_to_process}")
        pages_without_marker_visuals: list[int] = []
        with tempfile.TemporaryDirectory(prefix="supsidian-hybrid-marker-") as temporary_directory:
            total_visuals = 0
            placed_count = 0
            for changed_index, page_number in enumerate(marker_pages_to_process, start=1):
                marker_dir = Path(temporary_directory) / f"marker_page_{page_number:03d}"
                try:
                    progress_event(
                        "marker",
                        provider="hybrid_marker_olmocr",
                        page=page_number,
                        total_pages=len(page_transcriptions),
                        changed_index=changed_index,
                        changed_count=len(marker_pages_to_process),
                    )
                    marker_started = time.monotonic()
                    run_hybrid_marker_for_page(pdf_file, marker_dir, page_number)
                    marker_elapsed = time.monotonic() - marker_started
                    remove_stale_page_visual_files(
                        extracted_visual_dir,
                        page_number,
                        page_transcriptions,
                    )
                    visuals = copy_marker_visuals(
                        marker_dir,
                        extracted_visual_dir,
                        assigned_page_override=page_number,
                    )
                    log(
                        f"Hybrid Marker page {page_number} finished in {marker_elapsed:.1f}s "
                        f"({len(visuals)} visual(s))"
                    )
                    if not visuals:
                        pages_without_marker_visuals.append(page_number)
                    total_visuals += len(visuals)
                    placed_count += apply_marker_visuals_to_pages(
                        page_transcriptions,
                        visuals,
                        obsidian_image_folder,
                    )
                except Exception as exc:
                    pages_without_marker_visuals.append(page_number)
                    log(
                        f"Hybrid Marker page {page_number} failed; continuing without "
                        f"Marker visuals for this page: {exc}"
                    )
                    continue

        if pages_without_marker_visuals and should_run_qwen_visual_fallback():
            log(
                "Hybrid Marker + Qwen3-VL fallback: checking pages without Marker visuals "
                f"{pages_without_marker_visuals}"
            )
            fallback_saved, fallback_placed = extract_qwen_fallback_visuals_for_pages(
                pdf_file,
                pages_without_marker_visuals,
                page_transcriptions,
                extracted_visual_dir,
                obsidian_image_folder,
            )
            total_visuals += fallback_saved
            placed_count += fallback_placed

        for page_number in marker_pages_to_process:
            if 1 <= page_number <= len(page_transcriptions):
                page_transcriptions[page_number - 1] = convert_hash_lines_to_tasks(
                    page_transcriptions[page_number - 1]
                )

        log(
            f"Hybrid Marker + Ollama OCR finished: {pdf_file} "
            f"({total_visuals} visual(s), {placed_count} placed by Marker order)"
        )
        remove_unreferenced_extracted_visual_files(
            extracted_visual_dir,
            page_transcriptions,
        )
        update_page_cache_markdown(note_file, page_transcriptions)
        return format_ocr_pages(page_transcriptions, preamble=preamble)

    if should_unload_before_marker:
        log("Hybrid Marker + Ollama: unloading Ollama model before starting Marker (keep_alive=0)")
        unload_local_ollama_model_via_api(LOCAL_OLLAMA_MODEL)

    marker_visuals: list[dict] = []
    try:
        with tempfile.TemporaryDirectory(prefix="supsidian-hybrid-marker-") as temporary_directory:
            marker_dir = Path(temporary_directory) / "marker_output"
            log("Hybrid Marker + Ollama: running Marker on the full current PDF")
            marker_started = time.monotonic()
            run_hybrid_marker(pdf_file, marker_dir)
            marker_elapsed = time.monotonic() - marker_started

            marker_visuals = copy_marker_visuals(marker_dir, extracted_visual_dir)
            placed_count = apply_marker_visuals_to_pages(
                page_transcriptions,
                marker_visuals,
                obsidian_image_folder,
            )

        log(
            f"Hybrid Marker + Ollama OCR finished in {marker_elapsed:.1f}s: {pdf_file} "
            f"({len(marker_visuals)} visual(s), {placed_count} placed by Marker order)"
        )
    except Exception as exc:
        log(
            "Hybrid Marker failed; continuing with Ollama OCR text only: "
            f"{exc}"
        )
        log(
            f"Hybrid Marker + Ollama OCR finished without Marker visuals: {pdf_file}"
        )

    if should_run_qwen_visual_fallback():
        pages_with_marker = {
            visual["assigned_page"]
            for visual in marker_visuals
            if isinstance(visual.get("assigned_page"), int)
        }
        pages_missing = [
            page_number
            for page_number in range(1, len(page_transcriptions) + 1)
            if page_number not in pages_with_marker
        ]
        if pages_missing:
            extract_qwen_fallback_visuals_for_pages(
                pdf_file,
                pages_missing,
                page_transcriptions,
                extracted_visual_dir,
                obsidian_image_folder,
            )

    return format_ocr_pages(page_transcriptions)


# ------------------------------------------------------------
# CLOUD VLM OCR (GEMINI / CLAUDE / OPENAI) + VISUAL EXTRACTION
# ------------------------------------------------------------

CLOUD_VLM_OCR_PROMPT = """You are performing high-accuracy OCR on a handwritten note page.

Transcribe all handwritten text faithfully into clean Markdown:
- Preserve spelling, grammar, wording, headings, lists, and meaningful line breaks.
- Convert tables into Markdown tables (do not use HTML tables).
- Transcribe clear mathematical notation accurately. Do not invent or summarize content.

Visual / Sketch Extraction:
- Identify ONLY genuine hand-drawn sketches, diagrams, charts, illustrations, or graphical tables.
- Do NOT create visual boxes for normal body text, headings, bullet lists, or single underlines.
- For each genuine visual, insert a placeholder token [[VISUAL_1]], [[VISUAL_2]], etc. on its own line in `markdown` at the exact vertical reading position where the visual appears on the page.
- Return each visual in the `visuals` array with its matching `id` (e.g. "VISUAL_1") and tight bounding box `box_2d` as [ymin, xmin, ymax, xmax] in normalized integer coordinates from 0 to 1000 relative to the page height and width.
- If the page has no drawings or diagrams, return an empty `visuals` array [].

Return ONLY valid JSON matching the schema:
{"markdown": "...", "visuals": [{"id": "VISUAL_1", "box_2d": [ymin, xmin, ymax, xmax]}]}"""

CLOUD_OCR_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string"},
        "visuals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "box_2d": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": ["id", "box_2d"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["markdown", "visuals"],
    "additionalProperties": False,
}

GEMINI_OCR_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "markdown": {"type": "STRING"},
        "visuals": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "box_2d": {
                        "type": "ARRAY",
                        "items": {"type": "INTEGER"},
                    },
                },
                "required": ["id", "box_2d"],
            },
        },
    },
    "required": ["markdown", "visuals"],
}


def build_cloud_vlm_ocr_prompt() -> str:
    effective_custom_instruction = compose_custom_ocr_instruction()
    if effective_custom_instruction:
        return f"{CLOUD_VLM_OCR_PROMPT}\n\nAdditional user instructions:\n{effective_custom_instruction}"
    return CLOUD_VLM_OCR_PROMPT


def resolve_cloud_ocr_model(provider: str) -> str:
    selected = provider.strip().lower()
    if selected not in CLOUD_OCR_DEFAULT_MODELS:
        raise RuntimeError(f"Unsupported cloud OCR provider '{provider}'.")
    configured_model = OCR_MODEL.strip() or str(config.get("ocr_model", "")).strip()
    return configured_model or CLOUD_OCR_DEFAULT_MODELS[selected]


def resolve_cloud_api_key(provider: str) -> str:
    selected = provider.strip().lower()
    if selected not in CLOUD_OCR_API_KEY_CONFIG_KEYS:
        raise RuntimeError(f"Unsupported cloud OCR provider '{provider}'.")

    module_keys = {
        "gemini": GEMINI_API_KEY,
        "claude": ANTHROPIC_API_KEY,
        "openai": OPENAI_API_KEY,
    }
    direct_key = str(module_keys.get(selected, "")).strip()
    if direct_key:
        return direct_key

    config_key = CLOUD_OCR_API_KEY_CONFIG_KEYS[selected]
    configured_key = str(config.get(config_key, "")).strip()
    if configured_key:
        return configured_key

    env_var = CLOUD_OCR_API_KEY_ENV_VARS[selected]
    return os.environ.get(env_var, "").strip()


def require_cloud_api_key(provider: str) -> str:
    selected = provider.strip().lower()
    api_key = resolve_cloud_api_key(selected)
    if not api_key:
        config_key = CLOUD_OCR_API_KEY_CONFIG_KEYS[selected]
        env_var = CLOUD_OCR_API_KEY_ENV_VARS[selected]
        raise RuntimeError(
            f"API key for '{selected}' not found. Set '{config_key}' in {CONFIG_FILE} "
            f"or {env_var} in {ENV_FILE}."
        )
    return api_key


def _strip_json_code_fences(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```\s*$", "", cleaned, count=1)
    return cleaned.strip()


def parse_cloud_vlm_json_response(
    raw_response: object,
    provider: str,
    page_number: int,
) -> tuple[str, list[dict]]:
    if isinstance(raw_response, dict):
        parsed = raw_response
    elif isinstance(raw_response, str):
        cleaned = _strip_json_code_fences(raw_response)
        try:
            parsed = json.loads(cleaned)
        except ValueError as exc:
            raise RuntimeError(
                f"{provider} returned invalid JSON for page {page_number}: {raw_response[:500]}"
            ) from exc
    else:
        raise RuntimeError(
            f"{provider} returned unexpected OCR payload type for page {page_number}: "
            f"{type(raw_response).__name__}"
        )

    if not isinstance(parsed, dict):
        raise RuntimeError(
            f"{provider} OCR JSON for page {page_number} must be an object."
        )

    markdown = parsed.get("markdown")
    if not isinstance(markdown, str):
        raise RuntimeError(
            f"{provider} OCR JSON for page {page_number} is missing a string 'markdown' field."
        )

    raw_visuals = parsed.get("visuals", [])
    visuals: list[dict] = []
    if isinstance(raw_visuals, list):
        for entry in raw_visuals:
            if not isinstance(entry, dict):
                continue
            visual_id = str(entry.get("id", "")).strip()
            box_2d = entry.get("box_2d")
            if not visual_id or not isinstance(box_2d, (list, tuple)):
                continue
            visuals.append({"id": visual_id, "box_2d": list(box_2d)})

    return markdown.strip(), visuals


def normalize_visual_box_2d(box_2d: object) -> tuple[float, float, float, float] | None:
    if not isinstance(box_2d, (list, tuple)) or len(box_2d) != 4:
        return None

    coords: list[float] = []
    for value in box_2d:
        if isinstance(value, bool):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        coords.append(max(0.0, min(1000.0, number)))

    ymin, xmin, ymax, xmax = coords
    if ymin >= ymax or xmin >= xmax:
        return None
    return (ymin, xmin, ymax, xmax)


def crop_and_save_visual_box(
    page_image,
    box_2d: object,
    destination_path: Path,
    padding_ratio: float = CLOUD_VISUAL_PADDING_RATIO,
    trim_margin_px: int = CLOUD_VISUAL_TRIM_MARGIN_PX,
    white_threshold: int = CLOUD_VISUAL_WHITE_THRESHOLD,
) -> bool:
    normalized = normalize_visual_box_2d(box_2d)
    if normalized is None:
        return False

    width, height = page_image.size
    if width <= 0 or height <= 0:
        return False

    ymin, xmin, ymax, xmax = normalized
    raw_left = (xmin / 1000.0) * width
    raw_top = (ymin / 1000.0) * height
    raw_right = (xmax / 1000.0) * width
    raw_bottom = (ymax / 1000.0) * height

    box_width = raw_right - raw_left
    box_height = raw_bottom - raw_top
    if box_width < 4.0 or box_height < 4.0:
        return False

    pad_x = max(2, int(round(box_width * padding_ratio)))
    pad_y = max(2, int(round(box_height * padding_ratio)))

    left = max(0, int(math.floor(raw_left)) - pad_x)
    top = max(0, int(math.floor(raw_top)) - pad_y)
    right = min(width, int(math.ceil(raw_right)) + pad_x)
    bottom = min(height, int(math.ceil(raw_bottom)) + pad_y)

    if right - left < 4 or bottom - top < 4:
        return False

    cropped = page_image.crop((left, top, right, bottom)).convert("RGB")

    # Trim excess pure whitespace while preserving a small residual margin.
    gray = cropped.convert("L")
    non_white_mask = gray.point(lambda pixel: 255 if pixel < white_threshold else 0)
    content_bbox = non_white_mask.getbbox()
    if content_bbox is None:
        return False

    c_left, c_top, c_right, c_bottom = content_bbox
    margin = max(0, int(trim_margin_px))
    trimmed_box = (
        max(0, c_left - margin),
        max(0, c_top - margin),
        min(cropped.width, c_right + margin),
        min(cropped.height, c_bottom + margin),
    )
    if trimmed_box[2] - trimmed_box[0] < 2 or trimmed_box[3] - trimmed_box[1] < 2:
        return False

    final_crop = cropped.crop(trimmed_box)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    final_crop.save(destination_path, format="JPEG", quality=90)
    return True


def apply_cloud_visuals_to_page_markdown(
    page_markdown: str,
    page_image_bytes: bytes,
    visuals: list[dict],
    page_number: int,
    extracted_visual_dir: Path,
    obsidian_image_folder: str,
) -> tuple[str, list[str]]:
    if not visuals:
        return page_markdown, []

    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError(
            "Cloud VLM visual extraction requires Pillow. Install Pillow in the active Supsidian Python environment."
        ) from exc

    extracted_visual_dir.mkdir(parents=True, exist_ok=True)
    saved_filenames: list[str] = []
    fallback_embeds: list[str] = []
    updated_markdown = page_markdown
    visual_index = 0

    with Image.open(io.BytesIO(page_image_bytes)) as raw_image:
        page_image = raw_image.convert("RGB")
        for visual in visuals:
            visual_id = str(visual.get("id", "")).strip()
            placeholder = f"[[{visual_id}]]" if visual_id else ""
            candidate_index = visual_index + 1
            filename = f"page-{page_number:03d}-visual-{candidate_index:03d}.jpeg"
            destination_path = extracted_visual_dir / filename

            saved = crop_and_save_visual_box(
                page_image,
                visual.get("box_2d"),
                destination_path,
            )
            if not saved:
                if placeholder and placeholder in updated_markdown:
                    updated_markdown = updated_markdown.replace(placeholder, "")
                continue

            visual_index = candidate_index
            saved_filenames.append(filename)
            if obsidian_image_folder:
                image_embed = f"![[{obsidian_image_folder}/extracted_visuals/{filename}]]"
            else:
                image_embed = f"![[{filename}]]"

            if placeholder and placeholder in updated_markdown:
                updated_markdown = updated_markdown.replace(placeholder, image_embed)
            else:
                fallback_embeds.append(image_embed)

    if fallback_embeds:
        updated_markdown = append_extracted_visuals(updated_markdown, fallback_embeds)

    updated_markdown = re.sub(r"\n{3,}", "\n\n", updated_markdown).strip()
    return updated_markdown, saved_filenames


def resolve_ocr_reasoning_effort() -> str:
    return normalize_ocr_reasoning_effort(OCR_REASONING_EFFORT)


def _gemini_thinking_config(model: str, effort: str) -> dict | None:
    normalized_model = model.strip().lower()
    normalized_effort = normalize_ocr_reasoning_effort(effort)
    # Gemini 2.0 Flash / legacy 1.5 models do not accept thinkingConfig.
    if normalized_model.startswith(("gemini-1.", "gemini-2.0")):
        return None
    level_map = {
        "minimal": "MINIMAL",
        "low": "LOW",
        "medium": "MEDIUM",
        "high": "HIGH",
    }
    return {"thinkingLevel": level_map[normalized_effort]}


def _openai_reasoning_effort(model: str, effort: str) -> str | None:
    normalized_model = model.strip().lower()
    normalized_effort = normalize_ocr_reasoning_effort(effort)
    # Only pass reasoning_effort to OpenAI reasoning-capable model families.
    if not normalized_model.startswith(("gpt-6", "gpt-5", "o1", "o3", "o4")):
        return None
    # gpt-6.2-sol and gpt-6.2-astra require at least "low" (no "none"/"minimal").
    if normalized_model.startswith("gpt-6.2") and normalized_effort == "minimal":
        return "low"
    return normalized_effort


def call_gemini_ocr_page(
    page_image_bytes: bytes,
    page_number: int,
    model: str,
    api_key: str,
) -> tuple[str, list[dict]]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    encoded_image = base64.b64encode(page_image_bytes).decode("ascii")
    generation_config: dict[str, object] = {
        "temperature": 0.0,
        "responseMimeType": "application/json",
        "responseSchema": GEMINI_OCR_RESPONSE_SCHEMA,
    }
    thinking_config = _gemini_thinking_config(model, resolve_ocr_reasoning_effort())
    if thinking_config is not None:
        generation_config["thinkingConfig"] = thinking_config

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": build_cloud_vlm_ocr_prompt()},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": encoded_image,
                        }
                    },
                ],
            }
        ],
        "generationConfig": generation_config,
    }
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=180)
    except requests.RequestException as exc:
        raise RuntimeError(f"Gemini OCR request failed for page {page_number}: {exc}") from exc

    if (
        response.status_code == 400
        and "thinkingConfig" in generation_config
        and any(token in response.text.lower() for token in ("thinkingconfig", "thinkinglevel", "unknown name"))
    ):
        generation_config.pop("thinkingConfig", None)
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=180)
        except requests.RequestException as exc:
            raise RuntimeError(f"Gemini OCR retry failed for page {page_number}: {exc}") from exc

    if not response.ok:
        raise RuntimeError(
            f"Gemini OCR returned HTTP {response.status_code} for page {page_number}: "
            f"{response.text.strip()[:500]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Gemini OCR returned invalid HTTP JSON for page {page_number}: {response.text[:500]}"
        ) from exc

    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError(f"Gemini OCR returned no candidates for page {page_number}: {data}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [part.get("text", "") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str)]
    raw_text = "".join(text_parts).strip()
    if not raw_text:
        raise RuntimeError(f"Gemini OCR returned empty content for page {page_number}.")

    return parse_cloud_vlm_json_response(raw_text, "gemini", page_number)


def call_claude_ocr_page(
    page_image_bytes: bytes,
    page_number: int,
    model: str,
    api_key: str,
) -> tuple[str, list[dict]]:
    url = "https://api.anthropic.com/v1/messages"
    encoded_image = base64.b64encode(page_image_bytes).decode("ascii")
    effort = resolve_ocr_reasoning_effort()
    payload: dict[str, object] = {
        "model": model,
        "max_tokens": 4096,
        "temperature": 0.0,
        "tools": [
            {
                "name": "submit_page_ocr",
                "description": (
                    "Submit the transcribed Markdown and bounding boxes for extracted "
                    "visuals on this page."
                ),
                "input_schema": CLOUD_OCR_JSON_SCHEMA,
            }
        ],
        "tool_choice": {"type": "tool", "name": "submit_page_ocr"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": encoded_image,
                        },
                    },
                    {
                        "type": "text",
                        "text": build_cloud_vlm_ocr_prompt(),
                    },
                ],
            }
        ],
    }

    if effort in {"medium", "high"}:
        budget_tokens = 2048 if effort == "medium" else 4096
        payload["max_tokens"] = 8192
        payload.pop("temperature", None)
        payload["thinking"] = {"type": "enabled", "budget_tokens": budget_tokens}
        payload["tool_choice"] = {"type": "auto"}

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=180)
    except requests.RequestException as exc:
        raise RuntimeError(f"Claude OCR request failed for page {page_number}: {exc}") from exc

    if (
        response.status_code == 400
        and "thinking" in payload
        and "thinking" in response.text.lower()
    ):
        payload.pop("thinking", None)
        payload["max_tokens"] = 4096
        payload["temperature"] = 0.0
        payload["tool_choice"] = {"type": "tool", "name": "submit_page_ocr"}
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=180)
        except requests.RequestException as exc:
            raise RuntimeError(f"Claude OCR retry failed for page {page_number}: {exc}") from exc

    if not response.ok:
        raise RuntimeError(
            f"Claude OCR returned HTTP {response.status_code} for page {page_number}: "
            f"{response.text.strip()[:500]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"Claude OCR returned invalid HTTP JSON for page {page_number}: {response.text[:500]}"
        ) from exc

    content_blocks = data.get("content")
    if not isinstance(content_blocks, list) or not content_blocks:
        raise RuntimeError(f"Claude OCR returned empty content for page {page_number}: {data}")

    for block in content_blocks:
        if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
            return parse_cloud_vlm_json_response(block["input"], "claude", page_number)

    text_parts = [
        block.get("text", "")
        for block in content_blocks
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
    ]
    raw_text = "".join(text_parts).strip()
    if not raw_text:
        raise RuntimeError(f"Claude OCR returned no tool_use or text payload for page {page_number}.")

    return parse_cloud_vlm_json_response(raw_text, "claude", page_number)


def call_openai_ocr_page(
    page_image_bytes: bytes,
    page_number: int,
    model: str,
    api_key: str,
) -> tuple[str, list[dict]]:
    url = "https://api.openai.com/v1/chat/completions"
    encoded_image = base64.b64encode(page_image_bytes).decode("ascii")
    payload: dict[str, object] = {
        "model": model,
        "temperature": 0.0,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "page_ocr_result",
                "strict": True,
                "schema": CLOUD_OCR_JSON_SCHEMA,
            },
        },
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_cloud_vlm_ocr_prompt()},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{encoded_image}",
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
    }

    reasoning_effort = _openai_reasoning_effort(model, resolve_ocr_reasoning_effort())
    if reasoning_effort is not None:
        payload["reasoning_effort"] = reasoning_effort

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=180)
    except requests.RequestException as exc:
        raise RuntimeError(f"OpenAI OCR request failed for page {page_number}: {exc}") from exc

    if (
        response.status_code == 400
        and "reasoning_effort" in payload
        and any(token in response.text.lower() for token in ("reasoning_effort", "reasoning", "unsupported"))
    ):
        payload.pop("reasoning_effort", None)
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=180)
        except requests.RequestException as exc:
            raise RuntimeError(f"OpenAI OCR retry failed for page {page_number}: {exc}") from exc

    if not response.ok:
        raise RuntimeError(
            f"OpenAI OCR returned HTTP {response.status_code} for page {page_number}: "
            f"{response.text.strip()[:500]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"OpenAI OCR returned invalid HTTP JSON for page {page_number}: {response.text[:500]}"
        ) from exc

    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError(f"OpenAI OCR returned no choices for page {page_number}: {data}")

    message = choices[0].get("message", {})
    content = message.get("content")
    if isinstance(content, list):
        text_parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        raw_text = "".join(text_parts).strip()
    elif isinstance(content, str):
        raw_text = content.strip()
    else:
        raw_text = ""

    if not raw_text:
        raise RuntimeError(f"OpenAI OCR returned empty content for page {page_number}.")

    return parse_cloud_vlm_json_response(raw_text, "openai", page_number)


def is_page_blank_locally(
    page_image_bytes: bytes,
    white_threshold: int = CLOUD_VISUAL_WHITE_THRESHOLD,
    min_ink_ratio: float = 0.0003,
) -> bool:
    """
    Detect blank or near-blank pages locally so empty pages are never uploaded
    to external cloud OCR providers.
    """
    try:
        from PIL import Image
    except ImportError:
        return False

    try:
        with Image.open(io.BytesIO(page_image_bytes)) as raw_image:
            width, height = raw_image.size
            if width <= 0 or height <= 0:
                return True
            gray = raw_image.convert("L")
            non_white_mask = gray.point(lambda pixel: 255 if pixel < white_threshold else 0)
            if non_white_mask.getbbox() is None:
                return True
            non_white_pixels = non_white_mask.histogram()[255]
            return (non_white_pixels / float(width * height)) < min_ink_ratio
    except Exception:
        return False


def prepare_cloud_upload_image_bytes(
    page_image_bytes: bytes,
    max_long_edge_px: int | None = None,
) -> bytes:
    """
    Re-encode a rendered page bitmap into a clean, metadata-free PNG (no EXIF,
    no text chunks, no file paths) and cap the longest edge to minimize uploaded data.
    """
    try:
        from PIL import Image
    except ImportError:
        return page_image_bytes

    cap = CLOUD_OCR_MAX_IMAGE_EDGE_PX if max_long_edge_px is None else int(max_long_edge_px)
    try:
        with Image.open(io.BytesIO(page_image_bytes)) as raw_image:
            rgb = raw_image.convert("RGB")
            width, height = rgb.size
            long_edge = max(width, height)
            if cap > 0 and long_edge > cap:
                scale = cap / float(long_edge)
                new_size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
                rgb = rgb.resize(new_size, Image.Resampling.LANCZOS)
            out = io.BytesIO()
            rgb.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception:
        return page_image_bytes


def call_cloud_vlm_ocr_page(
    provider: str,
    page_image_bytes: bytes,
    page_number: int,
    model: str,
    api_key: str,
) -> tuple[str, list[dict]]:
    selected = provider.strip().lower()
    if selected == "gemini":
        return call_gemini_ocr_page(page_image_bytes, page_number, model, api_key)
    if selected == "claude":
        return call_claude_ocr_page(page_image_bytes, page_number, model, api_key)
    if selected == "openai":
        return call_openai_ocr_page(page_image_bytes, page_number, model, api_key)
    raise RuntimeError(f"Unsupported cloud OCR provider '{provider}'.")


def cloud_vlm_ocr_selected_pdf_pages(
    pdf_file: Path,
    page_numbers: list[int],
    provider: str,
    extracted_visual_dir: Path,
    obsidian_image_folder: str,
    existing_page_transcriptions: list[str] | None = None,
) -> tuple[dict[int, str], dict[int, list[str]]]:
    if not page_numbers:
        return {}, {}

    selected_provider = provider.strip().lower()
    api_key = require_cloud_api_key(selected_provider)
    model = resolve_cloud_ocr_model(selected_provider)

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            f"{selected_provider} OCR requires PyMuPDF. Install it in the active Supsidian Python environment."
        ) from exc

    render_scale = PAGE_HASH_DPI / 72
    selected_pages = sorted(set(page_numbers))
    page_transcriptions: dict[int, str] = {}
    page_assets: dict[int, list[str]] = {}

    try:
        document = fitz.open(pdf_file)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF for {selected_provider} OCR: {pdf_file}: {exc}") from exc

    try:
        if len(document) == 0:
            raise RuntimeError(f"PDF has no pages for {selected_provider} OCR: {pdf_file}")
        invalid_pages = [
            page_number
            for page_number in selected_pages
            if page_number < 1 or page_number > len(document)
        ]
        if invalid_pages:
            raise RuntimeError(
                f"Invalid {selected_provider} OCR page number(s) for {pdf_file}: {invalid_pages}"
            )

        changed_index = 0
        for page_number, page in enumerate(document, start=1):
            if page_number not in selected_pages:
                continue

            changed_index += 1
            progress_event(
                "ocr",
                provider=selected_provider,
                model=model,
                page=page_number,
                total_pages=len(document),
                changed_index=changed_index,
                changed_count=len(selected_pages),
            )
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(render_scale, render_scale),
                alpha=PAGE_HASH_ALPHA,
            )
            page_image_bytes = pixmap.tobytes("png")
            if CLOUD_SKIP_BLANK_PAGES_LOCALLY and is_page_blank_locally(page_image_bytes):
                log(
                    f"Cloud OCR privacy optimization: skipped blank page {page_number} locally "
                    "without external upload"
                )
                remove_stale_page_visual_files(
                    extracted_visual_dir,
                    page_number,
                    existing_page_transcriptions or [],
                )
                page_transcriptions[page_number] = ""
                page_assets[page_number] = []
                continue

            upload_image_bytes = prepare_cloud_upload_image_bytes(page_image_bytes)
            raw_markdown, visuals = call_cloud_vlm_ocr_page(
                selected_provider,
                upload_image_bytes,
                page_number,
                model,
                api_key,
            )
            remove_stale_page_visual_files(
                extracted_visual_dir,
                page_number,
                existing_page_transcriptions or [],
            )
            page_markdown, saved_assets = apply_cloud_visuals_to_page_markdown(
                raw_markdown,
                page_image_bytes,
                visuals,
                page_number,
                extracted_visual_dir,
                obsidian_image_folder,
            )
            page_transcriptions[page_number] = page_markdown
            page_assets[page_number] = saved_assets
    finally:
        document.close()

    return page_transcriptions, page_assets


def cloud_vlm_ocr_pdf(
    pdf_file: Path,
    image_dir: Path,
    obsidian_image_folder: str,
    note_file: Path | None = None,
    provider: str | None = None,
) -> str:
    selected_provider = (provider or OCR_PROVIDER).strip().lower()
    model = resolve_cloud_ocr_model(selected_provider)
    extracted_visual_dir = image_dir / "extracted_visuals"

    log(f"Starting {selected_provider} cloud OCR ({model}): {pdf_file}")

    if note_file is not None:
        current_page_hashes = render_pdf_page_hashes(pdf_file)
        cache = load_page_cache(note_file) or {}
        cached_pages = cache.get("pages", [])
        if not isinstance(cached_pages, list):
            cached_pages = []
        cached_fingerprint = cache.get("ocr_fingerprint")
        cached_fingerprint = cached_fingerprint if isinstance(cached_fingerprint, str) else None

        fingerprint = ocr_settings_fingerprint(selected_provider)
        md_file = OBSIDIAN_NOTE_DIR / f"{safe_name(note_file)}.md"
        preamble, existing_md_pages = parse_existing_markdown_note(md_file)

        if cached_fingerprint and cached_fingerprint != fingerprint:
            log(f"{selected_provider} page cache invalidated due to OCR settings fingerprint change")

        reconciliation = reconcile_page_cache(
            current_page_hashes,
            cached_pages,
            fingerprint,
            cached_fingerprint=cached_fingerprint,
        )
        pages_to_ocr = reconciliation["changed_pages"]

        reused_page_texts = [
            ordered_page["markdown"] or ""
            for ordered_page in reconciliation["ordered_pages"]
        ]
        new_page_markdown, new_page_assets = (
            cloud_vlm_ocr_selected_pdf_pages(
                pdf_file,
                pages_to_ocr,
                selected_provider,
                extracted_visual_dir,
                obsidian_image_folder,
                existing_page_transcriptions=reused_page_texts,
            )
            if pages_to_ocr
            else ({}, {})
        )

        page_transcriptions: list[str] = []
        updated_pages: list[dict] = []
        updated_at = utc_now_iso()

        for ordered_page in reconciliation["ordered_pages"]:
            page_number = ordered_page["page_number"]
            if ordered_page["reused"]:
                same_position_hash = (
                    page_number - 1 < len(cached_pages)
                    and isinstance(cached_pages[page_number - 1], dict)
                    and cached_pages[page_number - 1].get("page_hash") == ordered_page["page_hash"]
                )
                if (
                    existing_md_pages
                    and same_position_hash
                    and page_number in existing_md_pages
                ):
                    markdown = existing_md_pages[page_number]
                else:
                    markdown = ordered_page["markdown"]
                cached_assets = (
                    cached_pages[page_number - 1].get("assets", [])
                    if same_position_hash and isinstance(cached_pages[page_number - 1].get("assets"), list)
                    else []
                )
                assets = list(cached_assets)
            else:
                if page_number not in new_page_markdown:
                    raise RuntimeError(
                        f"{selected_provider} did not return OCR text for changed page {page_number}"
                    )
                markdown = convert_html_tables(new_page_markdown[page_number], forgiving=True)[0]
                markdown = convert_hash_lines_to_tasks(markdown)
                assets = new_page_assets.get(page_number, [])

            page_transcriptions.append(markdown)
            updated_pages.append(
                {
                    "page_number": page_number,
                    "page_hash": ordered_page["page_hash"],
                    "markdown": markdown,
                    "assets": assets,
                    "updated_at": updated_at,
                }
            )

        remove_unreferenced_extracted_visual_files(
            extracted_visual_dir,
            page_transcriptions,
        )

        cache_data = {
            "schema_version": PAGE_CACHE_SCHEMA_VERSION,
            "note_path": str(note_file.expanduser().resolve()),
            "note_cache_id": note_page_cache_id(note_file),
            "ocr_fingerprint": fingerprint,
            "provider": selected_provider,
            "model": model,
            "visual_extraction": CLOUD_VISUAL_EXTRACTION_VERSION,
            "updated_at": updated_at,
            "pages": updated_pages,
            "last_run": {
                "page_count": len(current_page_hashes),
                "changed_pages": pages_to_ocr,
                "reused_pages_count": reconciliation["reused_pages_count"],
                "pages_to_ocr_count": reconciliation["pages_to_ocr_count"],
                "deleted_pages_count": reconciliation["deleted_pages_count"],
            },
        }
        save_page_cache(note_file, cache_data)

        log(
            f"{selected_provider} page cache: "
            f"reused {reconciliation['reused_pages_count']} page(s), "
            f"OCRed {reconciliation['pages_to_ocr_count']} page(s), "
            f"changed pages: {pages_to_ocr}"
        )
        log(f"{selected_provider} cloud OCR finished: {pdf_file}")
        return format_ocr_pages(page_transcriptions, preamble=preamble)

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            f"{selected_provider} OCR requires PyMuPDF. Install it in the active Supsidian Python environment."
        ) from exc

    try:
        document = fitz.open(pdf_file)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF for {selected_provider} OCR: {pdf_file}: {exc}") from exc

    try:
        page_numbers = list(range(1, len(document) + 1))
    finally:
        document.close()

    page_markdown_map, _ = cloud_vlm_ocr_selected_pdf_pages(
        pdf_file,
        page_numbers,
        selected_provider,
        extracted_visual_dir,
        obsidian_image_folder,
    )
    page_transcriptions = [
        convert_html_tables(page_markdown_map[page_number], forgiving=True)[0]
        for page_number in page_numbers
    ]
    remove_unreferenced_extracted_visual_files(
        extracted_visual_dir,
        page_transcriptions,
    )
    log(f"{selected_provider} cloud OCR finished: {pdf_file}")
    return format_ocr_pages(page_transcriptions)


def is_ocr_disabled(provider: str | None = None) -> bool:
    if not bool(config.get("ocr_enabled", True)):
        return True
    selected = (provider if provider is not None else OCR_PROVIDER).strip().lower()
    return selected in DISABLED_OCR_PROVIDERS


def build_no_ocr_markdown(note_file: Path, name: str, pdf_file: Path) -> str:
    attachment_path = (
        f"{ACTIVE_ATTACHMENT_FOLDER}/{name}/{pdf_file.name}"
        if ACTIVE_ATTACHMENT_FOLDER
        else pdf_file.name
    )
    return (
        "---\n"
        f'title: "{name}"\n'
        f'source_note: "{note_file.name}"\n'
        f'pdf_attachment: "{attachment_path}"\n'
        "ocr: false\n"
        "---\n\n"
        f"![[{pdf_file.name}]]\n"
    )


def ocr_pdf(pdf_file: Path, image_dir: Path, obsidian_image_folder: str) -> str:
    provider = OCR_PROVIDER

    if is_ocr_disabled(provider):
        return ""
    if provider == "mistral":
        return mistral_ocr_pdf(pdf_file, image_dir, obsidian_image_folder)
    if provider in CLOUD_VLM_OCR_PROVIDERS:
        return cloud_vlm_ocr_pdf(
            pdf_file,
            image_dir,
            obsidian_image_folder,
            provider=provider,
        )
    if provider == "local_ollama":
        return local_ollama_ocr_pdf(pdf_file, image_dir, obsidian_image_folder)
    if provider == "hybrid_marker_olmocr":
        return hybrid_marker_olmocr_pdf(pdf_file, image_dir, obsidian_image_folder)

    raise RuntimeError(
        f"Unsupported OCR provider '{provider}'. Supported providers: "
        f"{', '.join(SUPPORTED_OCR_PROVIDERS)}."
    )


# ------------------------------------------------------------
# TASK CONVERSION
# ------------------------------------------------------------

def convert_hash_lines_to_tasks(ocr_text: str) -> str:
    """
    Convert handwritten task marker lines directly inside the OCR text.

    Example:
    #call my mum
    # be proud

    becomes:
    - [ ] #task call my mum
    - [ ] #task be proud
    """
    converted_lines = []

    for line in ocr_text.splitlines():
        clean = line.strip()

        if not clean:
            converted_lines.append(line)
            continue

        if clean.startswith("## Page"):
            converted_lines.append(line)
            continue

        if OBSIDIAN_IMAGE_EMBED_PATTERN.fullmatch(clean):
            converted_lines.append(line)
            continue

        if GENERATED_VISUAL_HEADING_PATTERN.match(clean):
            continue

        if GENERATED_VISUAL_DESCRIPTION_PATTERN.match(clean):
            continue

        if re.match(r"^#{2,6}\s+", clean):
            converted_lines.append(line)
            continue

        if clean == "---":
            converted_lines.append(line)
            continue

        if TASK_MARKER and clean.startswith(TASK_MARKER) and should_run_hash_task_conversion():
            task_text = clean[len(TASK_MARKER):].strip()

            if task_text:
                converted_lines.append(f"- [ ] {TASK_TAG} {task_text}")
            else:
                converted_lines.append(line)

            continue

        converted_lines.append(line)

    return "\n".join(converted_lines)


# ------------------------------------------------------------
# PROCESSING
# ------------------------------------------------------------

def _sync_staged_attachments(staged_dir: Path, destination_dir: Path) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)

    for source_path in sorted(staged_dir.rglob("*")):
        relative = source_path.relative_to(staged_dir)
        target_path = destination_dir / relative
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        elif source_path.is_file():
            replace_file_atomically(source_path, target_path)

    staged_extracted_dir = staged_dir / "extracted_visuals"
    dest_extracted_dir = destination_dir / "extracted_visuals"
    if dest_extracted_dir.exists():
        staged_names = (
            {path.name for path in staged_extracted_dir.iterdir() if path.is_file()}
            if staged_extracted_dir.exists()
            else set()
        )
        for existing in list(dest_extracted_dir.iterdir()):
            if existing.is_file() and existing.name not in staged_names:
                existing.unlink(missing_ok=True)


def process_note(note_file: Path) -> None:
    name = safe_name(note_file)

    md_file = OBSIDIAN_NOTE_DIR / f"{name}.md"
    note_attachment_dir = PDF_DIR / name
    obsidian_image_folder = f"{ACTIVE_ATTACHMENT_FOLDER}/{name}"
    pdf_file = note_attachment_dir / f"{name}.pdf"

    log(f"Processing note: {note_file}")
    progress_event("processing", note=str(note_file), note_name=name)

    started_local_ollama_ocr = False

    try:
        with tempfile.TemporaryDirectory(prefix="supsidian-stage-") as stage_root:
            staged_attachment_dir = Path(stage_root) / name
            staged_attachment_dir.mkdir(parents=True, exist_ok=True)
            staged_pdf_file = staged_attachment_dir / f"{name}.pdf"

            existing_visuals_dir = note_attachment_dir / "extracted_visuals"
            if existing_visuals_dir.is_dir():
                shutil.copytree(
                    existing_visuals_dir,
                    staged_attachment_dir / "extracted_visuals",
                    dirs_exist_ok=True,
                )

            progress_event("converting", note=str(note_file), note_name=name)
            convert_note_to_pdf(note_file, staged_pdf_file)

            if is_ocr_disabled():
                _sync_staged_attachments(staged_attachment_dir, note_attachment_dir)
                if md_file.exists() and md_file.read_text(encoding="utf-8", errors="replace").strip():
                    log(f"Preserved existing Markdown note (OCR disabled): {md_file}")
                else:
                    progress_event("writing_markdown", note=str(note_file), note_name=name)
                    final_markdown = build_no_ocr_markdown(note_file, name, pdf_file)
                    write_text_atomically(md_file, final_markdown)
                    log(f"Markdown written: {md_file}")
                progress_event("done", note=str(note_file), note_name=name)
            else:
                progress_event(
                    "ocr_start",
                    note=str(note_file),
                    note_name=name,
                    provider=OCR_PROVIDER,
                )
                if OCR_PROVIDER == "local_ollama":
                    started_local_ollama_ocr = True
                    ocr_markdown = local_ollama_ocr_pdf_incremental(
                        staged_pdf_file,
                        staged_attachment_dir,
                        obsidian_image_folder,
                        note_file,
                    )
                elif OCR_PROVIDER == "hybrid_marker_olmocr":
                    started_local_ollama_ocr = True
                    ocr_markdown = hybrid_marker_olmocr_pdf(
                        staged_pdf_file,
                        staged_attachment_dir,
                        obsidian_image_folder,
                        note_file,
                    )
                elif OCR_PROVIDER in CLOUD_VLM_OCR_PROVIDERS:
                    ocr_markdown = cloud_vlm_ocr_pdf(
                        staged_pdf_file,
                        staged_attachment_dir,
                        obsidian_image_folder,
                        note_file=note_file,
                        provider=OCR_PROVIDER,
                    )
                else:
                    ocr_markdown = ocr_pdf(
                        staged_pdf_file,
                        staged_attachment_dir,
                        obsidian_image_folder,
                    )
                    ocr_markdown = convert_hash_lines_to_tasks(ocr_markdown)

                progress_event("writing_markdown", note=str(note_file), note_name=name)

                final_markdown = f"""{ocr_markdown}

---

## Original PDF

![[{ACTIVE_ATTACHMENT_FOLDER}/{name}/{name}.pdf]]
"""

                _sync_staged_attachments(staged_attachment_dir, note_attachment_dir)
                write_text_atomically(md_file, final_markdown)
                log(f"Markdown written: {md_file}")
                progress_event("done", note=str(note_file), note_name=name)

    finally:
        if started_local_ollama_ocr:
            unload_local_ollama_model_after_note()

    log(f"Done: {md_file}")


def select_note_files_in_source(
    source_dir: Path,
    note_file_filter: str | None = None,
) -> list[Path]:
    all_notes = sorted(source_dir.rglob("*.note"))
    if note_file_filter is None or not str(note_file_filter).strip():
        return all_notes

    target = str(note_file_filter).strip()
    target_folded = target.casefold()
    resolved_target: Path | None = None
    try:
        resolved_target = Path(target).expanduser().resolve()
    except OSError:
        resolved_target = None

    exact_matches: list[Path] = []
    for note_file in all_notes:
        if resolved_target is not None:
            try:
                if note_file.resolve() == resolved_target:
                    exact_matches.append(note_file)
                    continue
            except OSError:
                pass
        try:
            rel_path = str(note_file.relative_to(source_dir))
            if rel_path == target or rel_path.casefold() == target_folded:
                exact_matches.append(note_file)
                continue
        except ValueError:
            pass
    if exact_matches:
        return exact_matches

    return [
        note_file
        for note_file in all_notes
        if note_file.name.casefold() == target_folded
        or note_file.stem.casefold() == target_folded
    ]


def scan_active_notebook_once(note_file_filter: str | None = None) -> int:
    """
    Scan the Supernote source folder once (optionally restricted to a single .note file).
    Returns the number of matching .note files inspected.
    """
    if OPEN_REQUIRES_OBSIDIAN_RUNNING and not is_obsidian_running():
        log("Obsidian is not running. Skipping.")
        return 0

    if not SOURCE_DIR.exists():
        raise SystemExit(f"Source folder not found: {SOURCE_DIR}")

    state = load_state()
    note_files = select_note_files_in_source(SOURCE_DIR, note_file_filter)
    explicit_single_file = bool(note_file_filter and str(note_file_filter).strip())

    for note_file in note_files:
        key = str(note_file)
        current_signature = note_state_signature(note_file)
        md_file = OBSIDIAN_NOTE_DIR / f"{safe_name(note_file)}.md"

        if not explicit_single_file and state.get(key) == current_signature and md_file.exists():
            continue

        log(f"Found new or changed note: {note_file}")

        if not is_file_stable(note_file, FILE_STABILITY_WAIT_SECONDS):
            log(f"Skipped unstable file, will try next run: {note_file}")
            continue

        try:
            stable_signature = note_state_signature(note_file)
            process_note(note_file)
            state[key] = stable_signature
            save_state(state)
        except Exception as exc:
            logging.exception("Error processing %s", note_file)
            log(f"Error processing {note_file}: {exc}")

    return len(note_files)



def select_notebooks(folder_name: str | None = None) -> list[dict]:
    """Return all configured notebooks or filter by a specific folder name/path."""
    if folder_name is None or not str(folder_name).strip():
        return list(NOTEBOOKS)

    target = str(folder_name).strip()
    exact_matches = [
        notebook
        for notebook in NOTEBOOKS
        if str(notebook.get("name", "")).strip() == target
    ]
    if exact_matches:
        return exact_matches

    target_folded = target.casefold()
    folded_matches = [
        notebook
        for notebook in NOTEBOOKS
        if str(notebook.get("name", "")).strip().casefold() == target_folded
        or str(notebook.get("source_dir", "")).strip() == target
        or Path(str(notebook.get("source_dir", "")).strip()).name.casefold() == target_folded
        or str(notebook.get("obsidian_note_folder", "")).strip().casefold() == target_folded
    ]
    if folded_matches:
        return folded_matches

    available = [str(notebook.get("name", "Unnamed notebook")) for notebook in NOTEBOOKS]
    available_text = ", ".join(available) if available else "none configured"
    raise SystemExit(
        f"❌ Configured folder not found: '{target}'. Available folders: {available_text}"
    )


def scan_once(
    folder_name: str | None = None,
    note_file_filter: str | None = None,
) -> None:
    """
    Scan all configured Supernote notebooks (or a single selected folder / file) once.
    """
    selected_notebooks = select_notebooks(folder_name)
    total_matched_files = 0
    for index, notebook in enumerate(selected_notebooks, start=1):
        use_notebook(notebook)
        notebook_name = ACTIVE_NOTEBOOK.get("name", "Unnamed notebook")
        log(f"Scanning notebook: {notebook_name}")
        progress_event(
            "scanning",
            notebook=notebook_name,
            notebook_index=index,
            notebook_count=len(selected_notebooks),
        )
        if note_file_filter and str(note_file_filter).strip():
            matched = scan_active_notebook_once(note_file_filter=note_file_filter)
        else:
            matched = scan_active_notebook_once()
        if isinstance(matched, int):
            total_matched_files += matched

    if note_file_filter and str(note_file_filter).strip() and total_matched_files == 0:
        raise SystemExit(f"❌ Note file not found: '{str(note_file_filter).strip()}'")


# ------------------------------------------------------------
# SETUP
# ------------------------------------------------------------

def ask(prompt: str, default: str = "") -> str:
    """
    Ask the user for input, with an optional default value.
    """
    if default:
        answer = input(f"{prompt}\n[{default}]\n> ").strip()
        return answer or default

    return input(f"{prompt}\n> ").strip()


def ask_bool(prompt: str, default: bool = True) -> bool:
    """
    Ask the user a yes/no question.
    """
    default_text = "Y/n" if default else "y/N"
    answer = input(f"{prompt} [{default_text}]\n> ").strip().lower()

    if not answer:
        return default

    return answer in ("y", "yes", "j", "ja", "true", "1")


def read_raw_config_for_setup() -> dict:
    if not CONFIG_FILE.exists():
        return {}

    try:
        raw_config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    return raw_config if isinstance(raw_config, dict) else {}


def read_existing_config_for_setup() -> dict:
    existing_config = read_raw_config_for_setup()

    config_for_setup = DEFAULT_CONFIG.copy()
    config_for_setup.update(existing_config)
    return config_for_setup


def choose_setup_ocr_provider(config_existed: bool, raw_config: dict) -> str:
    explicit_provider = str(raw_config.get("ocr_provider", "")).strip().lower()

    if explicit_provider in {"local_ollama", "mistral", "hybrid_marker_olmocr"}:
        default_provider = explicit_provider
    elif not config_existed:
        default_provider = "local_ollama"
    else:
        default_provider = "mistral"
        if explicit_provider:
            print(
                f"\nExisting OCR provider '{explicit_provider}' is not selectable in setup. "
                "Choose local_ollama, mistral, or hybrid_marker_olmocr.\n"
            )

    default_choice = {
        "local_ollama": "1",
        "mistral": "2",
        "hybrid_marker_olmocr": "3",
    }[default_provider]

    while True:
        choice = ask(
            "OCR strategy:\n"
            "1. local_ollama — Local Ollama OCR; private/local; requires Ollama, PyMuPDF, and the model\n"
            "2. mistral — Mistral cloud OCR; requires a Mistral API key\n"
            "3. hybrid_marker_olmocr — Experimental: local Ollama OCR + Marker visual extraction\n"
            "Choose OCR strategy (1, 2, or 3)",
            default_choice,
        ).strip().lower()

        if choice in {"1", "local_ollama"}:
            return "local_ollama"
        if choice in {"2", "mistral"}:
            return "mistral"
        if choice in {"3", "hybrid_marker_olmocr", "hybrid"}:
            return "hybrid_marker_olmocr"

        print(
            "Please choose 1 for local_ollama, 2 for mistral, "
            "or 3 for hybrid_marker_olmocr."
        )


def print_local_provider_setup_checks(provider: str, marker_command: str) -> None:
    """Print non-blocking setup checks shared by the local OCR providers."""
    (
        pymupdf_ok,
        pymupdf_detail,
        ollama_ok,
        ollama_detail,
        model_ok,
        model_detail,
    ) = local_ollama_diagnostics()

    if provider == "hybrid_marker_olmocr":
        print("Hybrid Marker + Ollama setup checks (non-blocking):")
    else:
        print("Local Ollama setup checks (non-blocking):")

    print(f"{'✅' if pymupdf_ok else '⚠️'} PyMuPDF — {pymupdf_detail}")
    print(f"{'✅' if ollama_ok else '⚠️'} Ollama — {ollama_detail}")
    print(f"{'✅' if model_ok else '⚠️'} Model '{LOCAL_OLLAMA_MODEL}' — {model_detail}")
    if not model_ok:
        print(f"   Run: ollama pull {LOCAL_OLLAMA_MODEL}")

    if provider == "hybrid_marker_olmocr":
        marker_command_path = shutil.which(marker_command)
        print(f"{'✅' if marker_command_path else '⚠️'} Marker command — {marker_command}")
        print(
            "⚠️ Experimental provider selected. Marker must be installed, and marker_single "
            "must be available to Supsidian’s app/LaunchAgent runtime. If it is not found, "
            "use an absolute hybrid_marker_command path."
        )
        if marker_command_path:
            print(f"   Resolved path: {marker_command_path}")

    print("")


def setup() -> None:
    """
    Interactive setup for user settings.
    Existing files will not be overwritten unless the user confirms.
    """
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("\nSupsidian setup\n")
    print(f"Settings folder:\n{APP_SUPPORT_DIR}\n")

    should_update_config = True
    config_existed = CONFIG_FILE.exists()
    selected_ocr_provider = OCR_PROVIDER
    setup_marker_command = HYBRID_MARKER_COMMAND

    if config_existed:
        should_update_config = ask_bool(
            f"Config already exists:\n{CONFIG_FILE}\n\nDo you want to update it interactively?",
            default=True,
        )

    if should_update_config:
        raw_existing_config = read_raw_config_for_setup()
        existing_config = read_existing_config_for_setup()

        print("\nPlease enter your settings.\n")
        print("Tip: You can drag folders/files from Finder into Terminal to paste their path.\n")

        source_dir = ask(
            "Supernote source folder",
            existing_config.get("source_dir", DEFAULT_CONFIG["source_dir"]),
        )

        vault_dir = ask(
            "Obsidian vault folder",
            existing_config.get("vault_dir", DEFAULT_CONFIG["vault_dir"]),
        )

        obsidian_note_folder = ask(
            "Folder inside your Obsidian vault for Markdown notes",
            existing_config.get("obsidian_note_folder", "Supernote"),
        )

        attachment_folder = ask(
            "Folder inside your Obsidian vault for PDFs/images",
            existing_config.get("attachment_folder", "Attachments/Supernote"),
        )

        state_file = ask(
            "Processed state file name",
            existing_config.get("state_file", "processed_notes.json"),
        )

        check_interval_seconds = ask(
            "Check interval in seconds",
            str(existing_config.get("check_interval_seconds", 60)),
        )

        file_stability_wait_seconds = ask(
            "Wait time in seconds to make sure a .note file is stable",
            str(existing_config.get("file_stability_wait_seconds", 10)),
        )

        supernote_tool_path = ask(
            "Path to supernote-tool",
            existing_config.get(
                "supernote_tool_path",
                DEFAULT_CONFIG["supernote_tool_path"],
            ),
        )

        task_marker = ask(
            "Handwritten task marker",
            existing_config.get("task_marker", "#"),
        )

        task_tag = ask(
            "Obsidian task tag",
            existing_config.get("task_tag", "#task"),
        )

        open_requires_obsidian_running = ask_bool(
            "Should syncing only run when Obsidian is open?",
            bool(existing_config.get("open_requires_obsidian_running", True)),
        )

        ocr_provider = choose_setup_ocr_provider(config_existed, raw_existing_config)
        selected_ocr_provider = ocr_provider
        local_ollama_url = (
            str(existing_config.get("local_ollama_url", DEFAULT_CONFIG["local_ollama_url"])).strip()
            or DEFAULT_CONFIG["local_ollama_url"]
        )
        local_ollama_model = (
            str(existing_config.get("local_ollama_model", DEFAULT_CONFIG["local_ollama_model"])).strip()
            or DEFAULT_CONFIG["local_ollama_model"]
        )
        local_ollama_num_ctx = positive_int_or_default(
            existing_config.get("local_ollama_num_ctx"),
            DEFAULT_CONFIG["local_ollama_num_ctx"],
        )
        hybrid_marker_command = (
            str(existing_config.get("hybrid_marker_command", DEFAULT_CONFIG["hybrid_marker_command"])).strip()
            or DEFAULT_CONFIG["hybrid_marker_command"]
        )
        if ocr_provider == "hybrid_marker_olmocr":
            print(
                "\nHybrid Marker + Ollama is Experimental. Marker must be installed, and an "
                "absolute marker_single path may be needed when the app/LaunchAgent PATH "
                "cannot find it.\n"
            )
            hybrid_marker_command = ask(
                "Path or command for marker_single",
                hybrid_marker_command,
            ).strip() or hybrid_marker_command
        setup_marker_command = hybrid_marker_command

        new_config = {
            "source_dir": source_dir,
            "vault_dir": vault_dir,
            "obsidian_note_folder": obsidian_note_folder,
            "attachment_folder": attachment_folder,
            "state_file": state_file,
            "check_interval_seconds": int(check_interval_seconds),
            "file_stability_wait_seconds": int(file_stability_wait_seconds),
            "supernote_tool_path": supernote_tool_path,
            "task_marker": task_marker,
            "task_tag": task_tag,
            "open_requires_obsidian_running": open_requires_obsidian_running,
            "ocr_provider": ocr_provider,
            "local_ollama_url": local_ollama_url,
            "local_ollama_model": local_ollama_model,
            "local_ollama_num_ctx": local_ollama_num_ctx,
            "hybrid_marker_command": hybrid_marker_command,
        }

        CONFIG_FILE.write_text(
            json.dumps(new_config, indent=2),
            encoding="utf-8",
        )

        print(f"\n✅ Config written:\n{CONFIG_FILE}\n")
    else:
        print("Keeping existing config.\n")

    if selected_ocr_provider == "mistral":
        if ENV_FILE.exists():
            update_env = ask_bool(
                f".env already exists:\n{ENV_FILE}\n\nDo you want to update your Mistral API key?",
                default=False,
            )
        else:
            update_env = True

        if update_env:
            current_key = os.environ.get("MISTRAL_API_KEY", "")
            default_display = "keep existing key" if current_key else "your_mistral_api_key_here"

            api_key = ask(
                "Mistral API key",
                default_display,
            )

            if api_key == "keep existing key":
                print("Keeping existing Mistral API key.")
            else:
                ENV_FILE.write_text(
                    f"MISTRAL_API_KEY={api_key}\n",
                    encoding="utf-8",
                )
                print(f"✅ .env written:\n{ENV_FILE}\n")
        else:
            print("Keeping existing .env file.\n")
    elif selected_ocr_provider in {"local_ollama", "hybrid_marker_olmocr"}:
        print(
            f"Mistral API key is not required for {selected_ocr_provider}. "
            "Leaving .env unchanged.\n"
        )
        print_local_provider_setup_checks(selected_ocr_provider, setup_marker_command)
    else:
        print(
            f"Mistral API key is not required for OCR provider '{selected_ocr_provider}'. "
            "Leaving .env unchanged.\n"
        )

    print("Setup complete.")
    print("")
    print("Next steps:")
    print("1. Run diagnostics:")
    print("   supernote-obsidian-sync --diagnose")
    print("2. Run one sync:")
    print("   supernote-obsidian-sync --once")
    print("")



# ------------------------------------------------------------
# LAUNCHAGENT CONTROL
# ------------------------------------------------------------

def launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def launchctl_service() -> str:
    return f"{launchctl_domain()}/{LAUNCH_AGENT_LABEL}"


def run_launchctl(arguments: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["launchctl", *arguments],
        text=True,
        capture_output=True,
        check=False,
    )


def is_agent_loaded() -> bool:
    result = run_launchctl(["print", launchctl_service()])
    return result.returncode == 0


def launch_agent_plist() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
"http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{LAUNCH_AGENT_LABEL}</string>

    <key>ProgramArguments</key>
    <array>
      <string>{HOMEBREW_CLI_PATH}</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>{LAUNCH_AGENT_OUT_LOG}</string>

    <key>StandardErrorPath</key>
    <string>{LAUNCH_AGENT_ERR_LOG}</string>
  </dict>
</plist>
"""


def install_agent() -> None:
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)

    LAUNCH_AGENT_FILE.write_text(launch_agent_plist(), encoding="utf-8")
    print(f"LaunchAgent written:\n{LAUNCH_AGENT_FILE}\n")

    if is_agent_loaded():
        print("LaunchAgent is already loaded. Restarting it.")
        run_launchctl(["bootout", launchctl_domain(), str(LAUNCH_AGENT_FILE)])

    result = run_launchctl(["bootstrap", launchctl_domain(), str(LAUNCH_AGENT_FILE)])

    if result.returncode != 0:
        print("Could not load LaunchAgent.")
        print(result.stderr.strip() or result.stdout.strip())
        raise SystemExit(result.returncode)

    start_agent()
    print("✅ LaunchAgent installed and started.")


def uninstall_agent() -> None:
    if is_agent_loaded():
        result = run_launchctl(["bootout", launchctl_domain(), str(LAUNCH_AGENT_FILE)])

        if result.returncode != 0:
            print("Could not stop LaunchAgent.")
            print(result.stderr.strip() or result.stdout.strip())
            raise SystemExit(result.returncode)

    if LAUNCH_AGENT_FILE.exists():
        LAUNCH_AGENT_FILE.unlink()
        print(f"Deleted LaunchAgent:\n{LAUNCH_AGENT_FILE}")
    else:
        print("No LaunchAgent file found.")

    print("✅ LaunchAgent uninstalled.")


def start_agent() -> None:
    if not LAUNCH_AGENT_FILE.exists():
        print("LaunchAgent is not installed yet.")
        print("Run:")
        print("  supernote-obsidian-sync --install-agent")
        raise SystemExit(1)

    if not is_agent_loaded():
        result = run_launchctl(["bootstrap", launchctl_domain(), str(LAUNCH_AGENT_FILE)])

        if result.returncode != 0:
            print("Could not load LaunchAgent.")
            print(result.stderr.strip() or result.stdout.strip())
            raise SystemExit(result.returncode)

    result = run_launchctl(["kickstart", "-k", launchctl_service()])

    if result.returncode != 0:
        print("Could not start LaunchAgent.")
        print(result.stderr.strip() or result.stdout.strip())
        raise SystemExit(result.returncode)

    print("✅ LaunchAgent started.")


def stop_agent() -> None:
    if not is_agent_loaded():
        print("LaunchAgent is not running.")
        return

    result = run_launchctl(["bootout", launchctl_domain(), str(LAUNCH_AGENT_FILE)])

    if result.returncode != 0:
        print("Could not stop LaunchAgent.")
        print(result.stderr.strip() or result.stdout.strip())
        raise SystemExit(result.returncode)

    print("✅ LaunchAgent stopped.")


def restart_agent() -> None:
    if is_agent_loaded():
        run_launchctl(["bootout", launchctl_domain(), str(LAUNCH_AGENT_FILE)])

    start_agent()
    print("✅ LaunchAgent restarted.")


def show_agent_status() -> None:
    installed = LAUNCH_AGENT_FILE.exists()
    loaded = is_agent_loaded()

    print("\nSupsidian LaunchAgent status\n")
    print(f"Label:     {LAUNCH_AGENT_LABEL}")
    print(f"Plist:     {LAUNCH_AGENT_FILE}")
    print(f"Installed: {'yes' if installed else 'no'}")
    print(f"Loaded:    {'yes' if loaded else 'no'}")
    print(f"Out log:   {LAUNCH_AGENT_OUT_LOG}")
    print(f"Err log:   {LAUNCH_AGENT_ERR_LOG}")
    print("")

# ------------------------------------------------------------
# CLI COMMANDS
# ------------------------------------------------------------

def local_ollama_tags_url() -> str:
    parsed = urlsplit(LOCAL_OLLAMA_URL)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid local_ollama_url: {LOCAL_OLLAMA_URL}")
    return urlunsplit((parsed.scheme, parsed.netloc, "/api/tags", "", ""))


def local_ollama_diagnostics() -> tuple[bool, str, bool, str, bool, str]:
    try:
        import fitz  # PyMuPDF  # noqa: F401
        pymupdf_ok = True
        pymupdf_detail = "available"
    except ImportError:
        pymupdf_ok = False
        pymupdf_detail = "missing; install PyMuPDF in the active Supsidian Python environment"

    try:
        tags_url = local_ollama_tags_url()
        response = requests.get(tags_url, timeout=5)
        response.raise_for_status()
        response_data = response.json()
    except (ValueError, requests.RequestException) as exc:
        return (
            pymupdf_ok,
            pymupdf_detail,
            False,
            f"unreachable: {exc}",
            False,
            f"cannot check while Ollama is unreachable; run: ollama pull {LOCAL_OLLAMA_MODEL}",
        )

    if not isinstance(response_data, dict):
        return (
            pymupdf_ok,
            pymupdf_detail,
            False,
            f"invalid response from {tags_url}",
            False,
            f"cannot check while Ollama is unreachable; run: ollama pull {LOCAL_OLLAMA_MODEL}",
        )

    model_names = {
        str(model.get("name") or model.get("model") or "")
        for model in response_data.get("models", [])
        if isinstance(model, dict)
    }
    model_available = LOCAL_OLLAMA_MODEL in model_names
    return (
        pymupdf_ok,
        pymupdf_detail,
        True,
        tags_url,
        model_available,
        "available" if model_available else f"missing; run: ollama pull {LOCAL_OLLAMA_MODEL}",
    )

def diagnose() -> None:
    """
    Check whether the local setup looks correct.

    First-time safe:
    - does not show placeholder paths
    - does not check fake Supernote folders
    - explains missing setup clearly
    """
    print("\nSupsidian diagnostics\n")

    checks = []

    def add_check(name: str, ok: bool, detail: str = "") -> None:
        symbol = "✅" if ok else "❌"
        line = f"{symbol} {name}"
        if detail:
            line += f" — {detail}"
        checks.append((ok, line))

    config_exists = CONFIG_FILE.exists()
    env_exists = ENV_FILE.exists()
    api_key_set = bool(os.environ.get("MISTRAL_API_KEY"))
    provider_supported = OCR_PROVIDER in SUPPORTED_OCR_PROVIDERS or is_ocr_disabled()

    vault_configured = config_exists and not is_placeholder_path(str(VAULT_DIR))
    vault_exists = vault_configured and VAULT_DIR.exists()

    tool_configured = config_exists and not is_placeholder_path(str(SUPERNOTE_TOOL_PATH))
    tool_exists = tool_configured and SUPERNOTE_TOOL_PATH.exists() and SUPERNOTE_TOOL_PATH.is_file()

    add_check(
        "Settings folder exists",
        APP_SUPPORT_DIR.exists(),
        str(APP_SUPPORT_DIR),
    )

    add_check(
        "Config file exists",
        config_exists,
        str(CONFIG_FILE) if config_exists else "missing",
    )

    add_check(
        ".env file exists",
        env_exists,
        str(ENV_FILE) if env_exists else "missing",
    )

    add_check(
        "OCR provider",
        provider_supported,
        OCR_PROVIDER
        if provider_supported
        else f"unsupported; supported providers: {', '.join(SUPPORTED_OCR_PROVIDERS)}",
    )

    if OCR_PROVIDER == "mistral":
        add_check(
            "MISTRAL_API_KEY is set",
            api_key_set,
            f"loaded from {ENV_FILE}" if api_key_set else "missing",
        )
    else:
        add_check(
            "MISTRAL_API_KEY is set",
            True,
            f"not required for OCR provider '{OCR_PROVIDER}'",
        )

    if OCR_PROVIDER in {"local_ollama", "hybrid_marker_olmocr"}:
        (
            pymupdf_ok,
            pymupdf_detail,
            ollama_ok,
            ollama_detail,
            model_ok,
            model_detail,
        ) = local_ollama_diagnostics()
        add_check("PyMuPDF is available", pymupdf_ok, pymupdf_detail)
        add_check("Ollama is reachable", ollama_ok, ollama_detail)
        add_check(
            f"Ollama model '{LOCAL_OLLAMA_MODEL}' is available",
            model_ok,
            model_detail,
        )
        if is_qwen3_vl_thinking_model(LOCAL_OLLAMA_MODEL):
            add_check(
                "Ollama model uses non-thinking -instruct variant",
                False,
                f"'{LOCAL_OLLAMA_MODEL}' can burn all output tokens in thinking mode; "
                "use 'qwen3-vl:8b-instruct' instead",
            )
        if OCR_PROVIDER == "hybrid_marker_olmocr":
            marker_command_path = shutil.which(HYBRID_MARKER_COMMAND)
            add_check(
                "Marker command is configured",
                bool(HYBRID_MARKER_COMMAND),
                HYBRID_MARKER_COMMAND or "missing",
            )
            add_check(
                "Marker command is available",
                marker_command_path is not None,
                str(marker_command_path)
                if marker_command_path
                else (
                    f"'{HYBRID_MARKER_COMMAND}' not found; install Marker and ensure "
                    "marker_single is on PATH"
                ),
            )
    elif OCR_PROVIDER in CLOUD_VLM_OCR_PROVIDERS:
        cloud_api_key_set = bool(resolve_cloud_api_key(OCR_PROVIDER))
        cloud_env_var = CLOUD_OCR_API_KEY_ENV_VARS[OCR_PROVIDER]
        cloud_config_key = CLOUD_OCR_API_KEY_CONFIG_KEYS[OCR_PROVIDER]
        cloud_model = resolve_cloud_ocr_model(OCR_PROVIDER)
        add_check(
            f"{cloud_env_var} is set",
            cloud_api_key_set,
            f"model '{cloud_model}'"
            if cloud_api_key_set
            else f"missing (set '{cloud_config_key}' in {CONFIG_FILE} or {cloud_env_var})",
        )
        try:
            import fitz  # PyMuPDF  # noqa: F401
            add_check("PyMuPDF is available", True, "available")
        except ImportError:
            add_check(
                "PyMuPDF is available",
                False,
                "missing; install PyMuPDF in the active Supsidian Python environment",
            )
        try:
            from PIL import Image  # noqa: F401
            add_check("Pillow is available", True, "available")
        except ImportError:
            add_check(
                "Pillow is available",
                False,
                "missing; install Pillow in the active Supsidian Python environment",
            )
    elif provider_supported and OCR_PROVIDER != "mistral" and not is_ocr_disabled():
        add_check(
            "Selected OCR provider is available",
            False,
            f"'{OCR_PROVIDER}' is not implemented yet",
        )

    add_check(
        "Obsidian vault is configured",
        vault_configured,
        str(VAULT_DIR) if vault_configured else "missing",
    )

    if vault_configured:
        add_check(
            "Obsidian vault exists",
            vault_exists,
            str(VAULT_DIR),
        )

    add_check(
        "supernote-tool is configured",
        tool_configured,
        str(SUPERNOTE_TOOL_PATH) if tool_configured else "missing",
    )

    if tool_configured:
        add_check(
            "supernote-tool exists",
            tool_exists,
            str(SUPERNOTE_TOOL_PATH),
        )

        if ".venv" in str(SUPERNOTE_TOOL_PATH):
            add_check(
                "supernote-tool path is usable but should be cleaned up later",
                True,
                "currently inside a project .venv",
            )

    obsidian_running = is_obsidian_running()

    add_check(
        "Obsidian is running",
        obsidian_running if OPEN_REQUIRES_OBSIDIAN_RUNNING else True,
        "required by current config"
        if OPEN_REQUIRES_OBSIDIAN_RUNNING
        else "not required by current config",
    )

    add_check(
        "At least one Supernote folder is configured",
        bool(NOTEBOOKS),
        f"{len(NOTEBOOKS)} folder(s)",
    )

    print("Global checks:\n")
    print("\n".join(line for _, line in checks))

    print("\nFolder checks:\n")

    folder_failed_count = 0

    if not NOTEBOOKS:
        print("No Supernote folders configured yet.")
        print("Add a folder in Settings → Folders or during first-time setup.\n")
    else:
        for index, notebook in enumerate(NOTEBOOKS, start=1):
            use_notebook(notebook)
            notebook_name = ACTIVE_NOTEBOOK.get("name", f"Folder {index}")

            print(f"{index}. {notebook_name}")

            source_ok = SOURCE_DIR.exists()

            try:
                OBSIDIAN_NOTE_DIR.mkdir(parents=True, exist_ok=True)
                note_folder_ok = OBSIDIAN_NOTE_DIR.exists()
            except Exception:
                note_folder_ok = False

            try:
                PDF_DIR.mkdir(parents=True, exist_ok=True)
                attachment_folder_ok = PDF_DIR.exists()
            except Exception:
                attachment_folder_ok = False

            state_parent_ok = STATE_FILE.parent.exists()

            if not state_parent_ok:
                try:
                    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    state_parent_ok = STATE_FILE.parent.exists()
                except Exception:
                    state_parent_ok = False

            folder_checks = [
                source_ok,
                note_folder_ok,
                attachment_folder_ok,
                state_parent_ok,
            ]

            folder_failed_count += sum(1 for ok in folder_checks if not ok)

            print(f"   {'✅' if source_ok else '❌'} Supernote folder:   {SOURCE_DIR}")
            print(f"   {'✅' if note_folder_ok else '❌'} Obsidian folder:    {OBSIDIAN_NOTE_DIR}")
            print(f"   {'✅' if attachment_folder_ok else '❌'} Attachment folder:  {PDF_DIR}")
            print(f"   {'✅' if state_parent_ok else '❌'} State file:         {STATE_FILE}")
            print("")

    failed_global = [line for ok, line in checks if not ok]

    print("Result:")
    if failed_global or folder_failed_count:
        print(f"❌ {len(failed_global) + folder_failed_count} check(s) failed.")
        print("Fix the failed items above before syncing.")
    else:
        print("✅ All checks passed.")

    print("")

def show_status() -> None:
    """
    Show a short machine- and human-readable status summary.
    Useful for the menu-bar app.
    """
    print("\nSupsidian status\n")

    print(f"Settings folder: {APP_SUPPORT_DIR}")
    print(f"Config file:     {CONFIG_FILE}")
    print(f"Env file:        {ENV_FILE}")
    print(f"Log file:        {LOG_FILE}")
    print("")

    print(f"Obsidian vault:  {VAULT_DIR}")
    print(f"Check interval:  {CHECK_INTERVAL_SECONDS} seconds")
    print(f"Obsidian running: {'yes' if is_obsidian_running() else 'no'}")
    print(f"OCR provider:     {OCR_PROVIDER}")
    if OCR_PROVIDER == "mistral":
        print(f"Mistral API key:  {'yes' if os.environ.get('MISTRAL_API_KEY') else 'no'}")
    else:
        print("Mistral API key:  not required")
    if OCR_PROVIDER in CLOUD_VLM_OCR_PROVIDERS:
        print(f"Cloud OCR model:  {resolve_cloud_ocr_model(OCR_PROVIDER)}")
        print(f"Cloud API key:    {'yes' if resolve_cloud_api_key(OCR_PROVIDER) else 'no'}")
    if OCR_PROVIDER in {"local_ollama", "hybrid_marker_olmocr"}:
        print(f"Ollama URL:       {LOCAL_OLLAMA_URL}")
        print(f"Ollama model:     {LOCAL_OLLAMA_MODEL}")
        print(f"Ollama num_ctx:   {LOCAL_OLLAMA_NUM_CTX}")
    if OCR_PROVIDER == "hybrid_marker_olmocr":
        marker_command_path = shutil.which(HYBRID_MARKER_COMMAND)
        print(f"Marker command:   {HYBRID_MARKER_COMMAND}")
        print(f"Marker path:      {marker_command_path or 'not found'}")
    print(f"supernote-tool:   {SUPERNOTE_TOOL_PATH}")
    print("")

    print("Configured notebook mappings:")
    print("")

    for index, notebook in enumerate(NOTEBOOKS, start=1):
        use_notebook(notebook)

        print(f"{index}. {ACTIVE_NOTEBOOK.get('name', 'Unnamed notebook')}")
        print(f"   Supernote folder:   {SOURCE_DIR}")
        print(f"   Obsidian folder:    {OBSIDIAN_NOTE_DIR}")
        print(f"   Attachment folder:  {PDF_DIR}")
        print(f"   State file:         {STATE_FILE}")
        print("")


def open_settings() -> None:
    """
    Open the macOS Application Support settings folder in Finder.
    """
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(["open", str(APP_SUPPORT_DIR)], check=False)
    print(f"Opened settings folder:\n{APP_SUPPORT_DIR}")


def open_log() -> None:
    """
    Open the log file in the default macOS app.
    If the log file does not exist yet, create an empty one.
    """
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    subprocess.run(["open", str(LOG_FILE)], check=False)
    print(f"Opened log file:\n{LOG_FILE}")


def reset_state() -> None:
    """
    Delete the processed state file.
    This makes the next sync treat notes as unprocessed again.
    """
    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"Deleted state file:\n{STATE_FILE}")
        print("")
        print("Next sync will re-check notes.")
    else:
        print("No state file found.")
        print(f"Expected location:\n{STATE_FILE}")

    print("")


def watch_loop() -> None:
    """
    Keep scanning every CHECK_INTERVAL_SECONDS.
    """
    log("Supsidian started")
    log(f"Watching source folder: {SOURCE_DIR}")
    log(f"Obsidian vault: {VAULT_DIR}")
    log(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    log(f"Log file: {LOG_FILE}")

    while True:
        scan_once()
        time.sleep(CHECK_INTERVAL_SECONDS)



def _sync_output_snapshot(notebooks: list[dict] | None = None) -> dict:
    """
    Take a lightweight snapshot of state files and generated Markdown files.
    Used to tell the user whether Sync Now actually changed anything.
    """
    snapshot = {
        "states": {},
        "markdown_files": {},
    }

    target_notebooks = NOTEBOOKS if notebooks is None else notebooks

    for index, notebook in enumerate(target_notebooks, start=1):
        use_notebook(notebook)
        name = ACTIVE_NOTEBOOK.get("name", f"Folder {index}")

        if STATE_FILE.exists():
            try:
                snapshot["states"][name] = STATE_FILE.read_text(encoding="utf-8")
            except Exception:
                snapshot["states"][name] = "<unreadable>"
        else:
            snapshot["states"][name] = None

        files = {}

        if OBSIDIAN_NOTE_DIR.exists():
            for file in OBSIDIAN_NOTE_DIR.glob("*.md"):
                try:
                    stat = file.stat()
                    files[str(file)] = {
                        "mtime_ns": stat.st_mtime_ns,
                        "size": stat.st_size,
                    }
                except Exception:
                    files[str(file)] = "<unreadable>"

        snapshot["markdown_files"][name] = files

    return snapshot


def sync_now_with_summary(
    folder_name: str | None = None,
    note_file_filter: str | None = None,
) -> None:
    """
    Run a one-time sync and print a user-friendly summary for the GUI window.
    """
    if note_file_filter and note_file_filter.strip():
        file_label = Path(note_file_filter.strip()).name
        if folder_name and folder_name.strip():
            print(f"\nSync File: {folder_name.strip()} / {file_label}\n")
        else:
            print(f"\nSync File: {file_label}\n")
    elif folder_name and folder_name.strip():
        print(f"\nSync Folder: {folder_name.strip()}\n")
    else:
        print("\nSync Now\n")

    if not NOTEBOOKS:
        print("❌ No Supernote folders configured yet.")
        print("Open Settings and add at least one Supernote folder first.\n")
        return

    selected_notebooks = select_notebooks(folder_name)
    before = _sync_output_snapshot(selected_notebooks)

    scan_once(folder_name=folder_name, note_file_filter=note_file_filter)

    after = _sync_output_snapshot(selected_notebooks)

    print("")
    if before != after:
        print("✅ Changes found and synced.")
    else:
        print("✅ No changes found.")

    print("")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supsidian — Supernote to Obsidian sync"
    )

    parser.add_argument(
        "--setup",
        action="store_true",
        help="Create or update user settings files.",
    )

    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Check whether the local setup is configured correctly.",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one sync scan and exit.",
    )

    parser.add_argument(
        "--folder",
        type=str,
        default=None,
        help="Sync only the specified configured Supernote folder.",
    )

    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Sync only the specified .note file (path, relative path, or filename/stem).",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current sync status and important paths.",
    )

    parser.add_argument(
        "--open-settings",
        action="store_true",
        help="Open the settings folder in Finder.",
    )

    parser.add_argument(
        "--open-log",
        action="store_true",
        help="Open the log file.",
    )

    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Delete the processed state file so notes can be re-checked.",
    )

    parser.add_argument(
        "--install-agent",
        action="store_true",
        help="Install and start the macOS LaunchAgent.",
    )

    parser.add_argument(
        "--uninstall-agent",
        action="store_true",
        help="Stop and remove the macOS LaunchAgent.",
    )

    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the macOS LaunchAgent.",
    )

    parser.add_argument(
        "--stop",
        action="store_true",
        help="Stop the macOS LaunchAgent.",
    )

    parser.add_argument(
        "--restart",
        action="store_true",
        help="Restart the macOS LaunchAgent.",
    )

    parser.add_argument(
        "--is-running",
        action="store_true",
        help="Show whether the macOS LaunchAgent is installed and loaded.",
    )

    args = parser.parse_args()

    if args.setup:
        setup()
    elif args.diagnose:
        diagnose()
    elif args.once or args.folder or args.file:
        sync_now_with_summary(folder_name=args.folder, note_file_filter=args.file)
    elif args.status:
        show_status()
    elif args.open_settings:
        open_settings()
    elif args.open_log:
        open_log()
    elif args.reset_state:
        reset_state()
    elif args.install_agent:
        install_agent()
    elif args.uninstall_agent:
        uninstall_agent()
    elif args.start:
        start_agent()
    elif args.stop:
        stop_agent()
    elif args.restart:
        restart_agent()
    elif args.is_running:
        show_agent_status()
    else:
        watch_loop()


if __name__ == "__main__":
    main()
