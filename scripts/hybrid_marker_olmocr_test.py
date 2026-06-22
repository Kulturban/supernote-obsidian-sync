#!/usr/bin/env python3
"""Experimental standalone local OCR prototype; it does not affect the main Supsidian sync."""

import argparse
import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "richardyoung/olmocr2:7b-q8"
OLLAMA_CONTEXT_WINDOW = 8192
RENDER_DPI = 200
SAFE_PROMPT = """You are doing OCR on handwritten school notes.
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

MARKDOWN_PROMPT = """You are doing OCR on handwritten school notes.
Transcribe only what is visibly written. Do not correct, fill in, or summarize content.
Return clean Markdown where helpful: preserve headings, lists, and line breaks; convert clear tables
to Markdown tables, never HTML. Use plain text math when it is clear. If text or math is uncertain,
write [unclear] or [unclear formula] rather than guessing. Return only the transcription."""

RAW_PROMPT = "Transcribe this page exactly. Do not summarize. Return only the transcription."

PROMPTS = {
    "safe": SAFE_PROMPT,
    "markdown": MARKDOWN_PROMPT,
    "raw": RAW_PROMPT,
}

IMAGE_LINK_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
PAGE_HEADING_PATTERN = re.compile(r"^#{1,6}\s+.*?\bpage\s+(\d+)\b", re.IGNORECASE)
PAGE_FILENAME_PATTERN = re.compile(r"(?:^|[-_ ])page[-_ ]?0*(\d+)(?:[-_ ].*)?$", re.IGNORECASE)
SUSPICIOUS_FULL_PAGE_PATTERN = re.compile(
    r"(?:^|[-_ ])(?:full[-_ ]?page|page[-_ ]?render|rendered[-_ ]?page)(?:[-_ ]|$)",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an experimental Marker + olmOCR local OCR test on a PDF."
    )
    parser.add_argument("pdf", help="Path to the input PDF")
    parser.add_argument(
        "--out",
        help="Output folder (default: local_ocr_test_output/<pdf-stem>/)",
    )
    parser.add_argument(
        "--prompt-mode",
        choices=PROMPTS.keys(),
        default="safe",
        help="OCR prompt style (default: safe)",
    )
    parser.add_argument(
        "--absolute-image-links",
        action="store_true",
        help="Use absolute paths for any images embedded in combined.md",
    )
    parser.add_argument(
        "--extract-visuals",
        choices=("auto", "marker", "opencv", "none"),
        default="auto",
        help="Visual extraction method (default: auto)",
    )
    parser.add_argument(
        "--embed-page-images",
        choices=("never", "debug", "always"),
        default="never",
        help="Embed full-page renders in combined.md (default: never)",
    )
    return parser.parse_args()


def render_pages(pdf_path: Path, pages_dir: Path) -> list[Path]:
    print("Rendering pages at approximately 200 dpi...")
    scale = RENDER_DPI / 72
    page_paths: list[Path] = []

    try:
        document = fitz.open(pdf_path)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF '{pdf_path}': {exc}") from exc

    try:
        for index, page in enumerate(document, start=1):
            page_path = pages_dir / f"page-{index:03d}.png"
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pixmap.save(page_path)
            page_paths.append(page_path)
            print(f"  Rendered page {index}/{len(document)}: {page_path.name}")
    finally:
        document.close()

    if not page_paths:
        raise RuntimeError("The PDF has no pages to OCR.")

    return page_paths


def run_marker(pdf_path: Path, marker_dir: Path) -> tuple[bool, str]:
    marker_command = shutil.which("marker_single")

    if not marker_command:
        print("Skipping Marker: marker_single is not available in PATH.")
        (marker_dir / "marker_unavailable.txt").write_text(
            "marker_single was not found in PATH. Marker was skipped.\n",
            encoding="utf-8",
        )
        return False, "Marker was unavailable (marker_single was not found in PATH)."

    print("Running Marker...")
    command = [marker_command, str(pdf_path), "--output_dir", str(marker_dir)]

    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError as exc:
        message = f"Could not start Marker: {exc}"
        (marker_dir / "marker_error.txt").write_text(message + "\n", encoding="utf-8")
        (marker_dir / "marker.log").write_text(message + "\n", encoding="utf-8")
        print(f"Marker failed, continuing: {message}")
        return False, message

    log_text = (
        f"Command: {' '.join(command)}\n"
        f"Exit code: {result.returncode}\n\n"
        "--- stdout ---\n"
        f"{result.stdout}\n"
        "--- stderr ---\n"
        f"{result.stderr}\n"
    )
    (marker_dir / "marker.log").write_text(log_text, encoding="utf-8")

    if result.returncode != 0:
        message = f"Marker exited with status {result.returncode}; see marker_error.txt and marker.log."
        (marker_dir / "marker_error.txt").write_text(
            message + "\n\n" + log_text,
            encoding="utf-8",
        )
        print(f"Marker failed, continuing: {message}")
        return False, message

    print("Marker completed.")
    return True, "Marker was available and completed successfully."


def ocr_page(page_path: Path, prompt: str) -> tuple[str, dict]:
    image_base64 = base64.b64encode(page_path.read_bytes()).decode("ascii")
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "images": [image_base64],
        "prompt": prompt,
        # A rendered 200-dpi page can exceed Ollama's default 4k context.
        "options": {"num_ctx": OLLAMA_CONTEXT_WINDOW},
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=600)
    except requests.ConnectionError as exc:
        raise RuntimeError(
            "Could not connect to Ollama at http://localhost:11434. "
            "Start Ollama, then ensure the model is installed with: "
            f"ollama pull {OLLAMA_MODEL}"
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Ollama request failed for {page_path.name}: {exc}") from exc

    if not response.ok:
        detail = response.text.strip()
        raise RuntimeError(
            f"Ollama returned HTTP {response.status_code} for {page_path.name}: {detail}\n"
            f"Confirm that model '{OLLAMA_MODEL}' is available: ollama pull {OLLAMA_MODEL}. "
            f"This prototype requests a {OLLAMA_CONTEXT_WINDOW}-token context window."
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Ollama returned invalid JSON for {page_path.name}: {response.text}") from exc

    text = data.get("response")
    if not isinstance(text, str):
        raise RuntimeError(
            f"Ollama did not return OCR text for {page_path.name}: {json.dumps(data)}"
        )

    return text.strip(), data


def link_for_markdown(path: Path, output_dir: Path, absolute_links: bool) -> str:
    return str(path) if absolute_links else str(path.relative_to(output_dir))


def is_inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def page_from_filename(path: Path) -> int | None:
    match = PAGE_FILENAME_PATTERN.match(path.stem)
    return int(match.group(1)) if match else None


def copy_marker_visuals(marker_dir: Path, visuals_dir: Path) -> list[dict]:
    """Copy only local image assets explicitly referenced by Marker Markdown."""
    print("Looking for Marker-declared image assets...")
    manifest: list[dict] = []
    copied_sources: dict[Path, dict] = {}
    marker_markdown_files = sorted(marker_dir.rglob("*.md"))

    for markdown_file in marker_markdown_files:
        try:
            markdown_text = markdown_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            markdown_text = markdown_file.read_text(encoding="utf-8", errors="replace")

        current_page: int | None = None
        for line_number, line in enumerate(markdown_text.splitlines(), start=1):
            heading_match = PAGE_HEADING_PATTERN.match(line.strip())
            if heading_match:
                current_page = int(heading_match.group(1))

            for link_match in IMAGE_LINK_PATTERN.finditer(line):
                raw_link = link_match.group(1).strip()
                entry = {
                    "copied_filename": None,
                    "original_marker_path": raw_link,
                    "source_marker_markdown_file": str(markdown_file.relative_to(marker_dir)),
                    "assigned_page": current_page,
                    "reason": "",
                    "status": "rejected",
                }

                if raw_link.startswith(("http://", "https://", "data:", "#")):
                    entry["reason"] = "Rejected non-local image link."
                    manifest.append(entry)
                    continue

                linked_path = (markdown_file.parent / raw_link).resolve()
                if not is_inside(linked_path, marker_dir):
                    entry["reason"] = "Rejected path outside marker_output/."
                    manifest.append(entry)
                    continue
                if not linked_path.is_file():
                    entry["reason"] = "Referenced local file does not exist."
                    manifest.append(entry)
                    continue
                if linked_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
                    entry["reason"] = "Referenced file is not a supported image asset."
                    manifest.append(entry)
                    continue
                if SUSPICIOUS_FULL_PAGE_PATTERN.search(linked_path.stem):
                    entry["reason"] = "Rejected suspicious full-page render filename."
                    manifest.append(entry)
                    continue

                filename_page = page_from_filename(linked_path)
                if filename_page is not None:
                    entry["assigned_page"] = filename_page
                    assignment_reason = "Assigned from image filename page number."
                elif current_page is not None:
                    assignment_reason = "Assigned from Marker Markdown page heading."
                else:
                    assignment_reason = "No reliable page assignment signal."

                if linked_path in copied_sources:
                    prior = copied_sources[linked_path]
                    entry.update(
                        copied_filename=prior["copied_filename"],
                        assigned_page=prior["assigned_page"],
                        reason="Duplicate Marker reference; reused existing copied asset.",
                        status="copied",
                    )
                    manifest.append(entry)
                    continue

                visual_index = sum(item["status"] == "copied" for item in manifest) + 1
                if entry["assigned_page"] is not None:
                    destination_name = (
                        f"page-{entry['assigned_page']:03d}-visual-{visual_index:03d}"
                        f"{linked_path.suffix.lower()}"
                    )
                else:
                    destination_name = f"marker-visual-{visual_index:03d}{linked_path.suffix.lower()}"

                destination = visuals_dir / destination_name
                while destination.exists():
                    visual_index += 1
                    destination = visuals_dir / f"marker-visual-{visual_index:03d}{linked_path.suffix.lower()}"

                shutil.copy2(linked_path, destination)
                entry.update(
                    copied_filename=destination.name,
                    reason=assignment_reason,
                    status="copied",
                )
                copied_sources[linked_path] = entry
                manifest.append(entry)
                print(f"  Copied Marker visual: {destination.name}")

    return manifest


def run_opencv_placeholder(visuals_dir: Path) -> list[dict]:
    """Reserve the explicit OpenCV mode without adding a required dependency yet."""
    try:
        import cv2  # noqa: F401
    except ImportError:
        message = (
            "OpenCV visual extraction was requested, but opencv-python is not installed. "
            "No visual crops were created. Install it with: python3 -m pip install opencv-python"
        )
        print(message)
        (visuals_dir / "opencv_unavailable.txt").write_text(message + "\n", encoding="utf-8")
        return []

    message = (
        "OpenCV is available, but local crop detection is intentionally a placeholder in this "
        "prototype. No visual crops were created."
    )
    print(message)
    (visuals_dir / "opencv_placeholder.txt").write_text(message + "\n", encoding="utf-8")
    return []


def marker_summary(marker_dir: Path, marker_succeeded: bool, marker_message: str) -> list[str]:
    if not marker_succeeded:
        return [f"- {marker_message}"]

    markdown_files = sorted(marker_dir.rglob("*.md"))
    asset_dirs = sorted(
        path for path in marker_dir.rglob("*") if path.is_dir() and path != marker_dir
    )
    lines = ["- Marker was available and completed successfully."]
    lines.append("- Generated Markdown files:")
    lines.extend(
        f"  - `{path.relative_to(marker_dir)}`" for path in markdown_files
    )
    if not markdown_files:
        lines.append("  - None found.")
    lines.append("- Asset/image folders:")
    lines.extend(f"  - `{path.relative_to(marker_dir)}/`" for path in asset_dirs)
    if not asset_dirs:
        lines.append("  - None found.")
    return lines


def write_combined_markdown(
    pdf_path: Path,
    output_dir: Path,
    page_texts: list[str],
    marker_succeeded: bool,
    marker_message: str,
    absolute_image_links: bool,
    embed_page_images: str,
    visual_manifest: list[dict],
) -> Path:
    print("Writing combined Markdown...")
    copied_visuals = [item for item in visual_manifest if item["status"] == "copied"]
    unassigned_visuals = [item for item in copied_visuals if item["assigned_page"] is None]
    visuals_by_page: dict[int, list[dict]] = {}
    for visual in copied_visuals:
        if visual["assigned_page"] is not None:
            visuals_by_page.setdefault(visual["assigned_page"], []).append(visual)

    lines = [
        f"# Hybrid local OCR test: {pdf_path.name}",
        "",
        "## Source",
        "",
        f"- PDF: {pdf_path}",
        "",
        "## Notes",
        "",
        "> Full page images are rendered for OCR/debugging but are not embedded by default. "
        "The final Supsidian workflow should rely on the attached PDF for full-page reference "
        "and only embed extracted visual assets such as drawings or diagrams.",
        "",
        "## Marker result",
        "",
        *marker_summary(output_dir / "marker_output", marker_succeeded, marker_message),
        "",
        "## Extracted visual assets",
        "",
    ]

    if not copied_visuals:
        lines.append("- No extracted visual assets found.")
    else:
        lines.append(f"- {len(copied_visuals)} extracted visual asset(s) copied.")
        for visual in copied_visuals:
            page_label = (
                f"page {visual['assigned_page']}" if visual["assigned_page"] is not None else "unassigned"
            )
            lines.append(f"- `{visual['copied_filename']}` ({page_label})")
        if unassigned_visuals:
            lines.extend(["", "### Unassigned extracted visuals", ""])
            for visual in unassigned_visuals:
                visual_path = output_dir / "extracted_visuals" / visual["copied_filename"]
                lines.append(f"![]({link_for_markdown(visual_path, output_dir, absolute_image_links)})")
                lines.append("")

    for index, text in enumerate(page_texts, start=1):
        page_name = f"page-{index:03d}.png"
        image_path = output_dir / "pages" / page_name
        lines.extend(["", f"## Page {index}", ""])

        if embed_page_images == "always":
            lines.extend([f"![]({link_for_markdown(image_path, output_dir, absolute_image_links)})", ""])

        lines.extend(["### olmOCR transcription", "", text or "[No transcription returned.]", ""])

        if page_visuals := visuals_by_page.get(index):
            lines.extend(["### Extracted visuals", ""])
            for visual in page_visuals:
                visual_path = output_dir / "extracted_visuals" / visual["copied_filename"]
                lines.extend(
                    [f"![]({link_for_markdown(visual_path, output_dir, absolute_image_links)})", ""]
                )

        if embed_page_images == "debug":
            lines.extend(
                [
                    "### Debug page render",
                    "",
                    f"![]({link_for_markdown(image_path, output_dir, absolute_image_links)})",
                    "",
                ]
            )

    combined_path = output_dir / "combined.md"
    combined_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return combined_path


def main() -> int:
    args = parse_args()
    pdf_path = Path(args.pdf).expanduser().resolve()

    if not pdf_path.is_file():
        print(f"Error: invalid PDF path or file does not exist: {pdf_path}", file=sys.stderr)
        return 2
    if pdf_path.suffix.lower() != ".pdf":
        print(f"Error: input must be a PDF file: {pdf_path}", file=sys.stderr)
        return 2
    missing_packages = []
    if fitz is None:
        missing_packages.append("PyMuPDF")
    if requests is None:
        missing_packages.append("requests")
    if missing_packages:
        print(
            "Error: missing required package(s): "
            f"{', '.join(missing_packages)}. Install them with: "
            "python3 -m pip install requests PyMuPDF",
            file=sys.stderr,
        )
        return 2

    output_dir = (
        Path(args.out).expanduser().resolve()
        if args.out
        else (Path.cwd() / "local_ocr_test_output" / pdf_path.stem).resolve()
    )
    pages_dir = output_dir / "pages"
    olmocr_dir = output_dir / "olmocr"
    visuals_dir = output_dir / "extracted_visuals"
    marker_dir = output_dir / "marker_output"

    for directory in (pages_dir, olmocr_dir, visuals_dir, marker_dir):
        directory.mkdir(parents=True, exist_ok=True)

    try:
        page_paths = render_pages(pdf_path, pages_dir)

        marker_succeeded = False
        marker_message = "Marker was not run for the selected visual extraction mode."
        visual_manifest: list[dict] = []

        if args.extract_visuals in {"auto", "marker"}:
            marker_succeeded, marker_message = run_marker(pdf_path, marker_dir)
            if marker_succeeded:
                visual_manifest = copy_marker_visuals(marker_dir, visuals_dir)
                copied_count = sum(item["status"] == "copied" for item in visual_manifest)
                if copied_count == 0:
                    print("Marker completed, but no usable Marker-declared image assets were found.")
                    marker_message = "Marker was available, but produced no usable declared image assets."
        elif args.extract_visuals == "opencv":
            marker_message = "Marker was skipped because OpenCV extraction was selected."
            visual_manifest = run_opencv_placeholder(visuals_dir)
        else:
            marker_message = "Marker was skipped because visual extraction is disabled."
            print("Skipping visual extraction (--extract-visuals none).")

        (visuals_dir / "manifest.json").write_text(
            json.dumps(visual_manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        page_texts: list[str] = []
        for index, page_path in enumerate(page_paths, start=1):
            print(f"Sending page {index}/{len(page_paths)} to Ollama...")
            text, raw_data = ocr_page(page_path, PROMPTS[args.prompt_mode])
            (olmocr_dir / f"page-{index:03d}.txt").write_text(text + "\n", encoding="utf-8")
            (olmocr_dir / f"page-{index:03d}.json").write_text(
                json.dumps(raw_data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            page_texts.append(text)

        combined_path = write_combined_markdown(
            pdf_path,
            output_dir,
            page_texts,
            marker_succeeded,
            marker_message,
            args.absolute_image_links,
            args.embed_page_images,
            visual_manifest,
        )
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    copied_visual_count = sum(item["status"] == "copied" for item in visual_manifest)
    print(f"Done. combined.md: {combined_path}")
    print(f"Saved {len(page_paths)} full-page render(s) in: {pages_dir}")
    print(f"Copied {copied_visual_count} extracted visual asset(s) to: {visuals_dir}")
    print(
        "Page images are not embedded by default. Use --embed-page-images debug or always "
        "to inspect the full-page renders."
    )
    print(
        "If embedded images do not display, make sure combined.md stays in the output folder, "
        "or rerun with --absolute-image-links."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
