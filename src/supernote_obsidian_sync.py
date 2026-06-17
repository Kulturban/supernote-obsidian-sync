import argparse
import base64
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from mistralai import Mistral


# ------------------------------------------------------------
# PROJECT PATHS
# ------------------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parents[1]

APP_SUPPORT_DIR = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Supernote Obsidian Sync"
)

# Backwards-compatible local folder for development.
LOCAL_DIR = PROJECT_DIR / "local"

CONFIG_FILE = APP_SUPPORT_DIR / "config.json"
ENV_FILE = APP_SUPPORT_DIR / ".env"
LOG_FILE = APP_SUPPORT_DIR / "supernote_obsidian_sync.log"

APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def log(message: str):
    print(message)
    logging.info(message)


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
    """
    if not CONFIG_FILE.exists():
        raise SystemExit(
            f"Config file not found: {CONFIG_FILE}\n"
            "Run: supernote-obsidian-sync --setup"
        )

    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


config = load_config()

SOURCE_DIR = expand_path(config["source_dir"])
VAULT_DIR = expand_path(config["vault_dir"])

OBSIDIAN_NOTE_DIR = VAULT_DIR / config["obsidian_note_folder"]
PDF_DIR = VAULT_DIR / config["attachment_folder"]

state_file_config = config.get("state_file", "processed_notes.json")

state_file_path = Path(state_file_config).expanduser()

if state_file_path.is_absolute():
    STATE_FILE = state_file_path
else:
    STATE_FILE = APP_SUPPORT_DIR / state_file_path

CHECK_INTERVAL_SECONDS = int(config.get("check_interval_seconds", 60))
FILE_STABILITY_WAIT_SECONDS = int(config.get("file_stability_wait_seconds", 10))

SUPERNOTE_TOOL_PATH = expand_path(config["supernote_tool_path"])

TASK_MARKER = config.get("task_marker", "#")
TASK_TAG = config.get("task_tag", "#task")

OPEN_REQUIRES_OBSIDIAN_RUNNING = bool(config.get("open_requires_obsidian_running", True))

load_dotenv(ENV_FILE)


# ------------------------------------------------------------
# APP CHECKS
# ------------------------------------------------------------

def is_obsidian_running():
    result = subprocess.run(
        ["pgrep", "-x", "Obsidian"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


# ------------------------------------------------------------
# STATE
# ------------------------------------------------------------

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def is_file_stable(path: Path, wait_seconds: int):
    first_size = path.stat().st_size
    time.sleep(wait_seconds)
    second_size = path.stat().st_size
    return first_size == second_size


def safe_name(note_file: Path) -> str:
    folder_name = note_file.parent.name
    file_name = note_file.stem

    if folder_name == SOURCE_DIR.name:
        name = file_name
    else:
        name = f"{folder_name} - {file_name}"

    name = "".join(c for c in name if c not in r'\/:*?"<>|').strip()
    return name or "Untitled Supernote"


def convert_note_to_pdf(note_file: Path, pdf_file: Path):
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
# MISTRAL OCR
# ------------------------------------------------------------

def mistral_ocr_pdf(pdf_file: Path, image_dir: Path, obsidian_image_folder: str) -> str:
    api_key = os.environ.get("MISTRAL_API_KEY")

    if not api_key:
        raise RuntimeError(
            f"MISTRAL_API_KEY not found. Check your env file: {ENV_FILE}"
        )

    client = Mistral(api_key=api_key)

    image_dir.mkdir(parents=True, exist_ok=True)

    log(f"Starting Mistral OCR: {pdf_file}")

    encoded_pdf = base64.b64encode(pdf_file.read_bytes()).decode("utf-8")

    response = client.ocr.process(
        model="mistral-ocr-latest",
        document={
            "type": "document_url",
            "document_url": f"data:application/pdf;base64,{encoded_pdf}",
        },
        include_image_base64=True,
    )

    markdown_parts = []

    for page in response.pages:
        page_number = page.index + 1
        page_markdown = page.markdown

        # Save Mistral-extracted images into this note's own image folder
        if hasattr(page, "images") and page.images:
            for image in page.images:
                image_id = image.id
                image_base64 = image.image_base64

                # Remove data URL prefix if present
                if "," in image_base64:
                    image_base64 = image_base64.split(",", 1)[1]

                image_bytes = base64.b64decode(image_base64)
                image_filename = f"page-{page_number}-{image_id}.png"
                image_path = image_dir / image_filename
                image_path.write_bytes(image_bytes)

                # Replace Mistral's local image reference with an Obsidian embed
                page_markdown = page_markdown.replace(
                    f"![{image_id}]({image_id})",
                    f"![[{obsidian_image_folder}/{image_filename}]]"
                )
                page_markdown = page_markdown.replace(
                    f"![{image_id}]({image_id}.png)",
                    f"![[{obsidian_image_folder}/{image_filename}]]"
                )
                page_markdown = page_markdown.replace(
                    f"![{image_id}]({image_id}.jpg)",
                    f"![[{obsidian_image_folder}/{image_filename}]]"
                )
                page_markdown = page_markdown.replace(
                    f"![{image_id}]({image_id}.jpeg)",
                    f"![[{obsidian_image_folder}/{image_filename}]]"
                )

        # Do not start the whole note with "---",
        # because Obsidian would interpret that as YAML/frontmatter.
        if page_number == 1:
            markdown_parts.append(f"## Page {page_number}\n\n")
        else:
            markdown_parts.append(f"\n\n---\n\n## Page {page_number}\n\n")

        markdown_parts.append(page_markdown)

    log(f"Mistral OCR finished: {pdf_file}")

    return "".join(markdown_parts).strip() + "\n"


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

    The marker and tag are configurable in local/config.json:
    task_marker = "#"
    task_tag = "#task"
    """

    converted_lines = []

    for line in ocr_text.splitlines():
        clean = line.strip()

        # Keep empty lines
        if not clean:
            converted_lines.append(line)
            continue

        # Keep generated page headings unchanged
        if clean.startswith("## Page"):
            converted_lines.append(line)
            continue

        # Keep horizontal separators unchanged
        if clean == "---":
            converted_lines.append(line)
            continue

        # Convert lines that start with the task marker into tasks
        if clean.startswith(TASK_MARKER):
            task_text = clean.lstrip(TASK_MARKER).strip()

            if task_text:
                converted_lines.append(f"- [ ] {TASK_TAG} {task_text}")
            else:
                converted_lines.append(line)

            continue

        # Keep all other OCR text unchanged
        converted_lines.append(line)

    return "\n".join(converted_lines)


