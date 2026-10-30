# -*- coding: utf-8 -*-
"""Convert the skill's Markdown reports to Word (.docx) on the Desktop."""

from __future__ import annotations

import re
import time
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

DESKTOP = Path.home() / "Desktop"
CN = "宋体"
HEI = "微软雅黑"


def _set_run(run, size=10.5, bold=False, cn=CN, color=None):
    run.font.name = "Times New Roman"
    run.font.size = Pt(size)
    run.bold = bold
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), cn)
    if color:
        run.font.color.rgb = RGBColor(*color)


def _add_table(doc, rows):
    if not rows:
        return
    cols = max(len(r) for r in rows)
    t = doc.add_table(rows=0, cols=cols)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, row in enumerate(rows):
        cells = t.add_row().cells
        for j in range(cols):
            text = row[j] if j < len(row) else ""
            cells[j].text = ""
            p = cells[j].paragraphs[0]
            p.paragraph_format.line_spacing = 1.1
            p.alignment = (
                WD_ALIGN_PARAGRAPH.CENTER if i == 0 else WD_ALIGN_PARAGRAPH.LEFT
            )
            r = p.add_run(text)
            _set_run(r, 8.5, bold=(i == 0), cn=HEI if i == 0 else CN)
            if i == 0:
                from docx.oxml import OxmlElement

                shd = OxmlElement("w:shd")
                shd.set(qn("w:val"), "clear")
                shd.set(qn("w:color"), "auto")
                shd.set(qn("w:fill"), "DCE6F1")
                cells[j]._tc.get_or_add_tcPr().append(shd)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def md_to_docx(md_text: str, out_path: Path, title: str | None = None) -> Path:
    doc = Document()
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.2)
    sec.bottom_margin = Cm(2.2)
    sec.left_margin = Cm(2.4)
    sec.right_margin = Cm(2.4)
    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(10.5)
    style.element.rPr.rFonts.set(qn("w:eastAsia"), CN)
    style.paragraph_format.line_spacing = 1.4

    lines = md_text.replace("\r\n", "\n").split("\n")
    i = 0
    table_rows = []
    while i < len(lines):
        line = lines[i].rstrip()
        if line.startswith("|") and "|" in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                i += 1
                continue
            table_rows.append(cells)
            i += 1
            continue
        if table_rows:
            _add_table(doc, table_rows)
            table_rows = []

        if not line.strip():
            i += 1
            continue
        if line.startswith("# "):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(8)
            _set_run(p.add_run(line[2:].strip()), 17, True, HEI, (31, 78, 121))
        elif line.startswith("## "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(12)
            p.paragraph_format.space_after = Pt(4)
            _set_run(p.add_run(line[3:].strip()), 13, True, HEI, (31, 78, 121))
        elif line.startswith("### "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(8)
            p.paragraph_format.space_after = Pt(2)
            _set_run(p.add_run(line[4:].strip()), 11.5, True, HEI)
        elif line.startswith("> "):
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Cm(0.4)
            _set_run(p.add_run(line[2:].strip()), 9, False, CN, (90, 90, 90))
        elif re.match(r"^\s*[-*]\s+", line):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.line_spacing = 1.35
            _set_run(p.add_run(re.sub(r"^\s*[-*]\s+", "", line)), 10.5)
        elif re.match(r"^\s*\d+\.\s+", line):
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.line_spacing = 1.35
            _set_run(p.add_run(re.sub(r"^\s*\d+\.\s+", "", line)), 10.5)
        else:
            p = doc.add_paragraph()
            p.paragraph_format.first_line_indent = Pt(21)
            _set_run(p.add_run(line.strip()), 10.5)
        i += 1
    if table_rows:
        _add_table(doc, table_rows)

    doc.core_properties.title = title or out_path.stem
    doc.core_properties.author = "A股市场情报 SKILL"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path


def save_to_desktop(md_path: Path, name: str | None = None) -> Path:
    text = md_path.read_text(encoding="utf-8")
    out = DESKTOP / (name or (md_path.stem + ".docx"))
    try:
        return md_to_docx(text, out, title=md_path.stem)
    except PermissionError:
        # The existing Word file is open; do not overwrite it.
        out = DESKTOP / f"{out.stem}_{time.strftime('%H%M%S')}.docx"
        return md_to_docx(text, out, title=md_path.stem)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("markdown")
    ap.add_argument("--name", default=None)
    args = ap.parse_args()
    print(save_to_desktop(Path(args.markdown), args.name))
