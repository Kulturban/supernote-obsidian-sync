import argparse
import base64
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

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
    "source_dir": "/Users/YOUR_USERNAME/Library/Containers/com.ratta.supernote/Data/Library/Application Support/com.ratta.supernote/YOUR_SUPERNOTE_ID/Supernote/Note/YOUR_NOTEBOOK_OR_FOLDER",
    "vault_dir": "/Users/YOUR_USERNAME/Documents/Obsidian Vault",
    "obsidian_note_folder": "Supernote",
    "attachment_folder": "Attachments/Supernote",
    "state_file": "processed_notes.json",
    "check_interval_seconds": 60,
    "file_stability_wait_seconds": 10,
    "supernote_tool_path": "/Users/YOUR_USERNAME/path/to/supernote-tool",
    "task_marker": "#",
    "task_tag": "#task",
    "open_requires_obsidian_running": True,
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


def normalize_notebooks(raw_config: dict) -> list[dict]:
    """
    Convert old single-folder config and new multi-folder config
    into one internal notebook list.

    Old config:
      source_dir, obsidian_note_folder, attachment_folder, state_file

    New config:
      notebooks: [
        {
          name,
          source_dir,
          obsidian_note_folder,
          attachment_folder,
          state_file
        }
      ]
    """
    configured_notebooks = raw_config.get("notebooks")

    if isinstance(configured_notebooks, list) and configured_notebooks:
        notebooks = configured_notebooks
    else:
        source_dir = raw_config.get("source_dir", DEFAULT_CONFIG["source_dir"])
        fallback_name = Path(source_dir).expanduser().name or "Supernote"

        notebooks = [
            {
                "name": fallback_name,
                "source_dir": source_dir,
                "obsidian_note_folder": raw_config.get(
                    "obsidian_note_folder",
                    DEFAULT_CONFIG["obsidian_note_folder"],
                ),
                "attachment_folder": raw_config.get(
                    "attachment_folder",
                    DEFAULT_CONFIG["attachment_folder"],
                ),
                "state_file": raw_config.get(
                    "state_file",
                    DEFAULT_CONFIG["state_file"],
                ),
            }
        ]

    normalized = []

    for index, notebook in enumerate(notebooks, start=1):
        source_dir = notebook.get("source_dir", "").strip()
        name = notebook.get("name") or Path(source_dir).expanduser().name or f"Notebook {index}"

        obsidian_note_folder = notebook.get("obsidian_note_folder") or name
        attachment_folder = notebook.get("attachment_folder") or f"Attachments/Supernote/{name}"
        state_file = notebook.get("state_file") or f"processed_{slugify(name)}.json"

        normalized.append(
            {
                "name": name,
                "source_dir": source_dir,
                "obsidian_note_folder": obsidian_note_folder,
                "attachment_folder": attachment_folder,
                "state_file": state_file,
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

        ocr_markdown = mistral_ocr_pdf(
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


def read_existing_config_for_setup() -> dict:
    if not CONFIG_FILE.exists():
        return DEFAULT_CONFIG.copy()

    try:
        existing_config = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        existing_config = {}

    config_for_setup = DEFAULT_CONFIG.copy()
    config_for_setup.update(existing_config)
    return config_for_setup


def setup() -> None:
    """
    Interactive setup for user settings.
    Existing files will not be overwritten unless the user confirms.
    """
    APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)

    print("\nSupernote → Obsidian Sync setup\n")
    print(f"Settings folder:\n{APP_SUPPORT_DIR}\n")

    should_update_config = True

    if CONFIG_FILE.exists():
        should_update_config = ask_bool(
            f"Config already exists:\n{CONFIG_FILE}\n\nDo you want to update it interactively?",
            default=True,
        )

    if should_update_config:
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
        }

        CONFIG_FILE.write_text(
            json.dumps(new_config, indent=2),
            encoding="utf-8",
        )

        print(f"\n✅ Config written:\n{CONFIG_FILE}\n")
    else:
        print("Keeping existing config.\n")

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

    print("\nSupernote → Obsidian Sync LaunchAgent status\n")
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

def diagnose() -> None:
    """
    Check whether the local setup looks correct.
    """
    print("\nSupernote → Obsidian Sync diagnostics\n")

    checks = []

    def add_check(name: str, ok: bool, detail: str = "") -> None:
        symbol = "✅" if ok else "❌"
        line = f"{symbol} {name}"
        if detail:
            line += f" — {detail}"
        checks.append((ok, line))

    add_check(
        "Settings folder exists",
        APP_SUPPORT_DIR.exists(),
        str(APP_SUPPORT_DIR),
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
        f"loaded from {ENV_FILE}" if os.environ.get("MISTRAL_API_KEY") else "missing",
    )

    add_check(
        "Obsidian vault exists",
        VAULT_DIR.exists(),
        str(VAULT_DIR),
    )

    add_check(
        "supernote-tool exists",
        SUPERNOTE_TOOL_PATH.exists(),
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
        "At least one notebook is configured",
        bool(NOTEBOOKS),
        f"{len(NOTEBOOKS)} notebook(s)",
    )

    print("Global checks:\n")
    print("\n".join(line for _, line in checks))

    notebook_checks = []

    def add_notebook_check(notebook_name: str, name: str, ok: bool, detail: str = "") -> None:
        symbol = "✅" if ok else "❌"
        line = f"{symbol} {name}"
        if detail:
            line += f" — {detail}"
        notebook_checks.append((ok, notebook_name, line))

    print("\nNotebook checks:\n")

    for index, notebook in enumerate(NOTEBOOKS, start=1):
        use_notebook(notebook)
        notebook_name = ACTIVE_NOTEBOOK.get("name", f"Notebook {index}")

        print(f"{index}. {notebook_name}")

        source_ok = SOURCE_DIR.exists()
        add_notebook_check(
            notebook_name,
            "Supernote source folder exists",
            source_ok,
            str(SOURCE_DIR),
        )

        try:
            OBSIDIAN_NOTE_DIR.mkdir(parents=True, exist_ok=True)
            note_folder_ok = OBSIDIAN_NOTE_DIR.exists()
        except Exception:
            note_folder_ok = False

        add_notebook_check(
            notebook_name,
            "Obsidian output note folder exists or can be created",
            note_folder_ok,
            str(OBSIDIAN_NOTE_DIR),
        )

        try:
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            attachment_folder_ok = PDF_DIR.exists()
        except Exception:
            attachment_folder_ok = False

        add_notebook_check(
            notebook_name,
            "Attachment folder exists or can be created",
            attachment_folder_ok,
            str(PDF_DIR),
        )

        state_parent_ok = STATE_FILE.parent.exists()

        if not state_parent_ok:
            try:
                STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
                state_parent_ok = STATE_FILE.parent.exists()
            except Exception:
                state_parent_ok = False

        add_notebook_check(
            notebook_name,
            "State file folder exists or can be created",
            state_parent_ok,
            str(STATE_FILE),
        )

        print(f"   {'✅' if source_ok else '❌'} Supernote folder:   {SOURCE_DIR}")
        print(f"   {'✅' if note_folder_ok else '❌'} Obsidian folder:    {OBSIDIAN_NOTE_DIR}")
        print(f"   {'✅' if attachment_folder_ok else '❌'} Attachment folder:  {PDF_DIR}")
        print(f"   {'✅' if state_parent_ok else '❌'} State file:         {STATE_FILE}")
        print("")

    failed_global = [line for ok, line in checks if not ok]
    failed_notebooks = [line for ok, _, line in notebook_checks if not ok]

    print("Result:")
    if failed_global or failed_notebooks:
        print(f"❌ {len(failed_global) + len(failed_notebooks)} check(s) failed.")
        print("Fix the failed items above before syncing.")
    else:
        print("✅ All checks passed.")

    print("")

def show_status() -> None:
    """
    Show a short machine- and human-readable status summary.
    Useful for the menu-bar app.
    """
    print("\nSupernote → Obsidian Sync status\n")

    print(f"Settings folder: {APP_SUPPORT_DIR}")
    print(f"Config file:     {CONFIG_FILE}")
    print(f"Env file:        {ENV_FILE}")
    print(f"Log file:        {LOG_FILE}")
    print("")

    print(f"Obsidian vault:  {VAULT_DIR}")
    print(f"Check interval:  {CHECK_INTERVAL_SECONDS} seconds")
    print(f"Obsidian running: {'yes' if is_obsidian_running() else 'no'}")
    print(f"API key set:      {'yes' if os.environ.get('MISTRAL_API_KEY') else 'no'}")
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
    log("Supernote → Obsidian Sync started")
    log(f"Watching source folder: {SOURCE_DIR}")
    log(f"Obsidian vault: {VAULT_DIR}")
    log(f"Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    log(f"Log file: {LOG_FILE}")

    while True:
        scan_once()
        time.sleep(CHECK_INTERVAL_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Supernote → Obsidian Sync"
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
        scan_once()
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
