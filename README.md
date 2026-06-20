# Supsidian

**Supernote → Obsidian Sync**

Supsidian is a macOS menu bar app and command-line tool for syncing handwritten Supernote notes into an Obsidian vault.

It converts Supernote `.note` files into PDFs, sends them to Mistral OCR, saves the recognized text as Markdown, preserves extracted images, and can convert handwritten task markers into Obsidian tasks.

## Highlights

* macOS menu bar app
* Manual **Sync Now** action
* Multi-folder Supernote → Obsidian mappings
* Mistral OCR integration
* Optional **Custom OCR Instruction**
* PDF attachments saved directly into your Obsidian vault
* Extracted OCR images embedded in Markdown
* Task conversion for handwritten task markers (works with Obsidian's "Task" plugin)
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
3. Adding your Mistral API key
4. Adding one or more Supernote folders

After setup, use **Sync Now** from the menu bar.

## How it works

Supsidian uses this basic workflow:

```
Supernote .note file
→ PDF conversion
→ Mistral OCR
→ Markdown note in Obsidian
→ PDF and extracted images saved as attachments
```

The original Supernote note is not edited. Supsidian creates Markdown output inside your Obsidian vault.


## Notes
Supsidian is currently unsigned and not notarized.

If macOS blocks the app, right-click the app and choose Open. You may need to do this the first time you start the app.

If macOS says the app is damaged, cannot be opened, or offers to move it to the Trash, this is usually Gatekeeper quarantine behavior for unsigned apps.

You can remove the quarantine flag manually:

xattr -dr com.apple.quarantine /Applications/Supsidian.app

Then open Supsidian again:

open -a Supsidian

## License

MIT License
