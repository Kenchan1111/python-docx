"""Dump paragraphs of a CSC chapter to JSONL for human annotation.

Pipeline:
1. Open the .docx
2. accept_all_revisions() to get a clean text baseline
3. Emit one JSONL line per paragraph with index, style, runs formatting, text
4. Also emit a compact "headings only" view (alt path)

Usage:
    python tools/dump_paragraphs.py csc_samples/"Chapitre A - modele.docx"
    python tools/dump_paragraphs.py --headings csc_samples/"Chapitre A - modele.docx"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.revisions import accept_all_revisions


def run_formatting(run) -> dict:
    """Return a dict of inline formatting cues that may signal questions/comments."""
    f = {}
    if run.bold:
        f["b"] = True
    if run.italic:
        f["i"] = True
    if run.underline:
        f["u"] = True
    if getattr(run.font, "highlight_color", None):
        f["highlight"] = str(run.font.highlight_color)
    color = getattr(run.font.color, "rgb", None) if run.font.color is not None else None
    if color:
        f["color"] = str(color)
    return f


def paragraph_record(idx: int, para) -> dict:
    """Build a JSON-serialisable record describing one paragraph."""
    style_name = para.style.name if para.style is not None else None
    # numbering level if any
    p = para._p
    num_pr = p.find(qn("w:pPr"))
    list_lvl = None
    list_id = None
    if num_pr is not None:
        ilvl = num_pr.find(f".//{qn('w:numPr')}/{qn('w:ilvl')}")
        numid = num_pr.find(f".//{qn('w:numPr')}/{qn('w:numId')}")
        if ilvl is not None:
            list_lvl = ilvl.get(qn("w:val"))
        if numid is not None:
            list_id = numid.get(qn("w:val"))

    # Inline formatting per run — keep only paragraphs where it matters
    run_fmts = []
    for r in para.runs:
        fm = run_formatting(r)
        if fm:
            run_fmts.append({"text": (r.text or "")[:60], **fm})

    return {
        "idx": idx,
        "style": style_name,
        "list_id": list_id,
        "list_lvl": list_lvl,
        "text": para.text,
        "run_fmt": run_fmts,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docx", type=Path, help="Path to the .docx file")
    ap.add_argument("--headings", action="store_true", help="Emit only Heading* paragraphs")
    ap.add_argument(
        "--keep-empty",
        action="store_true",
        help="Keep empty/whitespace-only paragraphs (default: drop)",
    )
    ap.add_argument(
        "--no-accept",
        action="store_true",
        help="Skip accept_all_revisions (analyse raw source)",
    )
    args = ap.parse_args(argv)

    if not args.docx.exists():
        print(f"File not found: {args.docx}", file=sys.stderr)
        return 1

    doc = Document(str(args.docx))
    if not args.no_accept:
        n = accept_all_revisions(doc)
        print(f"# accepted {n} revisions", file=sys.stderr)

    for idx, para in enumerate(doc.paragraphs):
        rec = paragraph_record(idx, para)
        if not args.keep_empty and not rec["text"].strip():
            continue
        if args.headings:
            style = rec["style"] or ""
            if not (style.startswith("Heading") or "Titre" in style or style in ("Title",)):
                continue
        print(json.dumps(rec, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
