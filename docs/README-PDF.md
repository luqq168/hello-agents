# 章节 Markdown 转 PDF

将 `docs/前言.md`、`docs/Preface.md` 以及 `docs/chapter1` … `docs/chapter16` 下的 Markdown 转为 PDF（版式接近 Markdown 预览，含文内可点击目录）。

## 环境要求

- Node.js 18+
- Python 3（下载图片、合并 PDF 书签）
- `pip install -r requirements-docs.txt`（合并全书时需要 `pypdf`、`pymupdf`）

## 一键构建

在仓库根目录执行：

```bash
npm install
npm run docs:pdf:all
```

分步执行：

```bash
npm run docs:images   # 下载 GitHub 远程图片到 docs/images/
npm run docs:pdf      # 生成各章 PDF（与 .md 同目录）
npm run docs:pdf:merge   # 合并为中/英两本全书 PDF（章→节→小节嵌套书签）
npm run docs:pdf:full    # 下载图片 + 生成各章 + 合并全书
```

仅构建某一章（例如第二章）：

```bash
npm run docs:pdf:chapter2
# 或
node docs/build-pdf.mjs chapter2
```

## 输出说明

- PDF 路径：`docs/前言.pdf`、`docs/Preface.pdf`、`docs/chapterN/<章节名>.pdf`
- 合并全书（中/英分册，左侧书签：**前言** / **Preface** → **章** → 带序号小节（如 `9.2.3`、`16.4.1`）→ 子小节；每章末尾另含 **习题**、**参考文献**（英文为 Exercises / References，若该章 Markdown 有对应标题）；不含代码示例内的 `## 项目简介` 等无序号标题）：
  - `docs/Hello-Agents-全书-中文.pdf`
  - `docs/Hello-Agents-全书-英文.pdf`
- 构建缓存：`docs/.pdf-build/`（staging 与图片 manifest，可删除后重建）
- 图片缓存：`docs/images/`（由 `scripts/download-doc-images.py` 下载）

## 特性

- 使用 [md-to-pdf](https://github.com/simonhaenisch/md-to-pdf)（Chromium 渲染），兼容文内 HTML（`<div>`、`<img>` 等）
- 使用 [KaTeX](https://katex.org/)（`marked-katex-extension`，与 Docsify 站点一致）渲染 `$...$` / `$$...$$` 公式
- 文首插入 **目录** 块，条目可点击跳转到对应标题
- 远程图片先本地化到 `docs/images/`，PDF 中以站点根路径 `/images/...` 加载（避免 staging 目录导致图片 404）

## CI

推送相关路径变更时，GitHub Actions 工作流 `.github/workflows/docs-pdf.yml` 会构建 PDF 并上传为 artifact `chapter-pdfs`。
