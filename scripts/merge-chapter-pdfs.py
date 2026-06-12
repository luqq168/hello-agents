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
    from pypdf.generic import Fit
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

PREFACE_PDFS = {
    "zh": DOCS_DIR / "前言.pdf",
    "en": DOCS_DIR / "Preface.pdf",
}

HEADING_RE = re.compile(r"^(#{2,3})\s+(.+)$")
# Only section headings like "9.2.3 Title" or "16.4.1 Title" (not "📝 项目简介")
NUMBERED_TITLE_RE = re.compile(r"^\d+(?:\.\d+)+\s+\S")
NUMBERED_LINE_RE = re.compile(r"^\d+(?:\.\d+)+\s+")
TRAILING_BOOKMARK_TITLES = frozenset(
    {"习题", "参考文献", "Exercises", "References"}
)
SKIP_TITLES = frozenset({"目录", "Table of Contents"})
HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Heading:
    level: int  # 2 = ##, 3 = ###
    title: str
    section_id: str  # e.g. "9.2.3"


@dataclass(frozen=True)
class HeadingPosition:
    """Bookmark target: page index (0-based) and optional vertical scroll (PDF /FitH)."""

    page: int
    fit: Fit


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


def find_book_pdfs(lang: str) -> list[Path]:
    pdfs: list[Path] = []
    preface = PREFACE_PDFS.get(lang)
    if preface and preface.is_file():
        pdfs.append(preface)
    pdfs.extend(find_chapter_pdfs(lang))
    return pdfs


def md_path_for_pdf(pdf_path: Path) -> Path:
    return pdf_path.with_suffix(".md")


def plain_title(raw: str) -> str:
    text = HTML_TAG_RE.sub("", raw).strip()
    text = re.sub(r"\s+#+\s*$", "", text).strip()
    return re.sub(r"\s+", " ", text)


def parse_section_id(title: str) -> str | None:
    title = title.strip()
    m = re.match(r"^(\d+(?:\.\d+)+)", title)
    if m:
        return m.group(1)
    if title in TRAILING_BOOKMARK_TITLES:
        return title
    return None


def is_numbered_section_title(title: str) -> bool:
    return bool(NUMBERED_TITLE_RE.match(title.strip()))


def is_trailing_bookmark_title(title: str) -> bool:
    return title.strip() in TRAILING_BOOKMARK_TITLES


def should_bookmark_heading(title: str) -> bool:
    return is_numbered_section_title(title) or is_trailing_bookmark_title(title)


def normalize_text(text: str) -> str:
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
        if not should_bookmark_heading(title):
            continue
        section_id = parse_section_id(title)
        if not section_id:
            continue
        headings.append(Heading(level=level, title=title, section_id=section_id))
    return headings


def _page_lines(doc: fitz.Document, pno: int) -> list[str]:
    return [ln.strip() for ln in doc[pno].get_text().splitlines() if ln.strip()]


def _is_toc_page(doc: fitz.Document, pno: int) -> bool:
    """
    Detect in-document TOC pages (not body text containing substring '目录').
    """
    lines = _page_lines(doc, pno)
    if not lines:
        return False

    # Explicit "目录" / "Table of Contents" title near top
    for ln in lines[:6]:
        if ln in SKIP_TITLES or ln.lower() == "table of contents":
            numbered = sum(1 for x in lines if NUMBERED_LINE_RE.match(x))
            return numbered >= 5

    # TOC continuation: mostly short lines that look like section entries
    if pno <= 4:
        numbered = [ln for ln in lines if NUMBERED_LINE_RE.match(ln)]
        if len(numbered) >= 8 and len(numbered) >= len(lines) * 0.45:
            long_body = sum(1 for ln in lines if len(ln) > 60)
            return long_body <= 2

    # Page lists many section titles (injected PDF TOC) without "目录" header
    if pno <= 2:
        hits = sum(1 for ln in lines if NUMBERED_LINE_RE.match(ln))
        if hits >= 6 and hits / max(len(lines), 1) >= 0.35:
            long_body = sum(1 for ln in lines if len(ln) > 80)
            if long_body <= 1:
                return True

    return False


def _toc_pages(doc: fitz.Document) -> set[int]:
    return {pno for pno in range(len(doc)) if _is_toc_page(doc, pno)}


def _rect_to_fit(page: fitz.Page, rect: fitz.Rect) -> Fit:
    pdf_top = float(page.rect.height - rect.y0)
    return Fit.fit_horizontally(top=pdf_top)