# ------------------------------------------------------------
# PROCESSING
# ------------------------------------------------------------

def process_note(note_file: Path):
    name = safe_name(note_file)

    OBSIDIAN_NOTE_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    obsidian_note_copy = OBSIDIAN_NOTE_DIR / note_file.name
    md_file = OBSIDIAN_NOTE_DIR / f"{name}.md"

    note_attachment_dir = PDF_DIR / name

    # This is the path Obsidian uses inside wiki links.
    obsidian_image_folder = f"{config['attachment_folder']}/{name}"

    pdf_file = note_attachment_dir / f"{name}.pdf"

    log(f"Processing note: {note_file}")

    # Copy the .note file temporarily into the Obsidian vault
    shutil.copy2(note_file, obsidian_note_copy)
    log(f"Copied .note temporarily to Obsidian: {obsidian_note_copy}")

    # Convert the original Supernote .note file to PDF
    convert_note_to_pdf(note_file, pdf_file)

    # Send the PDF to Mistral OCR and get Markdown transcription
    ocr_markdown = mistral_ocr_pdf(pdf_file, note_attachment_dir, obsidian_image_folder)

    # Convert handwritten task marker lines directly into Obsidian tasks
    ocr_markdown = convert_hash_lines_to_tasks(ocr_markdown)

    # Markdown: OCR with inline tasks first, then original PDF
    final_markdown = f"""{ocr_markdown}

---

## Original PDF

![[{config['attachment_folder']}/{name}/{name}.pdf]]
"""

    md_file.write_text(final_markdown, encoding="utf-8")
    log(f"Markdown written: {md_file}")

    # Delete only the copied .note file inside the Obsidian vault.
    # This does NOT delete the original Supernote sync file.
    if obsidian_note_copy.exists():
        obsidian_note_copy.unlink()
        log(f"Deleted copied .note file: {obsidian_note_copy}")

    log(f"Done: {md_file}")


