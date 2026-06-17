import base64
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from mistralai import Mistral


def is_obsidian_running():
    result = subprocess.run(
        ["pgrep", "-x", "Obsidian"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


SOURCE_DIR = Path("/Users/david/Library/Containers/com.ratta.supernote/Data/Library/Application Support/com.ratta.supernote/1196691438668095488/Supernote/Note/Psychomotorik")

VAULT_DIR = Path("/Users/david/Documents/Obsidian Vault")
OBSIDIAN_NOTE_DIR = VAULT_DIR / "Psychomotorik"
PDF_DIR = VAULT_DIR / "Attachments" / "Supernote" / "Psychomotorik"

STATE_FILE = Path.home() / "supernote-automation" / "processed_psychomotorik.json"

load_dotenv(Path.home() / "supernote-automation" / ".env")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_file_stable(path: Path, wait_seconds=10):
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

    subprocess.run(
        [
            "/Users/david/supernote-automation/.venv/bin/supernote-tool",
            "convert",
            "-t",
            "pdf",
            "-a",
            str(note_file),
            str(pdf_file),
        ],
        check=True,
    )


def mistral_ocr_pdf(pdf_file: Path, image_dir: Path, obsidian_image_folder: str) -> str:
    api_key = os.environ["MISTRAL_API_KEY"]
    client = Mistral(api_key=api_key)

    image_dir.mkdir(parents=True, exist_ok=True)

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

        # Important:
        # Do NOT start the whole file with "---",
        # because Obsidian would interpret it as YAML frontmatter.
        if page_number == 1:
            markdown_parts.append(f"## Page {page_number}\n\n")
        else:
            markdown_parts.append(f"\n\n---\n\n## Page {page_number}\n\n")

        markdown_parts.append(page_markdown)

    return "".join(markdown_parts).strip() + "\n"


def convert_hash_lines_to_tasks(ocr_text: str) -> str:
    """
    Convert handwritten # task markers directly inside the OCR text.

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

        # Convert lines that start with # into tasks
        if clean.startswith("#"):
            task_text = clean.lstrip("#").strip()

            if task_text:
                converted_lines.append(f"- [ ] #task {task_text}")
            else:
                converted_lines.append(line)

            continue

        # Keep all other OCR text unchanged
        converted_lines.append(line)

    return "\n".join(converted_lines)


def process_note(note_file: Path):
    name = safe_name(note_file)

    OBSIDIAN_NOTE_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    obsidian_note_copy = OBSIDIAN_NOTE_DIR / note_file.name
    md_file = OBSIDIAN_NOTE_DIR / f"{name}.md"

    note_attachment_dir = PDF_DIR / name
    obsidian_image_folder = f"Attachments/Supernote/Psychomotorik/{name}"
    pdf_file = note_attachment_dir / f"{name}.pdf"

    # Copy the .note file temporarily into the Obsidian vault
    shutil.copy2(note_file, obsidian_note_copy)

    # Convert the original Supernote .note file to PDF
    convert_note_to_pdf(note_file, pdf_file)

   
    # Send the PDF to Mistral OCR and get Markdown transcription
    ocr_markdown = mistral_ocr_pdf(pdf_file, note_attachment_dir, obsidian_image_folder)

    # Convert handwritten # lines directly into Obsidian tasks
    ocr_markdown = convert_hash_lines_to_tasks(ocr_markdown)

    # Markdown: OCR with inline tasks first, then original PDF
    final_markdown = f"""{ocr_markdown}

---

## Original PDF

![[Attachments/Supernote/Psychomotorik/{name}/{name}.pdf]]
"""


    md_file.write_text(final_markdown, encoding="utf-8")

    # Delete only the copied .note file inside the Obsidian vault.
    # This does NOT delete the original Supernote sync file.
    if obsidian_note_copy.exists():
        obsidian_note_copy.unlink()
        print(f"Deleted copied .note file: {obsidian_note_copy}")

    print(f"Done: {md_file}")


def main():
    if not is_obsidian_running():
        print("Obsidian is not running. Skipping.")
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

        print(f"Found new or changed note: {note_file}")

        if not is_file_stable(note_file):
            print(f"Skipped unstable file, will try next run: {note_file}")
            continue

        try:
            process_note(note_file)
            state[key] = current_signature
            save_state(state)
        except Exception as e:
            print(f"Error processing {note_file}: {e}")


if __name__ == "__main__":
    while True:
        main()
        time.sleep(60)