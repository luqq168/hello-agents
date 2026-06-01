#!/usr/bin/env python3
"""Merge chapter PDFs into Chinese / English books with nested PDF outline bookmarks."""

from __future__ import annotations

import re
import shutil
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

try:
    from pypdf import PdfReader, PdfWriter
except ImportError:
    print("Missing dependency: pip install pypdf", file=sys.stderr)
    raise SystemExit(1) from None

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Missing dependency: pip install pymupdf", file=sys.stderr)
    raise SystemExit(1) from None

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"

OUTPUTS = {
    "zh": DOCS_DIR / "Hello-Agents-全书-中文.pdf",
    "en": DOCS_DIR / "Hello-Agents-全书-英文.pdf",
}

HEADING_RE = re.compile(r"^(#{2,3})\s+(.+)$")
SKIP_TITLES = frozenset({"目录", "Table of Contents"})
HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Heading:
    level: int  # 2 = ##, 3 = ###
    title: str


def chapter_num(path: Path) -> int:
    m = re.search(r"chapter(\d+)", str(path), re.I)
    return int(m.group(1)) if m else 0


def is_chinese_pdf(path: Path) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", path.name))


def find_chapter_pdfs(lang: str) -> list[Path]:
    pdfs: list[Path] = []
    for ch_dir in sorted(DOCS_DIR.glob("chapter*"), key=chapter_num):
        if not ch_dir.is_dir():
            continue
        for pdf in sorted(ch_dir.glob("*.pdf")):
            zh = is_chinese_pdf(pdf)
            if lang == "zh" and zh:
                pdfs.append(pdf)
            elif lang == "en" and not zh:
                pdfs.append(pdf)
    return sorted(pdfs, key=chapter_num)


def md_path_for_pdf(pdf_path: Path) -> Path:
    return pdf_path.with_suffix(".md")


def plain_title(raw: str) -> str:
    text = HTML_TAG_RE.sub("", raw).strip()
    text = re.sub(r"\s+#+\s*$", "", text).strip()
    return re.sub(r"\s+", " ", text)


def normalize_text(text: str) -> str:
    # Drop emoji / symbols that often differ between MD and PDF text extraction
    text = re.sub(
        r"[\U00010000-\U0010ffff"
        r"\u2600-\u27bf"
        r"\ufe0f"
        r"\u200d"
        r"]+",
        "",
        text,
    )
    return re.sub(r"\s+", "", text)


def extract_headings(md_path: Path) -> list[Heading]:
    if not md_path.is_file():
        warnings.warn(f"Markdown not found for {md_path.name}, skipping section bookmarks")
        return []

    headings: list[Heading] = []
    for line in md_path.read_text(encoding="utf-8").splitlines():
        m = HEADING_RE.match(line.strip())
        if not m:
            continue
        level = len(m.group(1))
        title = plain_title(m.group(2))
        if not title or title in SKIP_TITLES:
            continue
        headings.append(Heading(level=level, title=title))
    return headings


def _is_toc_page(doc: fitz.Document, pno: int, headings: list[Heading]) -> bool:
    """Heuristic: injected HTML TOC lists many section titles on one page."""
    page_norm = normalize_text(doc[pno].get_text())
    if "目录" in page_norm or "TableofContents" in page_norm.replace(" ", ""):
        hits = sum(
            1 for h in headings if normalize_text(h.title) in page_norm
        )
        if hits >= 3:
            return True
    return False


def _page_has_heading(doc: fitz.Document, pno: int, needle: str) -> bool:
    if not needle:
        return False
    page_norm = normalize_text(doc[pno].get_text())
    return needle in page_norm


