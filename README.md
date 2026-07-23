# merge_pdf

A small interactive CLI that merges a folder of PDFs into a single document with a
clickable table of contents ("Table des annexes"). Built for assembling a main
document plus a set of appendices.

## What it does

- Reads every `*.pdf` in the `pdfs/` directory.
- Prompts you to pick the **main document** and the **order** and **titles** of the appendices.
- Generates a merged PDF (`merged_with_toc.pdf`) laid out as:
  1. the main document,
  2. a generated table of contents with page numbers,
  3. each appendix, prefixed by a title page.
- Adds PDF bookmarks, clickable links from the table of contents to each appendix,
  and a "Retour à la table des annexes" back-link on every title page.
- Remembers your last choices in `merge_pdf_checkpoint.json` so re-running is fast.

> The interactive prompts are in French.

## Usage

Requires Python 3 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
mkdir -p pdfs        # drop your PDFs in here
uv run main.py
```

The result is written to `merged_with_toc.pdf`.

## Dependencies

- [pypdf](https://pypi.org/project/pypdf/) — read/write and merge PDFs.
- [reportlab](https://pypi.org/project/reportlab/) — generate the table of contents and title pages.
