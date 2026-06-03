const path = require("path");
const markedKatex = require("marked-katex-extension");

module.exports = {
  stylesheet: [
    path.join(__dirname, "pdf-style.css"),
    path.join(__dirname, "..", "node_modules", "katex", "dist", "katex.min.css"),
  ],
  body_class: "markdown-body",
  marked_options: {
    gfm: true,
    breaks: false,
    headerIds: true,
    mangle: false,
  },
  marked_extensions: [
    markedKatex({
      throwOnError: false,
      nonStandard: true,
      strict: false,
    }),
  ],
  pdf_options: {
    format: "A4",
    printBackground: true,
    displayHeaderFooter: false,
    margin: {
      top: "20mm",
      bottom: "20mm",
      left: "18mm",
      right: "18mm",
    },
  },
  launch_options: {
    args: ["--font-render-hinting=medium", "--lang=zh-CN"],
  },
};
