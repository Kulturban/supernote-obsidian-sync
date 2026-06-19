# Supernote → Obsidian Sync

A macOS menu bar app and command-line tool for syncing handwritten Supernote notes into an Obsidian vault.

It converts Supernote `.note` files to PDF, sends them to Mistral OCR, saves the OCR result as searchable Markdown, embeds the original PDF, extracts OCR images, and can convert handwritten task markers into Obsidian Tasks.

## Features

* macOS menu bar app
* Guided first-time setup
* Manual **Sync Now** workflow
* Convert Supernote `.note` files to PDF
* Run OCR with Mistral
* Save OCR text as Markdown in Obsidian
* Save original PDFs as Obsidian attachments
* Extract images detected by Mistral OCR
* Convert handwritten task markers into Obsidian tasks
* Support for multiple Supernote folders
* Each Supernote folder can sync to a different Obsidian folder
* Local settings stored in `config.json`
* Private API key stored in local `.env`
* Diagnostics and status checks
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
* Homebrew
* Obsidian
* Supernote Partner app
* Mistral API key
* `supernote-tool`

## Installation with Homebrew

First install the tap:

```bash
brew tap Kulturban/supernote-obsidian-sync
brew trust Kulturban/supernote-obsidian-sync
```

Install the command-line tool:

```bash
brew install supernote-obsidian-sync
```

Install the macOS menu bar app:

```bash
brew install --cask kulturban/supernote-obsidian-sync/supernote-obsidian-sync-app
```

Open the app:

```bash
open -a SupernoteObsidianSync
```

The menu bar app will appear in the macOS menu bar.

## First-time setup

Open the menu bar app and choose **Settings**.

The setup assistant will guide you through:

1. Choosing your Obsidian vault
2. Connecting `supernote-tool`
3. Adding your Mistral API key
4. Choosing one or more Supernote Partner folders

After setup is complete, choose **Sync Now** from the menu bar app.

## Recommended Supernote folder

Supernote Partner usually stores notes here:

```text
~/Library/Containers/com.ratta.supernote/Data/Library/Application Support/com.ratta.supernote/<YOUR_SUPERNOTE_ID>/Supernote/Note
```

The app tries to suggest this folder automatically during setup.

## Usage

### Menu bar app

Use the menu bar app for normal use:

* **Sync Now** — run one sync
* **Settings** — edit setup and folder mappings
* **Status** — show current configuration status
* **Diagnose** — check whether setup is valid
* **Log** — open the log file

The app currently uses manual sync. Background watching is not shown in the release UI.

### Command line

Run diagnostics:

```bash
supernote-obsidian-sync --diagnose
```

Run one sync:

```bash
supernote-obsidian-sync --once
```

Show status:

```bash
supernote-obsidian-sync --status
```

Open the settings folder:

```bash
supernote-obsidian-sync --open-settings
```

Open the log file:

```bash
supernote-obsidian-sync --open-log
```

Show help:

```bash
supernote-obsidian-sync --help
```

## Configuration

Settings are stored locally here:

```text
~/Library/Application Support/Supernote Obsidian Sync/
```

Important files:

```text
config.json
.env
supernote_obsidian_sync.log
processed_*.json
```

Most users should configure the app through the GUI.

Advanced users can edit `config.json` manually.

Example multi-folder config:

```json
{
  "vault_dir": "/Users/YOUR_USERNAME/Documents/Obsidian Vault",
  "supernote_tool_path": "/opt/homebrew/bin/supernote-tool",
  "check_interval_seconds": 60,
  "file_stability_wait_seconds": 10,
  "task_marker": "#",
  "task_tag": "#task",
  "open_requires_obsidian_running": true,
  "notebooks": [
    {
      "name": "Supernote",
      "source_dir": "/Users/YOUR_USERNAME/Library/Containers/com.ratta.supernote/Data/Library/Application Support/com.ratta.supernote/YOUR_SUPERNOTE_ID/Supernote/Note",
      "obsidian_note_folder": "Supernote",
      "attachment_folder": "Attachments/Supernote/Supernote",
      "state_file": "processed_supernote.json"
    }
  ]
}
```

## Task conversion

If your handwritten OCR result contains:

```markdown
#call my mum
#buy apples
```

the app converts it to:

```markdown
- [ ] #task call my mum
- [ ] #task buy apples
```

The marker and tag can be changed in Settings or in `config.json`:

```json
{
  "task_marker": "#",
  "task_tag": "#task"
}
```

## macOS permissions

macOS may ask for permission to let the app, Terminal, Python, Obsidian, or Supernote Partner access files.

If syncing fails, check permissions in:

```text
System Settings → Privacy & Security → Full Disk Access
```

You may need to allow:

* Supernote Obsidian Sync
* Terminal
* Obsidian
* Supernote Partner
* the Python executable used by Homebrew

Then run:

```bash
supernote-obsidian-sync --diagnose
```

## Troubleshooting

Run diagnostics:

```bash
supernote-obsidian-sync --diagnose
```

Open the log file:

```bash
supernote-obsidian-sync --open-log
```

Open the settings folder:

```bash
supernote-obsidian-sync --open-settings
```

Show recent log lines:

```bash
tail -n 50 "$HOME/Library/Application Support/Supernote Obsidian Sync/supernote_obsidian_sync.log"
```

Reset processed state for one folder:

```bash
rm "$HOME/Library/Application Support/Supernote Obsidian Sync/processed_supernote.json"
```

This forces the app to process notes again.

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

Run diagnostics:

```bash
supernote-obsidian-sync --diagnose
```

Run one sync:

```bash
supernote-obsidian-sync --once
```

To build the macOS app from source, open:

```text
macos/SupernoteObsidianSync/SupernoteObsidianSync.xcodeproj
```

in Xcode.

## Roadmap

* [x] Basic Python sync script
* [x] Config file
* [x] Logging
* [x] Diagnostics
* [x] Command-line entry point
* [x] Homebrew formula
* [x] Multi-folder configuration
* [x] macOS menu bar app
* [x] GUI settings window
* [x] Guided first-time setup
* [x] Manual Sync Now workflow
* [x] Homebrew cask for menu bar app
* [ ] Code signing and notarization
* [ ] Automatic updates
* [ ] Optional background watcher UI

## License

MIT
