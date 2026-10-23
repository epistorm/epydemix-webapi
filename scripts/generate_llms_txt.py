"""Generate ``web/static/llms-full.txt`` from the docs MDX/MD files.

llms-full.txt is the long-form companion to ``llms.txt``: a single markdown
file containing all docs concatenated, suitable for RAG ingestion or for
agents that want the entire knowledge base in one fetch. Per
[llmstxt.org](https://llmstxt.org).

The script walks ``web/docs/**/*.{mdx,md}``, strips frontmatter, removes the
JSX import lines that Docusaurus pages need, replaces the project's
``<CurlBlock>`` tags with bash code fences, drops bare self-closing JSX tags
(e.g. ``<EndpointSelector />``), and concatenates the cleaned content with
section separators.

Re-run after adding or substantially editing a doc page:

    uv run python scripts/generate_llms_txt.py
"""

from __future__ import annotations

import re
from pathlib import Path

DOCS_DIR = Path(__file__).resolve().parents[1] / "web" / "docs"
STATIC_DIR = Path(__file__).resolve().parents[1] / "web" / "static"
OUTPUT = STATIC_DIR / "llms-full.txt"
# Per-page markdown copies are written under web/static/docs/<path>.md so they
# serve at /docs/<path>.md on the docs site (a plain mirror of each MDX page).
PER_PAGE_DIR = STATIC_DIR / "docs"

# Strip the YAML frontmatter at the top of the file.
_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n+", re.DOTALL)

# Strip ESM-style import lines used by Docusaurus.
_IMPORT_LINE_RE = re.compile(r"^import\s+.*from\s+['\"][^'\"]+['\"];?\s*$", re.MULTILINE)

# Replace <CurlBlock>{`...`}</CurlBlock> with a ```bash code fence.
_CURL_BLOCK_RE = re.compile(
    r"<CurlBlock>\s*\{\s*`(.*?)`\s*\}\s*</CurlBlock>",
    re.DOTALL,
)

# Drop bare self-closing JSX tags on their own line (e.g. <EndpointSelector />).
_SELF_CLOSING_JSX_RE = re.compile(r"^<[A-Z][A-Za-z0-9]*\s*/>\s*$", re.MULTILINE)

# Collapse runs of blank lines.
_MULTI_BLANK_RE = re.compile(r"\n{3,}")


def _clean(text: str) -> str:
    text = _FRONTMATTER_RE.sub("", text)
    text = _CURL_BLOCK_RE.sub(lambda m: f"```bash\n{m.group(1).strip()}\n```", text)
    text = _IMPORT_LINE_RE.sub("", text)
    text = _SELF_CLOSING_JSX_RE.sub("", text)
    return _MULTI_BLANK_RE.sub("\n\n", text).strip() + "\n"


def _per_page_path(rel_doc_path: str) -> Path:
    """Map ``intro.md`` → ``static/docs/intro.md``, ``guides/foo.mdx`` → ``static/docs/guides/foo.md``."""
    p = Path(rel_doc_path)
    return PER_PAGE_DIR / p.with_suffix(".md")


def main() -> None:
    # Release notes mirror what's already on GitHub Releases; we still want
    # per-page markdown mirrors so the in-page Copy / Open in chat widget
    # works on each release-notes page, but we skip them in the bundled
    # llms-full.txt (release history is noise for RAG / agent ingestion).
    bundle_skip_dirs = {"release-notes"}
    files = sorted(
        list(DOCS_DIR.rglob("*.mdx")) + list(DOCS_DIR.rglob("*.md")),
        key=lambda p: p.relative_to(DOCS_DIR).as_posix(),
    )
    if not files:
        raise SystemExit(f"no docs found under {DOCS_DIR}")

    parts: list[str] = [
        "# epydemix WebAPI — full documentation",
        "",
        "Concatenated from the docs site. See https://epydemix-webapi.vercel.app/docs"
        " for the rendered version with navigation.",
        "",
        "---",
        "",
    ]
    bundle_count = 0
    for path in files:
        rel = path.relative_to(DOCS_DIR).as_posix()
        cleaned = _clean(path.read_text(encoding="utf-8"))
        in_bundle_skip = any(part in bundle_skip_dirs for part in Path(rel).parts)

        # 1) Append into llms-full.txt (unless excluded).
        if not in_bundle_skip:
            parts.append(f"<!-- source: web/docs/{rel} -->")
            parts.append("")
            parts.append(cleaned)
            parts.append("---")
            parts.append("")
            bundle_count += 1

        # 2) Write a per-page mirror at /docs/<path>.md for every page,
        #    including the bundle-skipped ones, so the in-page widget works.
        per_page = _per_page_path(rel)
        per_page.parent.mkdir(parents=True, exist_ok=True)
        per_page.write_text(cleaned, encoding="utf-8")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(parts), encoding="utf-8")
    print(
        f"wrote {OUTPUT.relative_to(Path.cwd())} "
        f"({OUTPUT.stat().st_size:,} bytes from {bundle_count} files)"
    )
    print(
        f"wrote per-page mirrors under {PER_PAGE_DIR.relative_to(Path.cwd())}/ ({len(files)} files)"
    )


if __name__ == "__main__":
    main()
