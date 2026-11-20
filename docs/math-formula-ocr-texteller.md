# Math formula OCR and Texteller 3.0 investigation

This note is preliminary. It is based on the current Supsidian pipeline and local
testing observations, not on verified Texteller 3.0 product documentation.

## Current failure mode

Math formulas are still fragile in local OCR output. The common failures are:

- formulas are converted into approximate prose or LaTeX-like text;
- uncertain symbols, exponents, fractions, and roots are guessed;
- table cells containing formulas can be recognized inconsistently;
- Markdown conversion can preserve the wrong syntax even when the visual layout is otherwise useful.

The current safe prompt tells olmOCR to use plain-text math when clear and
`[unclear formula]` when uncertain, but model compliance is imperfect.

## Where formulas can be lost

1. **Supernote PDF conversion**
   - If the generated PDF preserves the handwriting clearly, this step is probably not the main loss point.
   - If strokes are rasterized too small or faintly, later OCR has less signal.

2. **Ollama / olmOCR**
   - This is currently the most likely loss point for handwritten math.
   - The model may infer symbols or emit LaTeX-ish notation even when the prompt asks for plain text.

3. **Marker**
   - Marker is used for layout and visual extraction in hybrid mode.
   - It can help place visuals and tables, but it is not currently the source of the final page text.
   - In v0.11.x, Marker output is intentionally not cached and Marker failures are non-fatal.

4. **HTML/table conversion**
   - The forgiving converter can turn irregular HTML tables into Markdown tables.
   - It preserves simple LaTeX-ish cell text as text, but it does not understand or validate formulas.

## What Texteller 3.0 might add

Texteller 3.0 may be useful if it provides stronger math-aware OCR for:

- handwritten formulas;
- equations embedded in note text;
- formula-heavy tables;
- consistent Markdown or plain-text math output.

This needs source verification before implementation:

- Is Texteller 3.0 available as a local model, command-line tool, Python package, or API?
- Does it support handwriting, or mainly printed/scanned math?
- Can it process cropped page images or formula regions?
- What license, runtime, hardware, and privacy constraints apply?
- What output formats are supported: plain text, Markdown, LaTeX, MathML, JSON?

## Possible provider designs

Do not implement these until Texteller details are verified.

### `texteller_math`

Use Texteller as a math-focused OCR provider or post-processor.

Open questions:

- Should it process the whole page or only detected formula regions?
- How would non-math handwriting be handled?
- Would it replace olmOCR or only correct formula spans?

### `hybrid_texteller_marker`

Use local OCR for text, Marker for visuals/layout, and Texteller for formula
regions.

Open questions:

- How are formula regions detected?
- How are Texteller formula results merged back into the page text?
- How are page-cache fingerprints invalidated when Texteller settings change?

## Tests needed before integration

- A PDF page with one clear formula should preserve the formula exactly.
- A page with an uncertain formula should emit `[unclear formula]` or another explicit uncertainty marker.
- A formula inside a Markdown table cell should remain in the correct cell.
- Switching math OCR settings should invalidate the page cache.
- Non-math pages should not be changed by a math post-processor.

## Recommendation

Keep v0.12.0 focused on Markdown quality, visual preservation, and progress
reporting. Treat Texteller as a separate research spike after verifying its
runtime and output format from primary sources.
