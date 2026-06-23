import argparse
import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
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
    "open_requires_obsidian_running": True,
    "ocr_provider": "mistral",
    "local_ollama_url": "http://localhost:11434/api/generate",
    "local_ollama_model": "richardyoung/olmocr2:7b-q8",
    "local_ollama_num_ctx": 8192,
    "hybrid_marker_command": "marker_single",
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
OCR_PROVIDER = str(config.get("ocr_provider", "mistral")).strip().lower() or "mistral"
LOCAL_OLLAMA_URL = (
    str(config.get("local_ollama_url", "http://localhost:11434/api/generate")).strip()
    or "http://localhost:11434/api/generate"
)
LOCAL_OLLAMA_MODEL = (
    str(config.get("local_ollama_model", "richardyoung/olmocr2:7b-q8")).strip()
    or "richardyoung/olmocr2:7b-q8"
)
LOCAL_OLLAMA_NUM_CTX = positive_int_or_default(config.get("local_ollama_num_ctx"), 8192)
HYBRID_MARKER_COMMAND = (
    str(config.get("hybrid_marker_command", "marker_single")).strip() or "marker_single"
)
SUPPORTED_OCR_PROVIDERS = (
    "mistral",
    "local_ollama",
    "hybrid_marker_olmocr",
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

def is_file_stable(path: Path, wait_seconds: int) -> bool:
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

    if CUSTOM_OCR_INSTRUCTION:
        payload["document_annotation_prompt"] = CUSTOM_OCR_INSTRUCTION
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


def ollama_ocr_pdf_pages(pdf_file: Path) -> list[str]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "local_ollama requires PyMuPDF. Install it in the active Supsidian Python environment."
        ) from exc

    render_scale = 200 / 72
    page_transcriptions = []

    try:
        document = fitz.open(pdf_file)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF for local_ollama OCR: {pdf_file}: {exc}") from exc

    try:
        if len(document) == 0:
            raise RuntimeError(f"PDF has no pages for local_ollama OCR: {pdf_file}")

        with tempfile.TemporaryDirectory(prefix="supsidian-local-ocr-") as temporary_directory:
            temporary_dir = Path(temporary_directory)

            for page_number, page in enumerate(document, start=1):
                page_path = temporary_dir / f"page-{page_number:03d}.png"
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(render_scale, render_scale),
                    alpha=False,
                )
                pixmap.save(page_path)

                payload = {
                    "model": LOCAL_OLLAMA_MODEL,
                    "prompt": LOCAL_OLLAMA_PROMPT,
                    "stream": False,
                    "images": [base64.b64encode(page_path.read_bytes()).decode("ascii")],
                    "options": {"num_ctx": LOCAL_OLLAMA_NUM_CTX},
                }

                try:
                    response = requests.post(LOCAL_OLLAMA_URL, json=payload, timeout=600)
                except requests.ConnectionError as exc:
                    raise RuntimeError(
                        f"Could not connect to Ollama at {LOCAL_OLLAMA_URL}. "
                        "Start Ollama, then ensure the model is installed with: "
                        f"ollama pull {LOCAL_OLLAMA_MODEL}"
                    ) from exc
                except requests.RequestException as exc:
                    raise RuntimeError(
                        f"Ollama request failed for page {page_number}: {exc}"
                    ) from exc

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

                page_markdown = response_data.get("response")
                if not isinstance(page_markdown, str):
                    raise RuntimeError(
                        f"Ollama did not return OCR text for page {page_number}: "
                        f"{json.dumps(response_data)}"
                    )

                page_transcriptions.append(page_markdown.strip())
    finally:
        document.close()

    return page_transcriptions


def format_ocr_pages(page_transcriptions: list[str]) -> str:
    markdown_parts = []

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


HTML_TABLE_PATTERN = re.compile(r"<table\b[^>]*>.*?</table\s*>", re.IGNORECASE | re.DOTALL)
MARKER_IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
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


