# Changelog

## v0.13.2

- Recommended `qwen3-vl:8b-instruct` (the non-thinking instruct variant) in macOS Settings and added a warning banner with a one-click switch when a non-instruct `qwen3-vl` thinking tag is configured.
- Added an empty-thinking-output guard in `ollama_ocr_selected_pdf_pages()` so pages where Ollama spends all output tokens in thinking mode (`eval_count > 0` / `done_reason=length` / `message.thinking`) abort with a clear error instead of overwriting existing Obsidian notes or caching blank pages.
- Hardened local Ollama requests with `num_predict` (`2048` for OCR, `384` for JSON visual fallback), `repeat_penalty` (`1.08`), `1680 px` max image edge capping, `Connection: close`, and a `(10, 180)` second timeout.
- Added per-page timing and token telemetry (`prompt_eval_count`, `eval_count`, `done_reason`, image size, Marker duration) to the sync log.
- Streamed per-page `visual_fallback` progress events (`95%`–`99%`) so the macOS menu bar indicator visibly advances during the Qwen3-VL visual fallback pass.

## v0.13.1

- Organized the **Synced Supernote Folders** settings section into horizontal folder tabs with an inline **+ New Folder** tab button so each synced folder gets its own tab.

## v0.13.0

- Added Cloud VLM OCR providers (`gemini`, `claude`, `openai`) with bounding-box sketch/diagram detection and local Pillow cropping + whitespace trimming.
- Updated Cloud OCR defaults and presets to November 2026 model generations (`gemini-4-hydrogen`, `claude-sonnet-5-5`, `gpt-6.1-terra`, plus fast/precision/flagship presets).
- Added `ocr_reasoning_effort` (`minimal`, `low`, `medium`, `high`, default `low`) to keep reasoning token usage low during page OCR, with automatic model-aware fallback and cache-fingerprint invalidation.
- Added **Test Connection** and **Load Available Models** buttons in macOS Settings (`0600` restricted `config.json` permissions) for future-proof model discovery.
- Optimized `local_ollama` and `hybrid_marker_olmocr` for `qwen3-vl:8b` on 16 GB Macs (`/api/chat` with `think: false`, sequential `keep_alive: 0` unload before Marker, Marker artifact filtering, and Qwen3-VL visual fallback).
- Preserved unchanged Obsidian Markdown pages in place and removed the automatic `Sync Now` popup window in favor of live menu bar status.

## v0.12.1

- Added a visual progress bar header to the macOS **Sync Now** window and live sync status directly at the top of the menu bar menu.
- Kept the **Sync Now** window floating while a sync is running, disabled duplicate window tabs, and added a **Show Sync Status Window** menu action.
- Added the `--folder` CLI option and a **Sync Folder** submenu in the macOS menu bar app to sync individual Supernote folders.
- Added the **No OCR (PDF Embed Only)** option (`ocr_provider: "none"`) to create companion Markdown notes with YAML frontmatter and `![[<Note>.pdf]]` embeds without overwriting manual edits.
- Improved file stability checks across multiple intervals so freshly synced `.note` files are processed on the first **Sync Now** run.
- Staged PDF conversion and OCR outside the Obsidian vault and wrote outputs atomically so no temporary `.note` or incomplete files appear in Obsidian during OCR.
- Fixed Ollama model pull progress parsing across carriage-return (`\r`) and ANSI updates with a linear progress bar.

## v0.12.0

- Added machine-readable `SUSPIDIAN_PROGRESS:` events to the CLI and live progress streaming in the macOS **Sync Now** output window.
- Added an optional macOS setting to open Supernote Partner and wait for a configurable delay before running **Sync Now**.
- Embedded extracted Hybrid Marker visuals silently without the `### Extracted visuals` heading and filtered obvious generated OCR visual description lines.
- Persisted enriched Hybrid Marker page Markdown back into the page cache so unchanged pages keep their extracted visual embeds on later incremental syncs.
- Cleaned up stale or unreferenced extracted visual files when pages are reprocessed or deleted.
- Preserved Markdown subheadings (`##`–`######`) and Obsidian image embeds (`![[...]]`) during task conversion.

## v0.11.0

- Added a page-level OCR cache based on rendered PDF page hashes.
- Added incremental Local Ollama OCR so unchanged pages can reuse cached Markdown.
- Added incremental Hybrid Marker + Ollama OCR for the Ollama text layer.
- Added Marker low-memory defaults for 16 GB Macs.
- Changed Hybrid Marker + Ollama so Marker runs only on changed pages when cache information is available.
- Skipped Marker entirely when no pages changed.
- Made Marker failures non-fatal; Supsidian now keeps Ollama OCR text even if Marker fails.
- Added optional Ollama model unloading after each processed note to free memory on 16 GB Macs.
