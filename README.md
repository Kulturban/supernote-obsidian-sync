# Supernote → Obsidian Sync

A macOS command-line tool for syncing handwritten Supernote `.note` files into an Obsidian vault.

It converts Supernote notes to PDF, sends the PDF to Mistral OCR, saves the OCR result as searchable Markdown, embeds the original PDF, and can convert handwritten task markers into Obsidian Tasks.

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
* Includes setup and diagnostics commands
* Installable with Homebrew

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
* Homebrew
* Obsidian
* Supernote Partner app
* `supernote-tool`
* Mistral API key

## Installation with Homebrew

Install the Homebrew tap and formula:

```bash
brew tap Kulturban/supernote-obsidian-sync
brew trust Kulturban/supernote-obsidian-sync
brew install supernote-obsidian-sync
```

Then run the first setup:

```bash
supernote-obsidian-sync --setup
```

This creates the settings folder:

```text
~/Library/Application Support/Supernote Obsidian Sync/
```

Open the settings folder in Finder:

```bash
open "$HOME/Library/Application Support/Supernote Obsidian Sync"
```

Edit `config.json`:

```bash
open -a TextEdit "$HOME/Library/Application Support/Supernote Obsidian Sync/config.json"
```

Edit `.env`:

```bash
open -a TextEdit "$HOME/Library/Application Support/Supernote Obsidian Sync/.env"
```

In `.env`, replace:

```bash
MISTRAL_API_KEY=your_mistral_api_key_here
```

with your real Mistral API key.

Then run diagnostics:

```bash
supernote-obsidian-sync --diagnose
```

If all important checks pass, run one sync:

```bash
supernote-obsidian-sync --once
```

To keep watching continuously:

```bash
supernote-obsidian-sync
```

## Configuration

The config file is stored here:

```text
~/Library/Application Support/Supernote Obsidian Sync/config.json
```

Example config:

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

### Important config fields

`source_dir`
The folder where Supernote Partner stores your `.note` files.

`vault_dir`
Your Obsidian vault folder.

`obsidian_note_folder`
The folder inside your Obsidian vault where Markdown notes should be saved.

`attachment_folder`
The folder inside your Obsidian vault where PDFs and images should be saved.

`supernote_tool_path`
The path to your installed `supernote-tool`.

`task_marker`
The handwritten marker used to create tasks. Default: `#`

`task_tag`
The Obsidian task tag that will be inserted. Default: `#task`

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

## Usage

Run setup:

```bash
supernote-obsidian-sync --setup
```

Run diagnostics:

```bash
supernote-obsidian-sync --diagnose
```

Run one sync scan:

```bash
supernote-obsidian-sync --once
```

Run continuously:

```bash
supernote-obsidian-sync
```

Show help:

```bash
supernote-obsidian-sync --help
```

## macOS permissions

macOS may ask for permission to let Python access files from other apps.

If syncing fails, give Full Disk Access to:

* Terminal
* Obsidian
* Supernote Partner
* the Python executable used by Homebrew

You can find the installed command with:

```bash
which supernote-obsidian-sync
```

Then check diagnostics again:

```bash
supernote-obsidian-sync --diagnose
```

## Troubleshooting

Run diagnostics:

```bash
supernote-obsidian-sync --diagnose
```

Check the log:

```bash
tail -n 50 "$HOME/Library/Application Support/Supernote Obsidian Sync/supernote_obsidian_sync.log"
```

Open the settings folder:

```bash
open "$HOME/Library/Application Support/Supernote Obsidian Sync"
```

Reset processed state:

```bash
rm "$HOME/Library/Application Support/Supernote Obsidian Sync/processed_notes.json"
```

This forces the script to process notes again.

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
pip install -e .
```

Run setup:

```bash
supernote-obsidian-sync --setup
```

Run diagnostics:

```bash
supernote-obsidian-sync --diagnose
```

## Roadmap

* [x] Basic Python sync script
* [x] Config file
* [x] Logging
* [x] Diagnostics
* [x] Setup command
* [x] Command-line entry point
* [x] Homebrew installation
* [ ] macOS menu bar app
* [ ] GUI settings window
* [ ] packaged `.app`
* [ ] automatic updates

## License

MIT