def run_hybrid_marker(pdf_file: Path, marker_output_dir: Path) -> None:
    marker_command = shutil.which(HYBRID_MARKER_COMMAND)
    if not marker_command:
        raise RuntimeError(
            "hybrid_marker_olmocr requires marker_single. Install Marker and ensure "
            "marker_single is on PATH."
        )

    marker_output_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [marker_command, str(pdf_file), "--output_dir", str(marker_output_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().replace("\n", " ")
        detail = detail[:1000] or "no output"
        raise RuntimeError(f"Marker failed with exit status {result.returncode}: {detail}")


def copy_marker_visuals(marker_dir: Path, extracted_visual_dir: Path) -> list[dict]:
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

                shutil.copy2(source_path, destination)
                copied_sources.add(source_path)
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


def append_extracted_visuals(page_text: str, image_embeds: list[str]) -> str:
    if not image_embeds:
        return page_text
    return page_text.rstrip() + "\n\n### Extracted visuals\n\n" + "\n\n".join(image_embeds)


def hybrid_marker_olmocr_pdf(
    pdf_file: Path,
    image_dir: Path,
    obsidian_image_folder: str,
) -> str:
    log(f"Starting hybrid Marker + Ollama OCR: {pdf_file}")

    with tempfile.TemporaryDirectory(prefix="supsidian-hybrid-marker-") as temporary_directory:
        marker_dir = Path(temporary_directory) / "marker_output"
        run_hybrid_marker(pdf_file, marker_dir)

        page_transcriptions = ollama_ocr_pdf_pages(pdf_file)
        page_transcriptions = [
            convert_html_tables(page_text, forgiving=True)[0]
            for page_text in page_transcriptions
        ]

        extracted_visual_dir = image_dir / "extracted_visuals"
        visuals = copy_marker_visuals(marker_dir, extracted_visual_dir)
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

    log(
        f"Hybrid Marker + Ollama OCR finished: {pdf_file} "
        f"({len(visuals)} visual(s), {placed_count} placed by Marker order)"
    )
    return format_ocr_pages(page_transcriptions)


def ocr_pdf(pdf_file: Path, image_dir: Path, obsidian_image_folder: str) -> str:
    provider = OCR_PROVIDER

    if provider == "mistral":
        return mistral_ocr_pdf(pdf_file, image_dir, obsidian_image_folder)
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

        if clean == "---":
            converted_lines.append(line)
            continue

        if TASK_MARKER and clean.startswith(TASK_MARKER):
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

def process_note(note_file: Path) -> None:
    name = safe_name(note_file)

    OBSIDIAN_NOTE_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    obsidian_note_copy = OBSIDIAN_NOTE_DIR / note_file.name
    md_file = OBSIDIAN_NOTE_DIR / f"{name}.md"

    note_attachment_dir = PDF_DIR / name
    obsidian_image_folder = f"{ACTIVE_ATTACHMENT_FOLDER}/{name}"
    pdf_file = note_attachment_dir / f"{name}.pdf"

    log(f"Processing note: {note_file}")

    shutil.copy2(note_file, obsidian_note_copy)
    log(f"Copied .note temporarily to Obsidian: {obsidian_note_copy}")

    try:
        convert_note_to_pdf(note_file, pdf_file)

        ocr_markdown = ocr_pdf(
            pdf_file,
            note_attachment_dir,
            obsidian_image_folder,
        )

        ocr_markdown = convert_hash_lines_to_tasks(ocr_markdown)

        final_markdown = f"""{ocr_markdown}

---

## Original PDF

![[{ACTIVE_ATTACHMENT_FOLDER}/{name}/{name}.pdf]]
"""

        md_file.write_text(final_markdown, encoding="utf-8")
        log(f"Markdown written: {md_file}")

    finally:
        if obsidian_note_copy.exists():
            obsidian_note_copy.unlink()
            log(f"Deleted copied .note file: {obsidian_note_copy}")

    log(f"Done: {md_file}")


def scan_active_notebook_once() -> None:
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
        except Exception as exc:
            logging.exception("Error processing %s", note_file)
            log(f"Error processing {note_file}: {exc}")



def scan_once() -> None:
    """
    Scan all configured Supernote notebooks once.
    """
    for notebook in NOTEBOOKS:
        use_notebook(notebook)
        log(f"Scanning notebook: {ACTIVE_NOTEBOOK.get('name', 'Unnamed notebook')}")
        scan_active_notebook_once()


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
    provider_supported = OCR_PROVIDER in SUPPORTED_OCR_PROVIDERS

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
    elif provider_supported and OCR_PROVIDER != "mistral":
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



def _sync_output_snapshot() -> dict:
    """
    Take a lightweight snapshot of state files and generated Markdown files.
    Used to tell the user whether Sync Now actually changed anything.
    """
    snapshot = {
        "states": {},
        "markdown_files": {},
    }

    for index, notebook in enumerate(NOTEBOOKS, start=1):
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


def sync_now_with_summary() -> None:
    """
    Run a one-time sync and print a user-friendly summary for the GUI window.
    """
    print("\nSync Now\n")

    if not NOTEBOOKS:
        print("❌ No Supernote folders configured yet.")
        print("Open Settings and add at least one Supernote folder first.\n")
        return

    before = _sync_output_snapshot()

    scan_once()

    after = _sync_output_snapshot()

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
    elif args.once:
        sync_now_with_summary()
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
