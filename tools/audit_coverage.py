"""Audit empirique de la couverture python-docx vs features CSC détectées.

Pour chaque feature, on tente l'API publique de python-docx et on rapporte:
- API disponible (haut niveau ou OXML brut)
- Lecture: ce qu'on récupère
- Écriture/création: ce qui fonctionne ou échoue
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

from docx import Document
from docx.oxml.ns import qn

SAMPLE = Path(__file__).resolve().parent.parent / "csc_samples" / "Chapitre A - modele.docx"


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def try_feature(name: str, fn: Callable[[], Any]) -> None:
    print(f"\n--- {name} ---")
    try:
        result = fn()
        if result is not None:
            print(f"  → {result}")
    except Exception as exc:
        print(f"  ✗ {type(exc).__name__}: {exc}")


def feat_hyperlinks(doc) -> str:
    n_hyperlinks = 0
    samples = []
    for para in doc.paragraphs:
        if hasattr(para, "hyperlinks"):
            for h in para.hyperlinks:
                n_hyperlinks += 1
                if len(samples) < 3:
                    samples.append(f"{h.text!r} → {h.address!r}")
    info = f"lecture: {n_hyperlinks} hyperlinks via paragraph.hyperlinks. Échantillons: {samples}"
    # Écriture
    write_status = "écriture: "
    try:
        para = doc.paragraphs[0]
        if hasattr(para, "add_hyperlink"):
            write_status += "add_hyperlink disponible (API haut niveau)"
        else:
            write_status += "PAS de add_hyperlink — écriture nécessite XML manuel"
    except Exception as e:
        write_status += f"erreur: {e}"
    return info + " | " + write_status


def feat_bookmarks(doc) -> str:
    body = doc.element.body
    starts = body.findall(f".//{qn('w:bookmarkStart')}")
    ends = body.findall(f".//{qn('w:bookmarkEnd')}")
    samples = [s.get(qn("w:name")) for s in starts[:5]]
    api = "PAS d'API haut niveau (pas de Document.bookmarks)"
    if hasattr(doc, "bookmarks"):
        api = "Document.bookmarks existe"
    return (
        f"lecture XML: {len(starts)} starts, {len(ends)} ends. "
        f"Échantillons: {samples}. API: {api}"
    )


def feat_footnotes(doc) -> str:
    api_status = []
    for attr in ("footnotes", "add_footnote"):
        api_status.append(f"{attr}: {'OUI' if hasattr(doc, attr) else 'NON'}")
    # Vérif via XML
    try:
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        part = doc.part
        footnotes_parts = [r for r in part.rels.values() if r.reltype == RT.FOOTNOTES]
        if footnotes_parts:
            fn_part = footnotes_parts[0].target_part
            fn_xml = fn_part.element
            footnotes = fn_xml.findall(qn("w:footnote"))
            return (
                f"footnotes.xml présent ({len(footnotes)} footnotes XML). "
                f"API Document: {api_status}"
            )
    except Exception as e:
        return f"erreur accès XML: {e}. API Document: {api_status}"
    return f"footnotes.xml absent. API Document: {api_status}"


def feat_comments(doc) -> str:
    api = "Document.comments: " + ("OUI" if hasattr(doc, "comments") else "NON")
    add = "Document.add_comment: " + ("OUI" if hasattr(doc, "add_comment") else "NON")
    if hasattr(doc, "comments"):
        try:
            comments = list(doc.comments)
            api += f" ({len(comments)} comments lus)"
        except Exception as e:
            api += f" (lecture KO: {e})"
    return f"{api} | {add}"


def feat_track_changes(doc) -> str:
    body = doc.element.body
    ins = body.findall(f".//{qn('w:ins')}")
    dele = body.findall(f".//{qn('w:del')}")
    mvf = body.findall(f".//{qn('w:moveFrom')}")
    mvt = body.findall(f".//{qn('w:moveTo')}")
    api_status = (
        "Document.accept_revisions: " + ("OUI" if hasattr(doc, "accept_revisions") else "NON")
        + " | Document.reject_revisions: " + ("OUI" if hasattr(doc, "reject_revisions") else "NON")
        + " | Document.revisions: " + ("OUI" if hasattr(doc, "revisions") else "NON")
    )
    return (
        f"XML brut: {len(ins)} ins, {len(dele)} del, "
        f"{len(mvf)} moveFrom, {len(mvt)} moveTo. API: {api_status}"
    )


def feat_sdt(doc) -> str:
    body = doc.element.body
    sdt = body.findall(f".//{qn('w:sdt')}")
    api = "Document.content_controls: " + ("OUI" if hasattr(doc, "content_controls") else "NON")
    return f"XML: {len(sdt)} sdt elements. API: {api}"


def feat_toc(doc) -> str:
    body = doc.element.body
    fld_simple = body.findall(f".//{qn('w:fldSimple')}")
    fld_char = body.findall(f".//{qn('w:fldChar')}")
    instr = body.findall(f".//{qn('w:instrText')}")
    toc_instr = [it.text.strip() for it in instr if it.text and "TOC" in it.text.upper()]
    api = "Document.update_fields / Document.toc: NON (jamais exposé)"
    return (
        f"XML: {len(fld_simple)} fldSimple, {len(fld_char)} fldChar, "
        f"{len(instr)} instrText. TOC instructions: {toc_instr}. {api}"
    )


def feat_numbering(doc) -> str:
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    try:
        numbering_parts = [r for r in doc.part.rels.values() if r.reltype == RT.NUMBERING]
        if not numbering_parts:
            return "Pas de numbering.xml"
        npart = numbering_parts[0].target_part
        nxml = npart.element
        abs_nums = nxml.findall(qn("w:abstractNum"))
        nums = nxml.findall(qn("w:num"))
        api = "doc.part.numbering_part: " + (
            "OUI" if hasattr(doc.part, "numbering_part") else "NON"
        )
        return (
            f"numbering.xml: {len(abs_nums)} abstractNum, {len(nums)} num instances. "
            f"API: {api}"
        )
    except Exception as e:
        return f"erreur: {e}"


def feat_images(doc) -> str:
    body = doc.element.body
    blips = body.findall(f".//{qn('a:blip')}")
    drawings = body.findall(f".//{qn('w:drawing')}")
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    image_parts = [r for r in doc.part.rels.values() if r.reltype == RT.IMAGE]
    formats = {}
    for r in image_parts:
        ct = r.target_part.content_type
        formats[ct] = formats.get(ct, 0) + 1
    return f"XML: {len(drawings)} drawings, {len(blips)} blips. Parts: {formats}"


def feat_sections(doc) -> str:
    info = []
    for i, sec in enumerate(doc.sections):
        h_attrs = ("header", "first_page_header", "even_page_header")
        f_attrs = ("footer", "first_page_footer", "even_page_footer")
        has_h = {a: not getattr(sec, a).is_linked_to_previous for a in h_attrs if hasattr(sec, a)}
        has_f = {a: not getattr(sec, a).is_linked_to_previous for a in f_attrs if hasattr(sec, a)}
        info.append(f"sec{i}: H={has_h} F={has_f} orient={sec.orientation}")
    return f"{len(doc.sections)} sections: " + " ; ".join(info)


def feat_custom_xml(doc) -> str:
    # docProps/custom.xml
    try:
        for r in doc.part.package.rels.values():
            if "custom-properties" in (r.reltype or ""):
                cust_part = r.target_part
                from lxml import etree
                root = etree.fromstring(cust_part.blob)
                props = root.findall(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/"
                    "custom-properties}property"
                )
                names = [p.get("name") for p in props[:3]]
                api = "OUI" if hasattr(doc, "custom_properties") else "NON"
                return (
                    f"docProps/custom.xml: {len(props)} props. "
                    f"Échantillons: {names}. API doc.custom_properties: {api}"
                )
    except Exception as e:
        return f"erreur accès custom props: {e}"
    return "Pas de custom XML détecté"


def feat_tabs_styles(doc) -> str:
    # Vérifier API pour tab stops et création de styles
    styles_api = hasattr(doc, "styles")
    n_styles = len(doc.styles) if styles_api else 0
    custom_styles = (
        [s.name for s in doc.styles if "CSC" in s.name or "Puces" in s.name][:5]
        if styles_api
        else []
    )
    return (
        f"doc.styles: {n_styles} styles totaux. Styles CSC détectés: {custom_styles}. "
        "Tab stops API: para.paragraph_format.tab_stops (présent)"
    )


def main() -> int:
    if not SAMPLE.exists():
        print(f"Sample introuvable: {SAMPLE}", file=sys.stderr)
        return 1
    print(f"Audit sur: {SAMPLE.name}")
    doc = Document(str(SAMPLE))

    features = [
        ("Hyperlinks", lambda: feat_hyperlinks(doc)),
        ("Bookmarks", lambda: feat_bookmarks(doc)),
        ("Footnotes", lambda: feat_footnotes(doc)),
        ("Comments (v1.2)", lambda: feat_comments(doc)),
        ("Track changes", lambda: feat_track_changes(doc)),
        ("Content controls (sdt)", lambda: feat_sdt(doc)),
        ("TOC / champs", lambda: feat_toc(doc)),
        ("Numbering", lambda: feat_numbering(doc)),
        ("Images & formats", lambda: feat_images(doc)),
        ("Sections multi-headers/footers", lambda: feat_sections(doc)),
        ("Custom XML / docProps", lambda: feat_custom_xml(doc)),
        ("Tab stops & styles custom", lambda: feat_tabs_styles(doc)),
    ]

    for name, fn in features:
        try_feature(name, fn)

    return 0


if __name__ == "__main__":
    sys.exit(main())