def find_heading_pages(pdf_path: Path, headings: list[Heading]) -> list[int]:
    if not headings:
        return []

    doc = fitz.open(str(pdf_path))
    page_count = len(doc)
    pages: list[int] = []
    search_from = 0
    last_page = 0

    toc_pages = {pno for pno in range(page_count) if _is_toc_page(doc, pno, headings)}

    try:
        for heading in headings:
            needle = normalize_text(heading.title)
            found: int | None = None

            if needle:
                for pno in range(search_from, page_count):
                    if pno in toc_pages:
                        continue
                    if _page_has_heading(doc, pno, needle):
                        found = pno
                        break

            if found is None:
                prefix_m = re.match(r"^[\d.]+\s*", heading.title)
                if prefix_m:
                    prefix = normalize_text(prefix_m.group(0))
                    if prefix:
                        for pno in range(search_from, page_count):
                            if pno in toc_pages:
                                continue
                            if prefix in normalize_text(doc[pno].get_text()):
                                found = pno
                                break

            if found is None:
                found = last_page
                warnings.warn(
                    f"Heading not found in PDF, using fallback page: "
                    f"{pdf_path.name!r} -> {heading.title!r} (page {found + 1})"
                )

            pages.append(found)
            last_page = found
            search_from = found  # ### may share the same page as ##
    finally:
        doc.close()

    return pages


def count_outline_items(outline) -> int:
    if not outline:
        return 0
    n = 0
    for item in outline:
        if isinstance(item, list):
            n += count_outline_items(item)
        else:
            n += 1
    return n


def merge_with_nested_bookmarks(pdf_paths: list[Path], output_path: Path) -> tuple[int, int]:
    writer = PdfWriter()
    total_bookmarks = 0

    for pdf_path in pdf_paths:
        chapter_title = pdf_path.stem
        md_path = md_path_for_pdf(pdf_path)
        headings = extract_headings(md_path)
        heading_pages = find_heading_pages(pdf_path, headings)

        reader = PdfReader(str(pdf_path))
        chapter_start = len(writer.pages)
        writer.append(reader)
        n_pages = len(reader.pages)

        chapter_ref = writer.add_outline_item(chapter_title, chapter_start)
        total_bookmarks += 1

        parent_by_level: dict[int, object] = {1: chapter_ref}

        for heading, local_page in zip(headings, heading_pages, strict=False):
            global_page = chapter_start + local_page
            parent = parent_by_level.get(heading.level - 1, chapter_ref)
            ref = writer.add_outline_item(
                heading.title, global_page, parent=parent
            )
            parent_by_level[heading.level] = ref
            for deeper in list(parent_by_level):
                if deeper > heading.level:
                    del parent_by_level[deeper]
            total_bookmarks += 1

        sub_count = len(headings)
        print(
            f"  + {pdf_path.relative_to(DOCS_DIR)} ({n_pages} pages) "
            f"-> [{chapter_title}] + {sub_count} section(s)"
        )

    _write_pdf(writer, output_path)

    return len(writer.pages), total_bookmarks


def _write_pdf(writer: PdfWriter, output_path: Path) -> None:
    build_dir = DOCS_DIR / ".pdf-build"
    build_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = build_dir / f"{output_path.name}.tmp"

    with tmp_path.open("wb") as f:
        writer.write(f)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(tmp_path, output_path)
        print(f"  Saved {output_path.relative_to(REPO_ROOT)}")
    except PermissionError:
        fallback = build_dir / output_path.name
        shutil.copy2(tmp_path, fallback)
        print(
            f"  WARNING: cannot overwrite locked file "
            f"{output_path.relative_to(REPO_ROOT)}; "
            f"wrote {fallback.relative_to(REPO_ROOT)} instead",
            file=sys.stderr,
        )
    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> int:
    failed = 0
    for lang, out_path in OUTPUTS.items():
        label = "中文" if lang == "zh" else "English"
        pdfs = find_chapter_pdfs(lang)
        if not pdfs:
            print(f"No {label} PDFs found under docs/chapter*/", file=sys.stderr)
            failed += 1
            continue

        print(f"\nMerging {len(pdfs)} {label} chapter(s) -> {out_path.relative_to(REPO_ROOT)}")
        total_pages, bookmark_count = merge_with_nested_bookmarks(pdfs, out_path)
        size_kb = out_path.stat().st_size / 1024

        reader = PdfReader(str(out_path))
        outline_count = count_outline_items(reader.outline)
        print(
            f"Done: {total_pages} pages, {size_kb:.0f} KB, "
            f"bookmarks written: {bookmark_count}, outline items: {outline_count}"
        )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