def scan_once():
    """
    Scan the Supernote source folder once.
    """
    if OPEN_REQUIRES_OBSIDIAN_RUNNING and not is_obsidian_running():
        log("Obsidian is not running. Skipping.")
        return

    if not SOURCE_DIR.exists():
        raise SystemExit(f"Source folder not found: {SOURCE_DIR}")

    state = load_state()

    for note_file in SOURCE_DIR.rglob("*.note"):
        stat = note_file.stat()
        key = str(note_file)
        current_signature = f"{stat.st_mtime_ns}:{stat.st_size}"

        if state.get(key) == current_signature:
            continue

        log(f"Found new or changed note: {note_file}")

        if not is_file_stable(note_file, FILE_STABILITY_WAIT_SECONDS):
            log(f"Skipped unstable file, will try next run: {note_file}")
            continue

        try:
            process_note(note_file)
            state[key] = current_signature
            save_state(state)
        except Exception as e:
            logging.exception(f"Error processing {note_file}")
            log(f"Error processing {note_file}: {e}")

def diagnose():
    """
    Check whether the local setup looks correct.
    """
    print("\nSupernote → Obsidian Sync diagnostics\n")

    checks = []

    def add_check(name: str, ok: bool, detail: str = ""):
        symbol = "✅" if ok else "❌"
        line = f"{symbol} {name}"
        if detail:
            line += f" — {detail}"
        checks.append((ok, line))

    add_check(
        "Project folder exists",
        PROJECT_DIR.exists(),
        str(PROJECT_DIR),
    )

    add_check(
        "Local folder exists",
        LOCAL_DIR.exists(),
        str(LOCAL_DIR),
    )

    add_check(
        "Config file exists",
        CONFIG_FILE.exists(),
        str(CONFIG_FILE),
    )

    add_check(
        ".env file exists",
        ENV_FILE.exists(),
        str(ENV_FILE),
    )

    add_check(
        "MISTRAL_API_KEY is set",
        bool(os.environ.get("MISTRAL_API_KEY")),
        "loaded from local/.env" if os.environ.get("MISTRAL_API_KEY") else "missing",
    )

    add_check(
        "Supernote source folder exists",
        SOURCE_DIR.exists(),
        str(SOURCE_DIR),
    )

    add_check(
        "Obsidian vault exists",
        VAULT_DIR.exists(),
        str(VAULT_DIR),
    )

    try:
        OBSIDIAN_NOTE_DIR.mkdir(parents=True, exist_ok=True)
        output_ok = OBSIDIAN_NOTE_DIR.exists()
    except Exception:
        output_ok = False

    add_check(
        "Obsidian output note folder exists or can be created",
        output_ok,
        str(OBSIDIAN_NOTE_DIR),
    )

    try:
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        attachments_ok = PDF_DIR.exists()
    except Exception:
        attachments_ok = False

    add_check(
        "Attachment folder exists or can be created",
        attachments_ok,
        str(PDF_DIR),
    )

    add_check(
        "supernote-tool exists",
        SUPERNOTE_TOOL_PATH.exists(),
        str(SUPERNOTE_TOOL_PATH),
    )

    add_check(
        "Obsidian is running",
        is_obsidian_running(),
        "required by current config" if OPEN_REQUIRES_OBSIDIAN_RUNNING else "not required by current config",
    )

    print("\n".join(line for _, line in checks))

    failed = [line for ok, line in checks if not ok]

    print("\nResult:")
    if failed:
        print(f"❌ {len(failed)} check(s) failed.")
        print("Fix the failed items above before syncing.")
    else:
        print("✅ All checks passed.")

    print("")


def watch_loop():
    """
    Keep scanning every CHECK_INTERVAL_SECONDS.
    """
    log("Supernote → Obsidian Sync started")
    log(f"Project folder: {PROJECT_DIR}")
    log(f"Watching source folder: {SOURCE_DIR}")
    log(f"Obsidian vault: {VAULT_DIR}")
    log(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    log(f"Log file: {LOG_FILE}")

    while True:
        scan_once()
        time.sleep(CHECK_INTERVAL_SECONDS)

def main():
    parser = argparse.ArgumentParser(
        description="Supernote → Obsidian Sync"
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

    args = parser.parse_args()

    if args.diagnose:
        diagnose()
    elif args.once:
        scan_once()
    else:
        watch_loop()


if __name__ == "__main__":
    main()