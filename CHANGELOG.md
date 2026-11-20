# Changelog

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
