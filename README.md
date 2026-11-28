# Supsidian

**Supernote → Obsidian Sync for macOS**

[![Latest Release](https://img.shields.io/badge/release-v0.13.5-blue)](https://github.com/Kulturban/supernote-obsidian-sync/releases/latest)
[![Platform](https://img.shields.io/badge/platform-macOS-lightgrey)](https://github.com/Kulturban/supernote-obsidian-sync/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

> **[⬇️ Download Latest macOS App (`Supsidian-0.13.5-macOS.zip`)](https://github.com/Kulturban/supernote-obsidian-sync/releases/latest)**

Supsidian is a lightweight macOS menu bar app and Python CLI that turns handwritten Supernote `.note` files into searchable Obsidian Markdown notes — complete with PDF attachments, automatically cropped hand-drawn sketches and diagrams, page-level incremental syncing, and customizable OCR instruction tabs.

---

## Highlights

- **Menu Bar App with Live Progress:** Runs quietly in the macOS menu bar (hidden from the Dock) and displays live sync progress (`🔄 Supsidian 40%`) directly in the menu bar and dropdown without intrusive popup windows.
- **Sync All, Sync Folder, or Sync a Single File:**
  - **Sync Now:** Sync all configured Supernote folders.
  - **Sync Folder → `<Folder>` → `Sync Entire Folder`:** Sync one specific folder.
  - **Sync Folder → `<Folder>` → `<Note.note>`:** Sync a single `.note` file on demand.
- **Page-Level Incremental Sync:** Hashes rendered PDF pages locally (`SHA-256`) so only newly added or modified pages are sent to OCR. Unchanged `## Page N` sections — including your manual edits in Obsidian — are preserved in place.
- **Cloud & Local OCR Providers (v0.13.5):**
  - **Google Gemini** (`gemini-4-hydrogen` default, plus `gemini-3.5-flash-lite`, `gemini-3.8-flash`, `gemini-4-neon`, `gemini-4-argon`, `gemini-4-carbon`)
  - **Anthropic Claude** (`claude-sonnet-5-5` default, plus `claude-haiku-5-5`, `claude-opus-5-5`, `claude-fable-5-2`)
  - **OpenAI** (`gpt-6.1-terra` default, plus `gpt-6-luna`, `gpt-6.2-sol`, `gpt-6.2-astra`)
  - **Mistral OCR** (`mistral-ocr-latest`)
  - **Local Ollama** (`qwen3-vl:8b-instruct` recommended for 16 GB Macs, or `richardyoung/olmocr2:7b-q8`)
    Fully white pages are skipped before Ollama OCR, and their page headings are retained.
  - **Hybrid Marker + Ollama (Experimental)** (sequential RAM unload before Marker + local Qwen3-VL sketch fallback)
  - **No OCR (PDF Embed Only)** (generates companion `.md` with YAML frontmatter and `![[<Note>.pdf]]` embed)
- **Automatic Sketch & Diagram Cropping:** Cloud VLM providers and Qwen3-VL detect hand-drawn sketches, diagrams, and charts via normalized bounding boxes (`0..1000`). Supsidian crops them **locally with Pillow** (adding a safety margin and trimming excess whitespace) and embeds them as `![[.../extracted_visuals/page-NNN-visual-MMM.jpeg]]` at the exact vertical reading position.
- **Tabbed Custom OCR Instructions:** Organize custom prompt rules in horizontal tabs under **Settings → OCR** (including built-in **Task Conversion**: `# Buy milk` → `- [ ] #task Buy milk`). Toggle, edit, save (`.json`/`.txt`), and load instruction tabs — applied across every OCR provider.
- **Privacy & Data Minimization:** Unchanged and blank pages are filtered 100% locally. Cloud VLM requests send only metadata-free page bitmaps (no filenames, folder paths, usernames, or full PDFs), and `config.json` / `.env` are written with restricted `0600` permissions.

---

## Download & Installation

### Option A: Direct Download from GitHub Releases (Recommended)

1. Download **`Supsidian-0.13.5-macOS.zip`** from the [latest GitHub Release](https://github.com/Kulturban/supernote-obsidian-sync/releases/tag/v0.13.5).
2. Unzip and move **`Supsidian.app`** into `/Applications`.
3. Install the Python CLI backend (and `supernote-tool` converter):
   ```bash
   git clone https://github.com/Kulturban/supernote-obsidian-sync.git ~/supernote-obsidian-sync
   cd ~/supernote-obsidian-sync
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
4. Remove the macOS Gatekeeper quarantine flag (required once for unsigned builds) and launch **Supsidian**:
   ```bash
   xattr -dr com.apple.quarantine /Applications/Supsidian.app
   open -a Supsidian
   ```

### Option B: Homebrew

```bash
brew install kulturban/supernote-obsidian-sync/supernote-obsidian-sync
brew install --cask kulturban/supernote-obsidian-sync/supsidian
open -a Supsidian
```

---

## First-Time Setup

Click the **Supsidian** icon in the macOS menu bar and choose **Settings…**:

1. **Obsidian Settings:** Select your **Obsidian vault** root folder and click **Auto-detect** (or **Choose…**) for `supernote-tool`.
2. **Folders:** Add each Supernote folder as a horizontal tab (**+ New Folder**) and choose its target Markdown and attachment folders inside your vault.
3. **OCR:** Choose your preferred OCR provider:
   - For **Google Gemini / Anthropic Claude / OpenAI**: Enter your API key, pick a model preset (or click **Load Available Models** to query live model IDs from the API), keep **Reasoning / Thinking effort** on `Low (Empfohlen)` for fast, low-cost OCR, and click **Test Connection**.
   - For **Local Ollama / Hybrid Marker + Ollama**: Select **`qwen3-vl:8b-instruct (Recommended — 16 GB)`** (or `richardyoung/olmocr2:7b-q8`) and click **Install Ollama Model** / **Check Local OCR Setup**.
4. Click **Save Settings**, then run **Sync Now** (or **Sync Folder**) from the menu bar.

---

## OCR Providers Overview

| Provider (`ocr_provider`) | Runs Where | Visual / Sketch Extraction | Best For |
| :--- | :--- | :--- | :--- |
| `gemini` | Cloud (Google) | Bounding-Box + local Pillow crop | Fast, high-accuracy handwriting & sketches (`gemini-4-hydrogen`) |
| `claude` | Cloud (Anthropic) | Bounding-Box + local Pillow crop | Complex structured notes (`claude-sonnet-5-5`) |
| `openai` | Cloud (OpenAI) | Bounding-Box + local Pillow crop | Visual reasoning & precise coordinates (`gpt-6.1-terra`) |
| `mistral` | Cloud (Mistral) | Native Mistral OCR image assets | Fast full-PDF cloud OCR (`mistral-ocr-latest`) |
| `local_ollama` | 100% Local (Mac) | Text transcription | Private local handwriting OCR (`qwen3-vl:8b-instruct`) |
| `hybrid_marker_olmocr` | 100% Local (Mac) | Marker crops + Qwen3-VL fallback | Local OCR with diagram/sketch extraction on 16 GB+ Macs |
| `none` | 100% Local (Mac) | Full PDF embed (`![[Note.pdf]]`) | Instant PDF sync with companion Markdown frontmatter |

> **Important Note for Local Qwen3-VL on Ollama:** Always use **`qwen3-vl:8b-instruct`** (the non-thinking instruct variant) rather than `qwen3-vl:8b`, so Ollama writes the transcription directly without spending tokens in thinking mode.

---

## Custom OCR Instructions & Task Conversion

Under **Settings → OCR → Custom OCR Instructions**, each horizontal tab defines a rule that is automatically appended to every OCR run regardless of the active provider:

- **Task Conversion (included by default):**
  ```text
  # Buy milk
  ```
  becomes an Obsidian task checkbox:
  ```markdown
  - [ ] #task Buy milk
  ```
- **Custom Tabs:** Click **+ New Instruction** to add rules (e.g. math formatting, language hints, or heading structure). Use **Save…** and **Load…** to export or import instruction presets as `.json` or `.txt`.

---

## Privacy & Security Architecture

When using external cloud providers (`gemini`, `claude`, `openai`), Supsidian minimizes transmitted data automatically:

1. **Page-Level SHA-256 Cache:** Unchanged pages are matched locally against `cache.json` and never re-uploaded.
2. **Local Blank-Page Filtering:** Empty or near-blank template pages (`< 0.03%` ink) are detected locally and skipped without an API request.
3. **Metadata-Free Bitmaps:** Only a freshly encoded RGB PNG of the changed page (capped at `1800 px` on the longest edge) is sent — no `.note` files, no full PDFs, no file names, no folder paths, and no EXIF chunks.
4. **Local Pillow Cropping:** The cloud model only returns numeric coordinates (`[ymin, xmin, ymax, xmax]`). All sketch cropping and whitespace trimming happen locally on your Mac.
5. **Restricted Credentials (`0600`):** API keys in `~/Library/Application Support/Supernote Obsidian Sync/config.json` and `.env` are written with POSIX `0600` owner-only permissions (or can be supplied via `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `MISTRAL_API_KEY`).

---

## Command-Line Interface (`supernote-obsidian-sync`)

```bash
# Sync all configured folders once
supernote-obsidian-sync --once

# Sync only a specific configured folder
supernote-obsidian-sync --once --folder "Praktikum Dietlimoos"

# Sync only a single .note file (by path, relative path, or filename/stem)
supernote-obsidian-sync --once --folder "Praktikum Dietlimoos" --file "Praktikumstag 3.note"

# Run setup diagnostics
supernote-obsidian-sync --diagnose

# Show current configuration & status
supernote-obsidian-sync --status

# Open settings folder or log file
supernote-obsidian-sync --open-settings
supernote-obsidian-sync --open-log

# Reset processed-note state to force a full check on next sync
supernote-obsidian-sync --reset-state
```

---

## Development & Building from Source

```bash
git clone https://github.com/Kulturban/supernote-obsidian-sync.git
cd supernote-obsidian-sync

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"

# Run unit test suite
.venv/bin/pytest -q

# Build macOS Release app
xcodebuild \
  -project macos/SupernoteObsidianSync/SupernoteObsidianSync.xcodeproj \
  -scheme SupernoteObsidianSync \
  -configuration Release \
  -derivedDataPath /tmp/supsidian-build \
  build
```

---

## License

[MIT License](LICENSE)
