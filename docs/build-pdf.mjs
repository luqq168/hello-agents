/**
 * Build PDFs for docs/chapterNN/*.md using md-to-pdf.
 * - Localizes remote images via manifest from scripts/download-doc-images.py
 * - Injects clickable in-document TOC
 * - Outputs PDF next to each source .md
 */

import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createRequire } from "module";
import { mdToPdf } from "md-to-pdf";

const require = createRequire(import.meta.url);
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");
const DOCS_DIR = path.join(REPO_ROOT, "docs");
const MANIFEST_PATH = path.join(DOCS_DIR, ".pdf-build", "image-manifest.json");
const STAGING_DIR = path.join(DOCS_DIR, ".pdf-build", "staging");
const CONFIG = require("./md-to-pdf.config.cjs");

const args = process.argv.slice(2);
const onlyFilter = args.find((a) => !a.startsWith("--"));
const dryRun = args.includes("--dry-run");

function findChapterMds() {
  const chapters = fs
    .readdirSync(DOCS_DIR, { withFileTypes: true })
    .filter((d) => d.isDirectory() && /^chapter\d+$/i.test(d.name))
    .map((d) => d.name)
    .sort((a, b) => {
      const na = parseInt(a.replace(/\D/g, ""), 10);
      const nb = parseInt(b.replace(/\D/g, ""), 10);
      return na - nb;
    });

  const files = [];
  for (const ch of chapters) {
    const dir = path.join(DOCS_DIR, ch);
    for (const name of fs.readdirSync(dir)) {
      if (name.endsWith(".md")) {
        files.push(path.join(dir, name));
      }
    }
  }
  return onlyFilter
    ? files.filter((f) =>
        f.replace(/\\/g, "/").includes(onlyFilter.replace(/\\/g, "/"))
      )
    : files;
}

function loadManifest() {
  if (!fs.existsSync(MANIFEST_PATH)) {
    console.error(
      `Image manifest not found: ${MANIFEST_PATH}\nRun: python scripts/download-doc-images.py`
    );
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf8"));
}

/** GitHub-style heading anchor (approximate, for TOC links). */
function slugify(text) {
  return text
    .replace(/<[^>]+>/g, "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^\w\u4e00-\u9fff\-]/g, "")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

function extractHeadings(markdown) {
  const headings = [];
  const lines = markdown.split(/\r?\n/);
  for (const line of lines) {
    const m = /^(#{1,4})\s+(.+)$/.exec(line.trim());
    if (!m) continue;
    const level = m[1].length;
    const title = m[2].replace(/\s+#+\s*$/, "").trim();
    if (level === 1) continue;
    headings.push({ level, title, id: slugify(title) });
  }
  return headings;
}

function buildTocBlock(headings, isChinese) {
  if (headings.length === 0) return "";
  const title = isChinese ? "目录" : "Table of Contents";
  const items = headings
    .map((h) => {
      const cls =
        h.level === 3 ? "toc-h3" : h.level === 4 ? "toc-h4" : "toc-h2";
      return `<li class="${cls}"><a href="#${h.id}">${h.title.replace(/</g, "&lt;")}</a></li>`;
    })
    .join("\n");

  return `
<div class="pdf-toc">

## ${title}

<ul>
${items}
</ul>

</div>

`;
}

/**
 * Image paths must be absolute from the HTTP server root (basedir=docs/).
 * md-to-pdf serves basedir and loads HTML via setContent with a deep staging URL;
 * relative "images/..." would resolve under .pdf-build/staging/... and 404.
 */
function localizeImages(content, manifest) {
  let out = content;
  for (const [url, relFromDocs] of Object.entries(manifest)) {
    const webPath = `/${relFromDocs.replace(/\\/g, "/")}`;
    out = out.split(url).join(webPath);
  }
  return out;
}

function isChineseChapter(filePath) {
  return /[\u4e00-\u9fff]/.test(path.basename(filePath));
}

function prepareMarkdown(mdPath, manifest) {
  const raw = fs.readFileSync(mdPath, "utf8");
  const localized = localizeImages(raw, manifest);
  const headings = extractHeadings(localized);
  const toc = buildTocBlock(headings, isChineseChapter(mdPath));

  const lines = localized.split(/\r?\n/);
  let insertAt = 0;
  for (let i = 0; i < lines.length; i++) {
    if (/^\s*#\s+/.test(lines[i])) {
      insertAt = i + 1;
      break;
    }
  }
  const before = lines.slice(0, insertAt).join("\n");
  const after = lines.slice(insertAt).join("\n");
  return `${before}\n${toc}${after}`;
}

async function buildOne(mdPath, manifest) {
  const pdfPath = mdPath.replace(/\.md$/i, ".pdf");
  const content = prepareMarkdown(mdPath, manifest);

  // Optional staging copy for debugging
  const stagingPath = path.join(
    STAGING_DIR,
    path.relative(DOCS_DIR, mdPath)
  );
  fs.mkdirSync(path.dirname(stagingPath), { recursive: true });
  fs.writeFileSync(stagingPath, content, "utf8");

  if (dryRun) {
    console.log(
      `[dry-run] ${path.relative(REPO_ROOT, mdPath)} -> ${path.relative(REPO_ROOT, pdfPath)}`
    );
    return;
  }

  console.log(`Building ${path.relative(REPO_ROOT, mdPath)} ...`);
  // Use { content } so the page base URL is http://localhost:<port>/ (not staging path)
  await mdToPdf(
    { content },
    {
      dest: pdfPath,
      basedir: DOCS_DIR,
      ...CONFIG,
    }
  );

  const stat = fs.statSync(pdfPath);
  console.log(
    `  -> ${path.relative(REPO_ROOT, pdfPath)} (${(stat.size / 1024).toFixed(0)} KB)`
  );
}

async function main() {
  const manifest = loadManifest();
  const files = findChapterMds();
  if (files.length === 0) {
    console.error("No markdown files matched.");
    process.exit(1);
  }
  console.log(`Converting ${files.length} file(s)...`);

  let failed = 0;
  for (const md of files) {
    try {
      await buildOne(md, manifest);
    } catch (err) {
      failed++;
      console.error(`ERROR ${md}:`, err.message || err);
    }
  }

  if (failed) {
    console.error(`\n${failed} file(s) failed.`);
    process.exit(1);
  }
  console.log("\nDone.");
}

main();
