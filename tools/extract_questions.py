"""Extraction heuristique de la typologie CSC Qualiroutes.

Classifie chaque paragraphe d'un .docx en types (SECTION_TITLE, META_COMMENT,
LEGAL_REMINDER, CSC_CONTENT, INLINE_PLACEHOLDER, CHOICE_HEADER, etc.) selon
les règles établies dans annotations/chapitre_A.yaml et chapitre_G.yaml.

Pipeline :
  1. accept_all_revisions() (les templates Qualiroutes ont des révisions en attente)
  2. Passe 1 : classifier chaque paragraphe individuellement (rules engine)
  3. Passe 2 : regrouper consécutifs (GROUPED_LEGAL_REMINDER, CONDITIONAL_BLOCK,
              CSC_CONTENT_TO_INSERT, EXAMPLE_BLOCK)
  4. Émettre JSON Lines

Usage :
  python tools/extract_questions.py csc_samples/"Chapitre A - modele.docx"
  python tools/extract_questions.py csc_samples/"Chapitre G - modele.docx" -o /tmp/G.jsonl
"""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from docx import Document
from docx.revisions import accept_all_revisions


# =====================================================================
# Style aliases (Ch.A vs Ch.G — plus extensions Heading par défaut)
# =====================================================================

HEADING_STYLES = {
    "CSC Titre 1",
    "CSC Titre 2",
    "CSC Titre 3",
    "Heading 1",
    "Heading 2",
    "Heading 3",
    "Heading 4",
    "Heading 5",
    "Titre 1",
    "Titre 2",
    "Titre 3",
    "En-tête de table des matières",
}

LIST_STYLES = {
    "Liste à puces",
    "Liste à puces 2",
    "retrait puce 1",
    "Paragraphe de liste",
    "Puces 1",
    "Puces 2",
    "Retrait corps de texte 2",
    "Retrait corps de texte 3",
}

BODY_ALT_STYLES = {
    "Body Text",
    "Body Text Indent",
    "Body Text 3",
    "Corps de texte 3",
    "Sans interligne",
    "Sans Interligne",
}

# Styles "alt" qui ont sémantique de META_COMMENT par défaut quand sans formatage
META_BIAS_STYLES = {"Corps de texte 3", "Body Text 3"}


# =====================================================================
# Incipits sémantiques pour désambiguïsation
# =====================================================================

META_INCIPITS = [
    r"^Indiquer\b",
    r"^Préciser\b",
    r"^Spécifier\b",
    r"^Mentionner\b",
    r"^Définir\b",
    r"^Enumérer\b",
    r"^Énumérer\b",
    r"^Supprimer\b",
    r"^Ajouter\b",
    r"^Selon l['']hypothèse",
    r"^Selon le cas",
    r"^Le cas échéant",
    r"^Pour les ",
    r"^Pour le réseau",
    r"^Pour le chantier",
    r"^Pour les chantiers",
    r"^Pour mémoire",
    r"^Si .{1,80}, ",          # Si <condition>, <action>
    r"^Si on désigne",
    r"^En cas de ",
    r"^En fonction du ",
    r"^Dans le cas où",
    r"^Au cas où",
    r"^A défaut\b",
    r"^Eventuellement\b",
    r"^Éventuellement\b",
    r"^S['']il échet",
    r"^Outre les ",
    r"^adapter le canevas",
    r"^Choisir ",
    r"^Vérifier ",        # contexte annexe checklist
]

LEGAL_REMINDER_INCIPITS = [
    r"^Il est rappelé",
    r"^En règle générale",
    r"^L['']attention (des soumissionnaires|est attirée)",
    r"^La durée totale",
    r"^Ces (exigences|indications|dispositions)",
    r"^Pour mémoire",
    r"^A titre d['']exemple",
    r"^L['']emploi de ",
    r"^Les enrobés ",
    r"^Le CP\d",          # spécifique Ch.G technique
]

