# Supsidian

**Supernote → Obsidian Sync**

Supsidian is a macOS menu bar app and command-line tool for syncing handwritten Supernote notes into an Obsidian vault.

It converts Supernote `.note` files into PDFs, recognizes them with your selected OCR provider, saves the text as Markdown, preserves extracted visuals where available, and can convert handwritten task markers into Obsidian tasks.

## Highlights

* macOS menu bar app
* Manual **Sync Now** action
* Multi-folder Supernote → Obsidian mappings
* Mistral and local OCR provider options
* Optional **Custom OCR Instruction**
* PDF attachments saved directly into your Obsidian vault
* Extracted OCR images embedded in Markdown
* Task conversion for handwritten task markers (works with Obsidian's "Task" plugin)
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

After opening Supsidian, click the menu bar icon and open **Settings**.

The setup will guide you through:

1. Choosing your Obsidian vault
2. Choosing the `supernote-tool` path
3. Choosing an OCR strategy
4. Adding a Mistral API key only when using Mistral
5. Adding one or more Supernote folders

After setup, use **Sync Now** from the menu bar.

## How it works

Supsidian uses this basic workflow:

```
Supernote .note file
→ PDF conversion
→ Selected OCR provider
→ Markdown note in Obsidian
→ Original PDF and extracted visuals saved as attachments
```

The original Supernote note is not edited. Supsidian creates Markdown output inside your Obsidian vault.

## OCR providers

Supsidian supports three OCR providers. New interactive setup defaults to local Ollama; existing configurations without an explicit provider continue using Mistral for compatibility.

### local_ollama

`local_ollama` is the local OCR option. Supsidian renders each page and sends the rendered page image only to Ollama running on your own machine.

It requires:

* [Ollama](https://ollama.com/)
* PyMuPDF in the active Supsidian Python environment
* the `richardyoung/olmocr2:7b-q8` model

Pull the default model with:

```
ollama pull richardyoung/olmocr2:7b-q8
```

### mistral

`mistral` is the cloud OCR option and the best compatibility choice for existing configurations. It sends note/PDF content to Mistral's OCR API and requires a `MISTRAL_API_KEY`.

### hybrid_marker_olmocr

`hybrid_marker_olmocr` is an **Experimental** backend option for advanced users. It combines local Ollama/olmOCR text recognition with Marker layout and visual extraction. When Marker identifies drawings or other visual assets, Supsidian copies the cropped asset into the note attachment folder and embeds it near its document position in Obsidian.

It requires all `local_ollama` prerequisites plus `marker_single` on the runtime PATH. It is available in interactive setup as an **Experimental** option, and advanced users can also select it manually in `config.json`.

If the app or LaunchAgent PATH does not include `marker_single`, set `hybrid_marker_command` to its absolute path:

```json
{
  "ocr_provider": "hybrid_marker_olmocr",
  "hybrid_marker_command": "/absolute/path/to/marker_single"
}
```

### Privacy

`local_ollama` and `hybrid_marker_olmocr` do not send note pages to Mistral. They rely on Ollama and, for hybrid mode, Marker running on your own machine. `mistral` sends note/PDF content to Mistral's API. Local processing depends on how your local tools and machine are configured, so Supsidian does not describe it as fully private.

### Selecting a provider in config.json

Interactive setup offers `local_ollama`, `mistral`, and `hybrid_marker_olmocr`. You can also select a provider manually in:

```
~/Library/Application Support/Supernote Obsidian Sync/config.json
```

Example local Ollama configuration:

```json
{
  "ocr_provider": "local_ollama",
  "local_ollama_url": "http://localhost:11434/api/generate",
  "local_ollama_model": "richardyoung/olmocr2:7b-q8",
  "local_ollama_num_ctx": 8192
}
```

After changing providers, run diagnostics:

```
supernote-obsidian-sync --diagnose
```

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

## Provider-specific setup notes

`MISTRAL_API_KEY` is needed only when `ocr_provider` is `mistral`. It is not required for `local_ollama` or `hybrid_marker_olmocr`.

For Mistral, the key is stored locally in:

```
~/Library/Application Support/Supernote Obsidian Sync/.env
```

Example:

```
MISTRAL_API_KEY=your_key_here
```

For local providers, ensure the required local tools are available, then run:

```
supernote-obsidian-sync --diagnose
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

## Reprocessing notes

Switching OCR provider does not automatically reprocess notes already recorded as processed. To process eligible notes again with the selected provider, run:

```
supernote-obsidian-sync --reset-state
supernote-obsidian-sync --once
```

`--reset-state` makes eligible notes process again and may update generated Markdown and PDF attachment outputs. Back up important Obsidian notes before mass reprocessing.

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

Run tests:

```
pytest -q
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

If macOS blocks the app, right-click the app and choose **Open**. You may need to do this the first time you start the app.

If macOS says the app is damaged, cannot be opened, or offers to move it to the Trash, this is usually Gatekeeper quarantine behavior for unsigned apps.

You can remove the quarantine flag manually:

```
xattr -dr com.apple.quarantine /Applications/Supsidian.app
```

Then open Supsidian again:

```
open -a Supsidian
```

Code signing and notarization are planned for a future release.

## License

MIT License
