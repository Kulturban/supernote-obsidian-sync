"""Unit tests for Cloud VLM OCR providers (Gemini, Claude, OpenAI) and Pillow visual extraction."""

from __future__ import annotations

import importlib
import io
import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
MODULE_NAME = "supernote_obsidian_sync"


class FakeHTTPResponse:
    def __init__(self, status_code: int = 200, json_data: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = text if text else (json.dumps(json_data) if json_data is not None else "")

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        if self._json_data is None:
            raise ValueError("No JSON data")
        return self._json_data


@pytest.fixture
def load_sync_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import a fresh backend module isolated inside tmp_path."""

    test_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(test_home))
    monkeypatch.syspath_prepend(str(SRC_DIR))
    for env_var in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MISTRAL_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)

    def load(config: dict | None = None):
        app_support = test_home / "Library" / "Application Support" / "Supernote Obsidian Sync"
        app_support.mkdir(parents=True, exist_ok=True)
        if config is not None:
            (app_support / "config.json").write_text(json.dumps(config), encoding="utf-8")

        sys.modules.pop(MODULE_NAME, None)
        importlib.invalidate_caches()
        return importlib.import_module(MODULE_NAME)

    yield load
    sys.modules.pop(MODULE_NAME, None)


def make_sketch_page_png_bytes(
    width: int = 1000,
    height: int = 1000,
    rect: tuple[int, int, int, int] = (200, 300, 600, 500),
) -> bytes:
    """Create a white RGB PNG with a dark rectangular sketch drawn at `rect` (left, top, right, bottom)."""
    image = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle(rect, outline=(20, 20, 20), width=6)
    draw.line((rect[0], rect[1], rect[2], rect[3]), fill=(20, 20, 20), width=4)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def write_pdf_with_sketch(pdf_path: Path, page_texts: list[str], draw_box_on_page_1: bool = True) -> None:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    try:
        for index, text in enumerate(page_texts, start=1):
            page = document.new_page(width=400, height=500)
            page.insert_text((40, 60), text, fontsize=14)
            if draw_box_on_page_1 and index == 1:
                page.draw_rect(fitz.Rect(80, 150, 300, 320), color=(0, 0, 0), width=3)
                page.draw_line((80, 150), (300, 320), color=(0, 0, 0), width=2)
        document.save(pdf_path)
    finally:
        document.close()


# ------------------------------------------------------------
# 1. CONFIG, MODEL & API KEY RESOLUTION
# ------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "config_key", "env_var", "default_model"),
    [
        ("gemini", "gemini_api_key", "GEMINI_API_KEY", "gemini-4-hydrogen"),
        ("claude", "anthropic_api_key", "ANTHROPIC_API_KEY", "claude-sonnet-5-5"),
        ("openai", "openai_api_key", "OPENAI_API_KEY", "gpt-6.1-terra"),
    ],
)
def test_cloud_provider_defaults_and_key_resolution(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    config_key: str,
    env_var: str,
    default_model: str,
) -> None:
    # Env fallback when config key is omitted
    monkeypatch.setenv(env_var, "env-secret-key")
    module = load_sync_module({"ocr_provider": provider})
    assert provider in module.SUPPORTED_OCR_PROVIDERS
    assert module.resolve_cloud_ocr_model(provider) == default_model
    assert module.resolve_cloud_api_key(provider) == "env-secret-key"

    # Config key overrides env var, and ocr_model overrides default
    module = load_sync_module(
        {
            "ocr_provider": provider,
            "ocr_model": "custom-model-v9",
            config_key: "config-secret-key",
        }
    )
    assert module.resolve_cloud_ocr_model(provider) == "custom-model-v9"
    assert module.resolve_cloud_api_key(provider) == "config-secret-key"

    # Missing key raises clear error
    monkeypatch.delenv(env_var, raising=False)
    module = load_sync_module({"ocr_provider": provider})
    with pytest.raises(RuntimeError, match=env_var):
        module.require_cloud_api_key(provider)


# ------------------------------------------------------------
# 2. MOCKED HTTP CALLS & JSON PARSING (GEMINI, CLAUDE, OPENAI)
# ------------------------------------------------------------


def test_call_gemini_ocr_page_parses_json_and_sends_schema(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_sync_module({"ocr_provider": "gemini"})
    captured: dict = {}

    def fake_post(url: str, headers: dict, json: dict, timeout: int):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeHTTPResponse(
            200,
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        "```json\n"
                                        '{"markdown": "Top line\\n\\n[[VISUAL_1]]\\n\\nBottom line", '
                                        '"visuals": [{"id": "VISUAL_1", "box_2d": [280, 180, 520, 620]}]}'
                                        "\n```"
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(module.requests, "post", fake_post)
    markdown, visuals = module.call_gemini_ocr_page(
        make_sketch_page_png_bytes(),
        page_number=1,
        model="gemini-2.5-flash",
        api_key="gem-key",
    )

    assert "models/gemini-2.5-flash:generateContent" in captured["url"]
    assert captured["headers"]["x-goog-api-key"] == "gem-key"
    assert captured["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseSchema" in captured["json"]["generationConfig"]
    assert markdown == "Top line\n\n[[VISUAL_1]]\n\nBottom line"
    assert visuals == [{"id": "VISUAL_1", "box_2d": [280, 180, 520, 620]}]


def test_call_claude_ocr_page_parses_tool_use_and_text_fallback(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_sync_module({"ocr_provider": "claude"})
    captured: dict = {}

    def fake_post_tool_use(url: str, headers: dict, json: dict, timeout: int):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeHTTPResponse(
            200,
            {
                "content": [
                    {
                        "type": "tool_use",
                        "name": "submit_page_ocr",
                        "input": {
                            "markdown": "Heading\n\n[[VISUAL_1]]",
                            "visuals": [{"id": "VISUAL_1", "box_2d": [300, 200, 500, 600]}],
                        },
                    }
                ]
            },
        )

    monkeypatch.setattr(module.requests, "post", fake_post_tool_use)
    markdown, visuals = module.call_claude_ocr_page(
        make_sketch_page_png_bytes(),
        page_number=1,
        model="claude-sonnet-4-5",
        api_key="claude-key",
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "claude-key"
    assert captured["json"]["tool_choice"] == {"type": "tool", "name": "submit_page_ocr"}
    assert markdown == "Heading\n\n[[VISUAL_1]]"
    assert visuals == [{"id": "VISUAL_1", "box_2d": [300, 200, 500, 600]}]

    # Also verify plain JSON text block fallback
    def fake_post_text(url: str, headers: dict, json: dict, timeout: int):
        return FakeHTTPResponse(
            200,
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"markdown": "Plain text only", "visuals": []}',
                    }
                ]
            },
        )

    monkeypatch.setattr(module.requests, "post", fake_post_text)
    markdown_text, visuals_text = module.call_claude_ocr_page(
        make_sketch_page_png_bytes(),
        page_number=2,
        model="claude-sonnet-4-5",
        api_key="claude-key",
    )
    assert markdown_text == "Plain text only"
    assert visuals_text == []


def test_call_openai_ocr_page_parses_strict_json_schema_response(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_sync_module({"ocr_provider": "openai"})
    captured: dict = {}

    def fake_post(url: str, headers: dict, json: dict, timeout: int):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeHTTPResponse(
            200,
            {
                "choices": [
                    {
                        "message": {
                            "content": (
                                '{"markdown": "Intro\\n\\n[[VISUAL_1]]\\n\\nOutro", '
                                '"visuals": [{"id": "VISUAL_1", "box_2d": [290, 190, 510, 610]}]}'
                            )
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr(module.requests, "post", fake_post)
    markdown, visuals = module.call_openai_ocr_page(
        make_sketch_page_png_bytes(),
        page_number=1,
        model="gpt-4.1",
        api_key="openai-key",
    )

    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer openai-key"
    assert captured["json"]["response_format"]["json_schema"]["strict"] is True
    assert markdown == "Intro\n\n[[VISUAL_1]]\n\nOutro"
    assert visuals == [{"id": "VISUAL_1", "box_2d": [290, 190, 510, 610]}]


# ------------------------------------------------------------
# 3. PILLOW CROP, PADDING, WHITESPACE TRIMMING & PLACEHOLDERS
# ------------------------------------------------------------


def test_crop_and_save_visual_box_adds_padding_and_trims_excess_whitespace(
    load_sync_module,
    tmp_path: Path,
) -> None:
    module = load_sync_module()
    # Sketch is drawn at x=300..500, y=350..450 (200x100 px) inside a 1000x1000 white page.
    png_bytes = make_sketch_page_png_bytes(width=1000, height=1000, rect=(300, 350, 500, 450))
    page_image = Image.open(io.BytesIO(png_bytes)).convert("RGB")

    # Case A: Loose bounding box with lots of extra whitespace around the sketch -> trimmed tightly
    loose_out = tmp_path / "loose.jpeg"
    saved_loose = module.crop_and_save_visual_box(
        page_image,
        [150, 100, 700, 800],  # 700x550 px box containing lots of white margin
        loose_out,
        padding_ratio=0.035,
        trim_margin_px=8,
    )
    assert saved_loose is True
    assert loose_out.exists()
    with Image.open(loose_out) as cropped_loose:
        # Original drawn rect is 201x101 px; with 8px trim margin on each side -> ~217x117 px
        assert 205 <= cropped_loose.width <= 230
        assert 105 <= cropped_loose.height <= 130

    # Case B: Tight bounding box slightly inside the outer stroke -> 3.5% safety padding rescues stroke
    tight_out = tmp_path / "tight.jpeg"
    saved_tight = module.crop_and_save_visual_box(
        page_image,
        [353, 304, 447, 496],  # slightly inset from (300, 350, 500, 450)
        tight_out,
        padding_ratio=0.035,
        trim_margin_px=4,
    )
    assert saved_tight is True
    with Image.open(tight_out) as cropped_tight:
        assert cropped_tight.width >= 200
        assert cropped_tight.height >= 100


def test_crop_and_save_visual_box_rejects_invalid_or_blank_boxes(
    load_sync_module,
    tmp_path: Path,
) -> None:
    module = load_sync_module()
    png_bytes = make_sketch_page_png_bytes(width=1000, height=1000, rect=(300, 350, 500, 450))
    page_image = Image.open(io.BytesIO(png_bytes)).convert("RGB")

    # Inverted, malformed, or pure-white regions must return False without creating a file
    invalid_boxes = [
        [500, 200, 300, 400],  # ymin > ymax
        [100, 600, 200, 500],  # xmin > xmax
        [100, 100, 100, 200],  # zero height
        [10, 10, 100, 100],    # pure white area (no ink)
        [100, 100],            # wrong length
        [True, 0, 500, 500],   # bool value
        [float("nan"), 0, 500, 500],
    ]
    for index, box in enumerate(invalid_boxes):
        out = tmp_path / f"invalid-{index}.jpeg"
        assert module.crop_and_save_visual_box(page_image, box, out) is False
        assert not out.exists()


def test_apply_cloud_visuals_replaces_placeholders_appends_missing_and_strips_invalid(
    load_sync_module,
    tmp_path: Path,
) -> None:
    module = load_sync_module()
    # Two sketches on page 1
    image = Image.new("RGB", (1000, 1000), color=(255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 150, 400, 350), outline=(10, 10, 10), width=5)
    draw.rectangle((150, 600, 500, 800), outline=(10, 10, 10), width=5)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    markdown = "Above sketch 1\n\n[[VISUAL_1]]\n\nBetween\n\n[[VISUAL_BAD]]\n\nEnd text"
    visuals = [
        {"id": "VISUAL_1", "box_2d": [140, 90, 360, 410]},
        {"id": "VISUAL_BAD", "box_2d": [900, 900, 950, 950]},  # pure white -> discarded
        {"id": "VISUAL_2", "box_2d": [590, 140, 810, 510]},    # placeholder missing -> fallback append
    ]

    extracted_dir = tmp_path / "extracted_visuals"
    updated_md, saved_files = module.apply_cloud_visuals_to_page_markdown(
        markdown,
        png_bytes,
        visuals,
        page_number=1,
        extracted_visual_dir=extracted_dir,
        obsidian_image_folder="Attachments/Note",
    )

    assert saved_files == ["page-001-visual-001.jpeg", "page-001-visual-002.jpeg"]
    assert (extracted_dir / "page-001-visual-001.jpeg").is_file()
    assert (extracted_dir / "page-001-visual-002.jpeg").is_file()
    assert "[[VISUAL_1]]" not in updated_md
    assert "[[VISUAL_BAD]]" not in updated_md
    assert (
        "Above sketch 1\n\n![[Attachments/Note/extracted_visuals/page-001-visual-001.jpeg]]\n\nBetween"
        in updated_md
    )
    assert updated_md.endswith(
        "End text\n\n![[Attachments/Note/extracted_visuals/page-001-visual-002.jpeg]]"
    )


# ------------------------------------------------------------
# 4. CACHE FINGERPRINT & INVALIDATION ON PROVIDER / MODEL CHANGE
# ------------------------------------------------------------


def test_cloud_fingerprint_changes_on_provider_model_and_visual_version(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_sync_module({"ocr_provider": "gemini", "ocr_model": ""})
    fp_gemini_default = module.ocr_settings_fingerprint("gemini")
    fp_claude_default = module.ocr_settings_fingerprint("claude")
    fp_openai_default = module.ocr_settings_fingerprint("openai")

    assert len({fp_gemini_default, fp_claude_default, fp_openai_default}) == 3

    monkeypatch.setattr(module, "OCR_MODEL", "gemini-2.5-pro")
    fp_gemini_pro = module.ocr_settings_fingerprint("gemini")
    assert fp_gemini_pro != fp_gemini_default

    monkeypatch.setattr(module, "CLOUD_VISUAL_EXTRACTION_VERSION", "bbox-pillow-crop-v2")
    fp_gemini_pro_v2 = module.ocr_settings_fingerprint("gemini")
    assert fp_gemini_pro_v2 != fp_gemini_pro


def test_cloud_vlm_ocr_pdf_caches_pages_and_invalidates_on_provider_or_model_switch(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = load_sync_module(
        {
            "ocr_provider": "gemini",
            "gemini_api_key": "gem-test-key",
            "anthropic_api_key": "claude-test-key",
        }
    )
    monkeypatch.setattr(module, "OBSIDIAN_NOTE_DIR", tmp_path / "vault" / "notes")
    monkeypatch.setattr(module, "PDF_DIR", tmp_path / "vault" / "attachments")
    monkeypatch.setattr(module, "ACTIVE_ATTACHMENT_FOLDER", "Attachments/Test")

    note_file = tmp_path / "source" / "SketchNote.note"
    note_file.parent.mkdir(parents=True)
    note_file.write_bytes(b"fake-note")

    pdf_file = tmp_path / "staged" / "SketchNote.pdf"
    pdf_file.parent.mkdir(parents=True)
    write_pdf_with_sketch(pdf_file, ["Page 1 heading", "Page 2 text"], draw_box_on_page_1=True)

    image_dir = tmp_path / "staged"
    api_calls: list[tuple[str, str, int]] = []

    def fake_post(url: str, headers: dict, json: dict, timeout: int):
        if "generativelanguage.googleapis.com" in url:
            model_name = url.split("models/")[1].split(":")[0]
            api_calls.append(("gemini", model_name, len(api_calls) + 1))
            if len(api_calls) == 1:
                payload = {
                    "markdown": "Gemini Page 1\n\n[[VISUAL_1]]\n\n#follow up",
                    "visuals": [{"id": "VISUAL_1", "box_2d": [280, 180, 660, 770]}],
                }
            else:
                payload = {"markdown": "Gemini Page 2", "visuals": []}
            return FakeHTTPResponse(
                200,
                {"candidates": [{"content": {"parts": [{"text": module.json.dumps(payload)}]}}]},
            )
        if "api.anthropic.com" in url:
            api_calls.append(("claude", json["model"], len(api_calls) + 1))
            return FakeHTTPResponse(
                200,
                {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "submit_page_ocr",
                            "input": {
                                "markdown": f"Claude reprocessed {json['model']}",
                                "visuals": [],
                            },
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(module.requests, "post", fake_post)

    # 1. First run with Gemini: processes both pages and extracts visual on page 1
    md_first = module.cloud_vlm_ocr_pdf(
        pdf_file,
        image_dir,
        "Attachments/Test/SketchNote",
        note_file=note_file,
        provider="gemini",
    )
    assert len(api_calls) == 2
    assert "![[Attachments/Test/SketchNote/extracted_visuals/page-001-visual-001.jpeg]]" in md_first
    assert "- [ ] #task follow up" in md_first
    assert (image_dir / "extracted_visuals" / "page-001-visual-001.jpeg").is_file()

    cache_data = module.load_page_cache(note_file)
    assert cache_data is not None
    assert cache_data["provider"] == "gemini"
    assert cache_data["model"] == "gemini-4-hydrogen"
    assert cache_data["visual_extraction"] == module.CLOUD_VISUAL_EXTRACTION_VERSION

    # 2. Second run with same provider & model: 100% cache hit, zero API calls
    api_calls.clear()
    md_second = module.cloud_vlm_ocr_pdf(
        pdf_file,
        image_dir,
        "Attachments/Test/SketchNote",
        note_file=note_file,
        provider="gemini",
    )
    assert api_calls == []
    assert md_second == md_first

    # 3. Switch provider to Claude -> fingerprint changes -> cache invalidated, stale visual removed
    md_claude = module.cloud_vlm_ocr_pdf(
        pdf_file,
        image_dir,
        "Attachments/Test/SketchNote",
        note_file=note_file,
        provider="claude",
    )
    assert len(api_calls) == 2
    assert all(call[0] == "claude" for call in api_calls)
    assert "Claude reprocessed claude-sonnet-5-5" in md_claude
    # Stale visual from Gemini run is no longer referenced and was cleaned up
    assert not (image_dir / "extracted_visuals" / "page-001-visual-001.jpeg").exists()

    # 4. Change model on Claude -> fingerprint changes -> cache invalidated again
    api_calls.clear()
    monkeypatch.setattr(module, "OCR_MODEL", "claude-opus-4-1")
    md_claude_opus = module.cloud_vlm_ocr_pdf(
        pdf_file,
        image_dir,
        "Attachments/Test/SketchNote",
        note_file=note_file,
        provider="claude",
    )
    assert len(api_calls) == 2
    assert all(call[1] == "claude-opus-4-1" for call in api_calls)
    assert "Claude reprocessed claude-opus-4-1" in md_claude_opus


# ------------------------------------------------------------
# 5. REASONING / THINKING EFFORT PAYLOADS, FALLBACK & FINGERPRINT
# ------------------------------------------------------------


def test_ocr_reasoning_effort_payloads_and_gpt62_minimal_clamp(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_sync_module({"ocr_provider": "gemini", "ocr_reasoning_effort": "minimal"})
    sent_payloads: list[dict] = []

    def fake_post(url: str, headers: dict, json: dict, timeout: int):
        sent_payloads.append(json)
        if "generativelanguage.googleapis.com" in url:
            return FakeHTTPResponse(
                200,
                {"candidates": [{"content": {"parts": [{"text": '{"markdown": "ok", "visuals": []}'}]}}]},
            )
        if "api.openai.com" in url:
            return FakeHTTPResponse(
                200,
                {"choices": [{"message": {"content": '{"markdown": "ok", "visuals": []}'}}]},
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(module.requests, "post", fake_post)

    # Gemini receives thinkingConfig.thinkingLevel = "MINIMAL"
    module.call_gemini_ocr_page(make_sketch_page_png_bytes(), 1, "gemini-4-hydrogen", "key")
    assert sent_payloads[-1]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}

    # gpt-6.1-terra accepts minimal
    module.call_openai_ocr_page(make_sketch_page_png_bytes(), 1, "gpt-6.1-terra", "key")
    assert sent_payloads[-1]["reasoning_effort"] == "minimal"

    # gpt-6.2-sol and gpt-6.2-astra clamp minimal -> low
    module.call_openai_ocr_page(make_sketch_page_png_bytes(), 1, "gpt-6.2-sol", "key")
    assert sent_payloads[-1]["reasoning_effort"] == "low"

    module.call_openai_ocr_page(make_sketch_page_png_bytes(), 1, "gpt-6.2-astra", "key")
    assert sent_payloads[-1]["reasoning_effort"] == "low"

    # Legacy gpt-4.1 omits reasoning_effort cleanly
    module.call_openai_ocr_page(make_sketch_page_png_bytes(), 1, "gpt-4.1", "key")
    assert "reasoning_effort" not in sent_payloads[-1]


def test_ocr_reasoning_effort_retries_without_param_on_http_400_and_invalidates_fingerprint(
    load_sync_module,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_sync_module({"ocr_provider": "gemini", "ocr_reasoning_effort": "low"})
    fp_low = module.ocr_settings_fingerprint("gemini")
    monkeypatch.setattr(module, "OCR_REASONING_EFFORT", "high")
    fp_high = module.ocr_settings_fingerprint("gemini")
    assert fp_high != fp_low

    attempts: list[dict] = []

    def fake_post_retry(url: str, headers: dict, json: dict, timeout: int):
        attempts.append(dict(json["generationConfig"]))
        if len(attempts) == 1:
            return FakeHTTPResponse(400, text="Invalid JSON payload: Unknown name 'thinkingConfig'")
        return FakeHTTPResponse(
            200,
            {"candidates": [{"content": {"parts": [{"text": '{"markdown": "recovered", "visuals": []}'}]}}]},
        )

    monkeypatch.setattr(module.requests, "post", fake_post_retry)
    md, visuals = module.call_gemini_ocr_page(make_sketch_page_png_bytes(), 1, "gemini-4-hydrogen", "key")
    assert md == "recovered"
    assert visuals == []
    assert len(attempts) == 2
    assert "thinkingConfig" in attempts[0]
    assert "thinkingConfig" not in attempts[1]