def _section_id_at_line_start(line_norm: str, id_norm: str) -> bool:
    """True if line starts with section id but not a deeper subsection (1.4 vs 1.4.1)."""
    if not line_norm.startswith(id_norm):
        return False
    rest = line_norm[len(id_norm) :]
    if not rest:
        return True
    return not rest.startswith(".")
    # After normalize, "1.4.1" -> rest after "1.4" is ".1..."


def _line_matches_heading(line_text: str, heading: Heading) -> bool:
    line_norm = normalize_text(line_text)
    title_norm = normalize_text(heading.title)

    if line_norm == title_norm:
        return True

    if heading.section_id in TRAILING_BOOKMARK_TITLES:
        return line_norm == normalize_text(heading.section_id)

    id_norm = normalize_text(heading.section_id)
    if not _section_id_at_line_start(line_norm, id_norm):
        return False
    return line_norm.startswith(title_norm)


def _pick_heading_rect(page: fitz.Page, heading: Heading) -> fitz.Rect | None:
    """Pick topmost heading line on a page (ignore TOC duplicates and inline mentions)."""
    best: fitz.Rect | None = None
    best_y = float("inf")

    data = page.get_text("dict")
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            line_text = "".join(span.get("text", "") for span in line.get("spans", []))
            if not _line_matches_heading(line_text, heading):
                continue
            x0, y0, x1, y1 = line["bbox"]
            if y0 < best_y:
                best_y = y0
                best = fitz.Rect(x0, y0, x1, y1)

    if best is not None:
        return best

    # Fallback: full-title search only when it maps to a single heading line
    rects = page.search_for(heading.title)
    if len(rects) == 1:
        return rects[0]
    return None


def find_heading_positions(
    pdf_path: Path, headings: list[Heading]
) -> list[HeadingPosition]:
    if not headings:
        return []

    doc = fitz.open(str(pdf_path))
    page_count = len(doc)
    positions: list[HeadingPosition] = []
    search_from = 0
    last = HeadingPosition(page=0, fit=Fit.fit_horizontally(top=None))

    toc_pages = _toc_pages(doc)

    try:
        for heading in headings:
            found_page: int | None = None
            found_rect: fitz.Rect | None = None

            for pno in range(search_from, page_count):
                if pno in toc_pages:
                    continue
                page = doc[pno]
                rect = _pick_heading_rect(page, heading)
                if rect is not None:
                    found_page = pno
                    found_rect = rect
                    break

            if found_page is None:
                found_page = last.page
                page = doc[found_page]
                found_rect = _pick_heading_rect(page, heading) or fitz.Rect(
                    72, 72, 200, 90
                )
                warnings.warn(
                    f"Heading position fallback: {pdf_path.name!r} -> "
                    f"{heading.title!r} (page {found_page + 1})"
                )

            page = doc[found_page]
            fit = (
                _rect_to_fit(page, found_rect)
                if found_rect is not None
                else Fit.fit_horizontally(top=None)
            )

            pos = HeadingPosition(page=found_page, fit=fit)
            positions.append(pos)
            last = pos
            search_from = found_page
    finally:
        doc.close()

    return positions


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
        heading_positions = find_heading_positions(pdf_path, headings)

        reader = PdfReader(str(pdf_path))
        chapter_start = len(writer.pages)
        writer.append(reader)
        n_pages = len(reader.pages)

        chapter_ref = writer.add_outline_item(
            chapter_title, chapter_start, fit=Fit.fit_horizontally(top=None)
        )
        total_bookmarks += 1

        parent_by_level: dict[int, object] = {1: chapter_ref}

        for heading, pos in zip(headings, heading_positions, strict=False):
            global_page = chapter_start + pos.page
            parent = parent_by_level.get(heading.level - 1, chapter_ref)
            ref = writer.add_outline_item(
                heading.title,
                global_page,
                parent=parent,
                fit=pos.fit,
            )
            parent_by_level[heading.level] = ref
            for deeper in list(parent_by_level):
                if deeper > heading.level:
                    del parent_by_level[deeper]
            total_bookmarks += 1

        sub_count = len(headings)
        print(
            f"  + {pdf_path.relative_to(DOCS_DIR)} ({n_pages} pages) "
            f"-> [{chapter_title}] + {sub_count} numbered section(s)"
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
        try:
            saved = output_path.relative_to(REPO_ROOT)
        except ValueError:
            saved = output_path
        print(f"  Saved {saved}")
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
        pdfs = find_book_pdfs(lang)
        if not pdfs:
            print(
                f"No {label} PDFs found (docs/前言.pdf or Preface.pdf, or docs/chapter*/)",
                file=sys.stderr,
            )
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