EXAMPLE_HEADER_INCIPITS = [
    r"^Exemple\s*:",
    r"^Exemples\b",
    r"^A titre d['']exemple",
]

NOTA_BENE_INCIPITS = [r"^NB\s*:", r"^N\.B\.", r"^Note\s+relative\b"]

DOCUMENT_NOTE_INCIPITS = [r"^Note\s*:", r"^NB\s*:"]

PLACEHOLDER_MARKERS = [
    "…",
    "...",
    "(à compléter)",
    "(à définir)",
    "(à décrire)",
    "(à lister)",
    "A décrire",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


# =====================================================================
# Paragraph signal extraction
# =====================================================================

@dataclass
class ParaSignal:
    idx: int
    style: str | None
    text: str
    has_bold: bool = False
    has_italic: bool = False
    has_underline: bool = False
    has_color: bool = False
    has_highlight: bool = False
    starts_with_dash: bool = False
    starts_with_arrow: bool = False
    starts_with_letter_paren: bool = False  # a) b) c)
    starts_with_digit_paren: bool = False   # 1) 2)
    starts_with_bullet: bool = False        # •
    is_only_dash: bool = False
    is_only_ou: bool = False
    is_only_letter_number: bool = False
    contains_placeholder: bool = False


def signal_from_para(idx: int, para) -> ParaSignal:
    style = para.style.name if para.style is not None else None
    text = para.text
    sig = ParaSignal(idx=idx, style=style, text=text)

    for r in para.runs:
        if r.bold:
            sig.has_bold = True
        if r.italic:
            sig.has_italic = True
        if r.underline:
            sig.has_underline = True
        if r.font.color is not None and r.font.color.rgb is not None:
            sig.has_color = True
        if getattr(r.font, "highlight_color", None):
            sig.has_highlight = True

    stripped = text.strip()
    sig.starts_with_dash = bool(re.match(r"^-(\s|soit\s)", stripped))
    sig.starts_with_arrow = stripped.startswith("→")
    sig.starts_with_letter_paren = bool(re.match(r"^[a-z]\)", stripped))
    sig.starts_with_digit_paren = bool(re.match(r"^\d+\)", stripped))
    sig.starts_with_bullet = stripped.startswith("•")
    sig.is_only_dash = re.fullmatch(r"-\s*", stripped) is not None
    sig.is_only_ou = re.fullmatch(r"[Oo]u\.?", stripped) is not None
    sig.contains_placeholder = any(m in text for m in PLACEHOLDER_MARKERS)

    return sig


# =====================================================================
# Rules engine — chaque règle retourne (type, confidence) ou None
# Ordre = priorité (first match wins)
# =====================================================================

ClassifyResult = tuple[str, str] | None  # (type, confidence)


def rule_section_title(s: ParaSignal) -> ClassifyResult:
    if s.style in HEADING_STYLES:
        return ("SECTION_TITLE", "high")
    return None


def rule_document_note(s: ParaSignal) -> ClassifyResult:
    if (s.has_italic and s.has_underline) and _matches_any(s.text.strip(), DOCUMENT_NOTE_INCIPITS):
        return ("DOCUMENT_NOTE", "high")
    return None


def rule_example_header(s: ParaSignal) -> ClassifyResult:
    if (s.has_italic and s.has_underline) and _matches_any(s.text.strip(), EXAMPLE_HEADER_INCIPITS):
        return ("EXAMPLE_HEADER", "high")
    return None


def rule_annex_or_tech_section_header(s: ParaSignal) -> ClassifyResult:
    """Combinaison rare gras+couleur+italique = ANNEX_SECTION_HEADER ou TECH_SECTION_HEADER."""
    if s.has_bold and s.has_color and s.has_italic:
        # Différenciation par contexte : si on est dans une annexe → ANNEX_SECTION_HEADER
        # Sinon TECH_SECTION_HEADER. Pour v2 : on retourne le générique, le 2e pass affinera.
        return ("TECH_SECTION_HEADER", "high")
    return None


def rule_text_sub_title(s: ParaSignal) -> ClassifyResult:
    """Sous-titre textuel : gras + couleur (sans italique), généralement en MAJUSCULES."""
    if s.has_bold and s.has_color and not s.has_italic and s.style == "Normal":
        return ("TEXT_SUB_TITLE", "high")
    return None


def rule_variant_block_header(s: ParaSignal) -> ClassifyResult:
    if s.style == "Heading 9" and s.has_bold:
        return ("VARIANT_BLOCK_HEADER", "high")
    return None


def rule_structure_header(s: ParaSignal) -> ClassifyResult:
    if s.has_bold and s.has_underline and not s.has_color:
        return ("STRUCTURE_HEADER", "high")
    return None


def rule_enumerated_header(s: ParaSignal) -> ClassifyResult:
    if s.has_underline and (
        s.starts_with_letter_paren or re.match(r"^ARTICLE\s+\d+", s.text.strip())
    ):
        return ("ENUMERATED_HEADER", "high")
    return None


def rule_nota_bene(s: ParaSignal) -> ClassifyResult:
    if _matches_any(s.text.strip(), NOTA_BENE_INCIPITS) and not (s.has_italic and s.has_underline):
        return ("NOTA_BENE", "high")
    return None


def rule_choice_header(s: ParaSignal) -> ClassifyResult:
    # Souligné seul (pas gras), Normal, présence de ':' ou variante explicite.
    if s.has_underline and not s.has_bold and (
        re.search(r"Hypothèse\s+\d", s.text)
        or "Pouvoir adjudicateur:" in s.text
        or ":" in s.text
    ):
        return ("CHOICE_HEADER", "medium")
    return None


def rule_choice_separator(s: ParaSignal) -> ClassifyResult:
    if s.is_only_ou:
        return ("CHOICE_SEPARATOR", "high")
    return None


def rule_empty_list_placeholder(s: ParaSignal) -> ClassifyResult:
    if s.is_only_dash:
        return ("EMPTY_LIST_PLACEHOLDER", "high")
    return None


def rule_arrow_sub_action(s: ParaSignal) -> ClassifyResult:
    if s.starts_with_arrow:
        return ("ARROW_SUB_ACTION", "high")
    return None


def rule_numbered_procedure(s: ParaSignal) -> ClassifyResult:
    if s.starts_with_digit_paren:
        return ("NUMBERED_PROCEDURE", "high")
    return None


def rule_meta_in_puces(s: ParaSignal) -> ClassifyResult:
    """Style Puces + incipit méta = META_COMMENT (polysémie résolue)."""
    if s.style in {"Puces 1", "Puces 2"} and _matches_any(s.text.strip(), META_INCIPITS):
        return ("META_COMMENT", "high")
    return None


def rule_meta_in_corps_de_texte_3(s: ParaSignal) -> ClassifyResult:
    """Style 'Corps de texte 3' = META_COMMENT systématique (Ch.G)."""
    if s.style == "Corps de texte 3":
        # Vérif quand même : si c'est clairement du contenu narratif sans incipit, downgrade
        if _matches_any(s.text.strip(), META_INCIPITS):
            return ("META_COMMENT", "high")
        return ("META_COMMENT", "medium")
    return None


def rule_legal_reminder_color_italic(s: ParaSignal) -> ClassifyResult:
    """En Ch.G, [color,i] = LEGAL_REMINDER. En Ch.A, italique seul + incipit légal idem."""
    if s.has_color and s.has_italic:
        return ("LEGAL_REMINDER", "high")
    if s.has_italic and _matches_any(s.text.strip(), LEGAL_REMINDER_INCIPITS):
        return ("LEGAL_REMINDER", "high")
    return None


def rule_meta_color_only(s: ParaSignal) -> ClassifyResult:
    """[color] seul (Ch.G) = META_COMMENT."""
    if s.has_color and not s.has_italic and not s.has_bold and not s.has_underline:
        return ("META_COMMENT", "high")
    return None


def rule_meta_italic(s: ParaSignal) -> ClassifyResult:
    """Italique + incipit méta = META_COMMENT (Ch.A pattern principal)."""
    if s.has_italic and _matches_any(s.text.strip(), META_INCIPITS):
        return ("META_COMMENT", "high")
    return None


def rule_choice_item(s: ParaSignal) -> ClassifyResult:
    if s.starts_with_dash:
        return ("CHOICE_ITEM", "medium")
    return None


def rule_list_item(s: ParaSignal) -> ClassifyResult:
    if s.style in LIST_STYLES:
        return ("LIST_ITEM", "high")
    return None


def rule_inline_placeholder(s: ParaSignal) -> ClassifyResult:
    if s.contains_placeholder:
        return ("INLINE_PLACEHOLDER", "high")
    return None


def rule_meta_text_only_fallback(s: ParaSignal) -> ClassifyResult:
    """Dernier recours : style Normal sans formatage mais avec incipit méta clair."""
    if (
        s.style == "Normal"
        and not any([s.has_italic, s.has_color, s.has_bold, s.has_underline])
        and _matches_any(s.text.strip(), META_INCIPITS)
    ):
        return ("META_COMMENT", "low")
    return None


def rule_default_csc_content(s: ParaSignal) -> ClassifyResult:
    return ("CSC_CONTENT", "low")


# Order matters — first match wins. Ordre conçu pour éviter les conflits.
RULES: list[tuple[str, Callable[[ParaSignal], ClassifyResult]]] = [
    ("H01_section_title", rule_section_title),
    ("H02_document_note", rule_document_note),
    ("H03_example_header", rule_example_header),
    ("H04_annex_or_tech_section", rule_annex_or_tech_section_header),
    ("H05_text_sub_title", rule_text_sub_title),
    ("H06_variant_block_header", rule_variant_block_header),
    ("H07_structure_header", rule_structure_header),
    ("H08_enumerated_header", rule_enumerated_header),
    ("H09_nota_bene", rule_nota_bene),
    ("H10_choice_header", rule_choice_header),
    ("H11_choice_separator", rule_choice_separator),
    ("H12_empty_list_placeholder", rule_empty_list_placeholder),
    ("H13_arrow_sub_action", rule_arrow_sub_action),
    ("H14_numbered_procedure", rule_numbered_procedure),
    ("H15_meta_in_puces", rule_meta_in_puces),
    ("H16_meta_in_corps_de_texte_3", rule_meta_in_corps_de_texte_3),
    ("H17_legal_reminder_color_italic", rule_legal_reminder_color_italic),
    ("H18_meta_color_only", rule_meta_color_only),
    ("H19_meta_italic_with_incipit", rule_meta_italic),
    ("H20_choice_item", rule_choice_item),
    ("H21_inline_placeholder", rule_inline_placeholder),
    ("H22_list_item", rule_list_item),
    ("H23_meta_text_fallback", rule_meta_text_only_fallback),
    ("H99_default_csc_content", rule_default_csc_content),
]


def classify_pass1(signals: list[ParaSignal]) -> list[dict]:
    """Première passe : classification individuelle."""
    out = []
    for s in signals:
        result = None
        for rule_id, rule_fn in RULES:
            r = rule_fn(s)
            if r is not None:
                result = (rule_id, *r)
                break
        rule_id, type_, conf = result  # type: ignore[misc]
        out.append(
            {
                "idx": s.idx,
                "style": s.style,
                "type": type_,
                "confidence": conf,
                "rule": rule_id,
                "signals": _signal_summary(s),
                "excerpt": s.text[:120],
            }
        )
    return out


def _signal_summary(s: ParaSignal) -> list[str]:
    out = []
    signals = [
        (s.has_bold, "b"),
        (s.has_italic, "i"),
        (s.has_underline, "u"),
        (s.has_color, "color"),
        (s.has_highlight, "highlight"),
        (s.starts_with_dash, "dash"),
        (s.starts_with_arrow, "arrow"),
        (s.starts_with_letter_paren, "a)"),
        (s.starts_with_digit_paren, "1)"),
        (s.starts_with_bullet, "•"),
        (s.is_only_ou, "=ou"),
        (s.is_only_dash, "=dash"),
        (s.contains_placeholder, "..."),
    ]
    for enabled, label in signals:
        if enabled:
            out.append(label)
    return out


# =====================================================================
# Pass 2 — regroupement consécutif
# =====================================================================

def classify_pass2(annotations: list[dict]) -> list[dict]:
    """Regroupe les paragraphes consécutifs :
       - GROUPED_LEGAL_REMINDER : ≥3 LEGAL_REMINDER consécutifs sans break heading
       - Marque CSC_CONTENT_TO_INSERT après un META_COMMENT 'introduire le texte suivant:'
    """
    if not annotations:
        return annotations

    # 1. Marquer GROUPED_LEGAL_REMINDER
    i = 0
    while i < len(annotations):
        if annotations[i]["type"] == "LEGAL_REMINDER":
            j = i
            while j < len(annotations) and annotations[j]["type"] == "LEGAL_REMINDER":
                j += 1
            count = j - i
            if count >= 3:
                for k in range(i, j):
                    annotations[k]["group"] = f"grouped_legal_{i}"
                    annotations[k]["group_size"] = count
            i = j
        else:
            i += 1

    # 2. Marquer CSC_CONTENT_TO_INSERT après META_COMMENT annonciateur
    insert_pattern = re.compile(
        r"introduire le texte suivant|insérer le texte suivant|reprendre le texte suivant",
        re.I,
    )
    for i, ann in enumerate(annotations):
        if ann["type"] == "META_COMMENT" and insert_pattern.search(ann["excerpt"]):
            # Le prochain CSC_CONTENT devient CSC_CONTENT_TO_INSERT
            for k in range(i + 1, min(i + 10, len(annotations))):
                nxt = annotations[k]
                if nxt["type"] == "SECTION_TITLE":
                    break
                if nxt["type"] in ("CSC_CONTENT", "META_COMMENT"):
                    nxt["type"] = "CSC_CONTENT_TO_INSERT"
                    nxt["rule"] = nxt.get("rule", "") + "+pass2_to_insert"
                    break

    return annotations


# =====================================================================
# Main
# =====================================================================

def extract(docx_path: Path) -> list[dict]:
    doc = Document(str(docx_path))
    n = accept_all_revisions(doc)
    print(f"# accepted {n} revisions on {docx_path.name}", file=sys.stderr)
    signals = [
        signal_from_para(i, p)
        for i, p in enumerate(doc.paragraphs)
        if p.text.strip()
    ]
    annotations = classify_pass1(signals)
    annotations = classify_pass2(annotations)
    return annotations


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("docx", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="Output JSONL (default: stdout)")
    ap.add_argument("--stats", action="store_true", help="Print type distribution at end")
    args = ap.parse_args(argv)

    annotations = extract(args.docx)

    if args.output:
        with args.output.open("w", encoding="utf-8") as out_stream:
            for ann in annotations:
                out_stream.write(json.dumps(ann, ensure_ascii=False) + "\n")
    else:
        for ann in annotations:
            sys.stdout.write(json.dumps(ann, ensure_ascii=False) + "\n")

    if args.stats:
        c = Counter(a["type"] for a in annotations)
        print("\n=== Type distribution ===", file=sys.stderr)
        for t, n in c.most_common():
            print(f"  {t:<25} {n:>4}", file=sys.stderr)
        print(f"  TOTAL                     {sum(c.values()):>4}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
