#!/usr/bin/env python3
"""Download remote images referenced in docs/chapter*/*.md to docs/images/."""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = REPO_ROOT / "docs"
IMAGES_DIR = DOCS_DIR / "images"
MANIFEST_PATH = DOCS_DIR / ".pdf-build" / "image-manifest.json"

# Markdown images and HTML <img src="...">
URL_PATTERN = re.compile(
    r"https://raw\.githubusercontent\.com/[^)\s\"']+/docs/images/([^)\s\"']+)"
)


def find_chapter_mds() -> list[Path]:
    return sorted(DOCS_DIR.glob("chapter*/*.md"))


def collect_urls(files: list[Path]) -> set[str]:
    urls: set[str] = set()
    for md in files:
        text = md.read_text(encoding="utf-8")
        for match in URL_PATTERN.finditer(text):
            rel = match.group(1)
            base = match.group(0).split("/docs/images/")[0]
            urls.add(f"{base}/docs/images/{rel}")
    return urls


def url_to_local_path(url: str) -> Path:
    rel = url.split("/docs/images/", 1)[1]
    return IMAGES_DIR / rel.replace("/", "\\").replace("\\", "/")


def download(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        return True
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "hello-agents-pdf-build/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            dest.write_bytes(resp.read())
        return True
    except urllib.error.URLError as exc:
        print(f"FAIL {url}: {exc}", file=sys.stderr)
        return False


def main() -> int:
    files = find_chapter_mds()
    if not files:
        print("No chapter markdown files found.", file=sys.stderr)
        return 1

    urls = collect_urls(files)
    print(f"Found {len(urls)} unique image URL(s) in {len(files)} markdown file(s).")

    manifest: dict[str, str] = {}
    failed = 0
    for url in sorted(urls):
        dest = url_to_local_path(url)
        ok = download(url, dest)
        if ok:
            rel_from_docs = dest.relative_to(DOCS_DIR).as_posix()
            manifest[url] = rel_from_docs
            print(f"OK  {rel_from_docs}")
        else:
            failed += 1

    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Manifest written to {MANIFEST_PATH.relative_to(REPO_ROOT)}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
