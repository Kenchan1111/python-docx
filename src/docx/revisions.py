"""Accept or reject tracked revisions (``w:ins``, ``w:del``, ``w:moveFrom``, ``w:moveTo``).

python-docx core has no API for tracked changes. This module fills that gap by
walking the OXML of the main document and all related parts that may host
revision markers (headers, footers, footnotes, endnotes, comments) and either
applying or discarding each revision.

Content-level revisions only: property-change markers such as ``w:rPrChange``,
``w:pPrChange``, ``w:sectPrChange`` are not handled here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Iterable

from lxml import etree

from docx.opc.constants import CONTENT_TYPE as CT
from docx.oxml.ns import qn

if TYPE_CHECKING:
    from docx.document import Document
    from docx.opc.part import Part


_WORDPROCESSING_CONTENT_TYPES = frozenset(
    {
        CT.WML_DOCUMENT_MAIN,
        CT.WML_HEADER,
        CT.WML_FOOTER,
        CT.WML_FOOTNOTES,
        CT.WML_ENDNOTES,
        CT.WML_COMMENTS,
    }
)


def accept_all_revisions(document: "Document") -> int:
    """Accept every content-level tracked revision in ``document``.

    Returns the total number of revision elements processed across all parts.
    The document is mutated in place; call ``document.save()`` to persist.
    """
    return _process_all(document, _accept_in_tree)


def reject_all_revisions(document: "Document") -> int:
    """Reject every content-level tracked revision in ``document``.

    Returns the total number of revision elements processed across all parts.
    The document is mutated in place; call ``document.save()`` to persist.
    """
    return _process_all(document, _reject_in_tree)


def _process_all(
    document: "Document", processor: Callable[[etree._Element], int]
) -> int:
    total = 0
    for part in _iter_wml_parts(document):
        # XmlPart exposes ``element`` (serialized live on .blob access) — mutate it.
        # Plain Part (e.g. footnotes when no class is registered) only carries
        # ``_blob``; parse it, mutate, write the bytes back.
        live_element = getattr(part, "_element", None)
        if live_element is not None:
            total += processor(live_element)
        else:
            blob = part.blob
            if not blob:
                continue
            root = etree.fromstring(blob)
            n = processor(root)
            if n:
                part._blob = etree.tostring(
                    root, xml_declaration=True, encoding="UTF-8", standalone=True
                )
            total += n
    return total


def _iter_wml_parts(document: "Document") -> Iterable["Part"]:
    """Yield every WordprocessingML part in the package."""
    package = document.part.package
    seen: set[int] = set()

    def walk(source):
        for rel in source.rels.values():
            if rel.is_external:
                continue
            part = rel.target_part
            key = id(part)
            if key in seen:
                continue
            seen.add(key)
            if part.content_type in _WORDPROCESSING_CONTENT_TYPES:
                yield part
            yield from walk(part)

    yield from walk(package)


def _accept_in_tree(root: etree._Element) -> int:
    count = 0
    # Drop deletion markers entirely (including their content).
    count += _remove_elements(root, (qn("w:del"), qn("w:moveFrom")))
    # Unwrap insertion markers, preserving their content.
    count += _unwrap_elements(root, (qn("w:ins"), qn("w:moveTo")))
    return count


def _reject_in_tree(root: etree._Element) -> int:
    count = 0
    # Drop insertion markers entirely.
    count += _remove_elements(root, (qn("w:ins"), qn("w:moveTo")))
    # Unwrap deletion markers and restore w:delText as w:t so the text reappears.
    count += _unwrap_elements(
        root, (qn("w:del"), qn("w:moveFrom")), restore_del_text=True
    )
    return count


def _remove_elements(root: etree._Element, tags: tuple[str, ...]) -> int:
    count = 0
    for tag in tags:
        for elem in list(root.iter(tag)):
            parent = elem.getparent()
            if parent is not None:
                parent.remove(elem)
                count += 1
    return count


def _unwrap_elements(
    root: etree._Element,
    tags: tuple[str, ...],
    *,
    restore_del_text: bool = False,
) -> int:
    """Replace each matching element with its children, in place."""
    count = 0
    del_text_tag = qn("w:delText")
    t_tag = qn("w:t")
    for tag in tags:
        # Snapshot the matches first; mutating during iteration is unsafe.
        for elem in list(root.iter(tag)):
            parent = elem.getparent()
            if parent is None:
                continue
            if restore_del_text:
                for dt in elem.iter(del_text_tag):
                    dt.tag = t_tag
            index = parent.index(elem)
            # Insert children at the element's position, preserving order.
            for child in list(elem):
                parent.insert(index, child)
                index += 1
            # Preserve any trailing text after the unwrapped element.
            if elem.tail:
                if len(parent) > 0 and index > 0:
                    sibling = parent[index - 1]
                    sibling.tail = (sibling.tail or "") + elem.tail
                else:
                    parent.text = (parent.text or "") + elem.tail
            parent.remove(elem)
            count += 1
    return count
