# Supernote → Obsidian Sync

A small macOS Python tool for syncing handwritten Supernote `.note` files into an Obsidian vault.

It converts Supernote notes to PDF, sends the PDF to Mistral OCR, saves the OCR result as Markdown, embeds the original PDF, and can convert handwritten task markers into Obsidian Tasks.

## Features

* Convert Supernote `.note` files to PDF
* Run OCR with Mistral
* Save OCR text as Markdown in Obsidian
* Save original PDFs as Obsidian attachments
* Extract images detected by Mistral OCR
* Convert handwritten task markers into Obsidian tasks
* Configurable via a local `config.json`
* Private API key via local `.env`
* Supports one-time sync and watch mode
* Includes diagnostics command
* Includes setup command

## Privacy warning

This tool reads local Supernote files and sends PDF data to Mistral OCR.

Do not use it with sensitive notes unless you are comfortable sending the note content to Mistral.

Never publish your:

* Mistral API key
* `.env`
* `config.json`
* processed state files
* logs
* personal notes
* real Supernote user ID
* personal file paths

## Requirements

* macOS
* Python 3
* Obsidian
* Supernote Partner app
* `supernote-tool`
* Mistral API key

## Installation from source

Clone the repository:

```bash
git clone https://github.com/Kulturban/supernote-obsidian-sync.git
cd supernote-obsidian-sync
```

Create a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## First setup

Run:

```bash
./bin/supernote-obsidian-sync --setup
```

This creates the user settings folder:

```text
~/Library/Application Support/Supernote Obsidian Sync/
```

Inside this folder, edit:

```text
config.json
.env
```

Add your Mistral API key to `.env`:

```bash
MISTRAL_API_KEY=your_api_key_here
```

## Configuration

The config file is stored here:

```text
~/Library/Application Support/Supernote Obsidian Sync/config.json
```

Example:

```json
{
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
  "open_requires_obsidian_running": true
}
```

## Usage

Run setup:

```bash
./bin/supernote-obsidian-sync --setup
```

Run diagnostics:

```bash
./bin/supernote-obsidian-sync --diagnose
```

Run one sync scan:

```bash
./bin/supernote-obsidian-sync --once
```

Run continuously:

```bash
./bin/supernote-obsidian-sync
```

## Task conversion

If your handwritten OCR result contains:

```markdown
#call my mum
#buy apples
```

the script converts it to:

```markdown
- [ ] #task call my mum
- [ ] #task buy apples
```

The marker and tag can be changed in `config.json`:

```json
{
  "task_marker": "#",
  "task_tag": "#task"
}
```

## macOS permissions

macOS may ask for permission to let Python access files from other apps.

If syncing fails, give Full Disk Access to:

* Terminal
* Obsidian
* Supernote Partner
* the Python executable inside `.venv`

Find the Python executable with:

```bash
.venv/bin/python -c "import sys; print(sys.executable)"
```

Then add it in:

```text
System Settings → Privacy & Security → Full Disk Access
```

## Troubleshooting

Run diagnostics:

```bash
./bin/supernote-obsidian-sync --diagnose
```

Check the log:

```bash
tail -n 50 "$HOME/Library/Application Support/Supernote Obsidian Sync/supernote_obsidian_sync.log"
```

Reset processed state:

```bash
rm "$HOME/Library/Application Support/Supernote Obsidian Sync/processed_notes.json"
```

This forces the script to process notes again.

## Roadmap

* [x] Basic Python sync script
* [x] Config file
* [x] Logging
* [x] Diagnostics
* [x] Setup command
* [x] Command-line entry point
* [ ] Homebrew installation
* [ ] macOS menu bar app
* [ ] GUI settings window
* [ ] packaged `.app`
* [ ] automatic updates

## License

MIT
