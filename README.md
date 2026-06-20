# Supsidian

**Supernote → Obsidian Sync**

Supsidian is a macOS menu bar app and command-line tool for syncing handwritten Supernote notes into an Obsidian vault.

It converts Supernote `.note` files into PDFs, sends them to Mistral OCR, saves the recognized text as Markdown, preserves extracted images, and can turn handwritten task markers into Obsidian tasks.

## Features

* macOS menu bar app
* Manual **Sync Now** action
* Multi-folder Supernote → Obsidian mappings
* Mistral OCR integration
* Optional **Custom OCR Instruction**
* PDF attachments saved into your vault
* Extracted OCR images embedded in Markdown
* Task conversion for handwritten task markers
* First-time setup flow
* Diagnostics and log access
* Runs as a menu-bar-only app and stays hidden from the Dock

## Installation

### 1. Install the command-line tool

```
brew install kulturban/supernote-obsidian-sync/supernote-obsidian-sync
```

### 2. Install Supsidian

```
brew install --cask kulturban/supernote-obsidian-sync/supsidian
```

### 3. Open Supsidian

```
open -a Supsidian
```

Supsidian runs as a menu bar app. It does not appear in the Dock.

## First setup

After opening Supsidian, open **Settings** from the menu bar icon.

The setup will guide you through:

1. Choosing your Obsidian vault
2. Choosing the `supernote-tool` path
3. Adding your Mistral API key
4. Adding one or more Supernote folders

After setup, use **Sync Now** from the menu bar.

## Configuration folder

Supsidian currently stores settings here:

```
~/Library/Application Support/Supernote Obsidian Sync/
```

This folder name is kept for compatibility with earlier versions.

Important files:

```
config.json
.env
supernote_obsidian_sync.log
```

## Mistral API key

Supsidian uses Mistral OCR. You need a Mistral API key.

The key is stored locally in:

```
~/Library/Application Support/Supernote Obsidian Sync/.env
```

Example:

```
MISTRAL_API_KEY=your_key_here
```

## Custom OCR Instruction

The **Custom OCR Instruction** field is optional.

You can use it to guide how OCR output should be rendered.

Example:

```
Preserve headings and bullet lists. Keep diagrams as images. Do not summarize. Keep the original wording as faithfully as possible.
```

Leave it empty for the default faithful OCR behavior.

Bad instructions can reduce OCR quality, so keep the prompt short and clear.

## Task conversion

Supsidian can convert OCR lines into Obsidian tasks.

Default handwritten/OCR line:

```
# Buy milk
```

Becomes:

```
- [ ] #task Buy milk
```

The default task settings are:

```
task_marker: #
task_tag: #task
```

You can change these in **Settings → OCR & Tasks**.

## Multi-folder sync

Supsidian supports multiple Supernote folders.

Each folder can be mapped to its own Obsidian note folder and attachment folder.

Example:

```
Supernote/Psychomotorik
→ Obsidian/Psychomotorik
→ Attachments/Supernote/Psychomotorik
```

Configure folders in:

```
Settings → Folders
```

## Manual sync

Supsidian is currently designed around manual syncing.

Use:

```
Sync Now
```

from the menu bar.

The command-line equivalent is:

```
supernote-obsidian-sync --once
```

## Diagnostics

Run diagnostics from the menu bar:

```
Settings → Diagnostics
```

Or from Terminal:

```
supernote-obsidian-sync --diagnose
```

Show status:

```
supernote-obsidian-sync --status
```

Open settings folder:

```
supernote-obsidian-sync --open-settings
```

Open log:

```
supernote-obsidian-sync --open-log
```

## Command-line tool

The command-line tool is still called:

```
supernote-obsidian-sync
```

This is intentional for compatibility.

Useful commands:

```
supernote-obsidian-sync --once
supernote-obsidian-sync --diagnose
supernote-obsidian-sync --status
supernote-obsidian-sync --open-settings
supernote-obsidian-sync --open-log
```

## Development

Clone the repository:

```
git clone https://github.com/Kulturban/supernote-obsidian-sync.git
cd supernote-obsidian-sync
```

Install in editable mode:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Build the macOS app:

```
xcodebuild \
  -project macos/SupernoteObsidianSync/SupernoteObsidianSync.xcodeproj \
  -scheme SupernoteObsidianSync \
  -configuration Release \
  -derivedDataPath /tmp/supsidian-build \
  clean build
```

Find the app:

```
find /tmp/supsidian-build -name "*.app" -type d
```

## Current naming

Public app name:

```
Supsidian
```

Command-line tool:

```
supernote-obsidian-sync
```

Python package:

```
supernote_obsidian_sync
```

Settings folder:

```
~/Library/Application Support/Supernote Obsidian Sync/
```

This avoids breaking existing installations.

## Notes

Supsidian is currently unsigned and not notarized.

If macOS blocks the app, right-click the app and choose **Open**.

Code signing and notarization are planned for a future release.

## License

MIT License
