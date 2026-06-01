/**
 * Merge chapter PDFs (Chinese / English) with bookmarks. Delegates to Python pypdf.
 */

import { spawnSync } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const script = path.resolve(__dirname, "..", "scripts", "merge-chapter-pdfs.py");

const result = spawnSync("python", [script], { stdio: "inherit" });
process.exit(result.status ?? 1);
