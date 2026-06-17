# Supernote → Obsidian Sync

A small macOS Python tool for syncing handwritten Supernote `.note` files into an Obsidian vault.

It converts Supernote notes to PDF, sends the PDF to Mistral OCR, saves the OCR result as Markdown, embeds the original PDF, and can convert handwritten task markers into Obsidian Tasks.

## Features

- Convert Supernote `.note` files to PDF
- Run OCR with Mistral
- Save OCR text as Markdown in Obsidian
- Save original PDFs as Obsidian attachments
- Convert handwritten task markers into Obsidian tasks
- Configurable via `local/config.json`
- Supports one-time sync and watch mode
- Includes diagnostics command
- macOS launcher script included

## Privacy warning

This tool reads local Supernote files and sends PDF data to Mistral OCR.

Do not use it with sensitive notes unless you are comfortable sending the note content to Mistral.

Never publish your:

- Mistral API key
- `local/.env`
- `local/config.json`
- processed state files
- logs
- personal notes
- real Supernote user ID
- personal file paths

## Requirements

- macOS
- Python 3
- Obsidian
- Supernote Partner app
- `supernote-tool`
- Mistral API key

## Installation

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
