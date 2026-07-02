# Changelog

## v0.11.0

- Added a page-level OCR cache based on rendered PDF page hashes.
- Added incremental Local Ollama OCR so unchanged pages can reuse cached Markdown.
- Added incremental Hybrid Marker + Ollama OCR for the Ollama text layer.
- Added Marker low-memory defaults for 16 GB Macs.
- Changed Hybrid Marker + Ollama so Marker runs only on changed pages when cache information is available.
- Skipped Marker entirely when no pages changed.
- Made Marker failures non-fatal; Supsidian now keeps Ollama OCR text even if Marker fails.
- Added optional Ollama model unloading after each processed note to free memory on 16 GB Macs.
