# pyright: reportPrivateUsage=false

"""Unit-test suite for the `docx.revisions` module."""

from __future__ import annotations

from lxml import etree

from docx.oxml.ns import nsmap, qn
from docx.revisions import _accept_in_tree, _reject_in_tree

W = nsmap["w"]


def _parse(xml_body: str) -> etree._Element:
    """Wrap *xml_body* in a ``w:body`` element and parse it."""
    return etree.fromstring(
        f'<w:body xmlns:w="{W}">{xml_body}</w:body>'.encode("utf-8")
    )


def _text_of(root: etree._Element) -> str:
    return "".join(t.text or "" for t in root.iter(qn("w:t")))


class DescribeAcceptInTree:
    """Suite for `_accept_in_tree` — unwraps insertions, removes deletions."""

    def it_unwraps_w_ins_keeping_its_runs(self):
        root = _parse('<w:ins><w:r><w:t>kept</w:t></w:r></w:ins>')
        assert _accept_in_tree(root) == 1
        assert root.find(qn("w:ins")) is None
        assert _text_of(root) == "kept"

    def it_drops_w_del_entirely(self):
        root = _parse(
            '<w:r><w:t>keep</w:t></w:r>'
            '<w:del><w:r><w:delText>gone</w:delText></w:r></w:del>'
        )
        assert _accept_in_tree(root) == 1
        assert root.find(qn("w:del")) is None
        assert _text_of(root) == "keep"

    def it_unwraps_w_moveTo_and_drops_w_moveFrom(self):
        root = _parse(
            '<w:moveTo><w:r><w:t>arrived</w:t></w:r></w:moveTo>'
            '<w:moveFrom><w:r><w:t>gone</w:t></w:r></w:moveFrom>'
        )
        assert _accept_in_tree(root) == 2
        assert _text_of(root) == "arrived"

    def it_handles_w_del_nested_inside_w_ins(self):
        root = _parse(
            '<w:ins>'
            '  <w:r><w:t>ins</w:t></w:r>'
            '  <w:del><w:r><w:delText>also-ins-then-del</w:delText></w:r></w:del>'
            '</w:ins>'
        )
        # Outer ins is unwrapped first → del is removed in the same pass,
        # so the count is 2 (one ins + one del that survived to be counted).
        _accept_in_tree(root)
        # What matters: nothing left, and only "ins" remains in text.
        assert root.find(f".//{qn('w:ins')}") is None
        assert root.find(f".//{qn('w:del')}") is None
        assert _text_of(root) == "ins"

    def it_preserves_text_tails_when_unwrapping(self):
        root = _parse(
            '<w:r><w:t>before</w:t></w:r>'
            '<w:ins><w:r><w:t>mid</w:t></w:r></w:ins>'
            '<w:r><w:t>after</w:t></w:r>'
        )
        _accept_in_tree(root)
        assert _text_of(root) == "beforemidafter"


class DescribeRejectInTree:
    """Suite for `_reject_in_tree` — removes insertions, restores deletions."""

    def it_drops_w_ins_entirely(self):
        root = _parse(
            '<w:r><w:t>keep</w:t></w:r>'
            '<w:ins><w:r><w:t>gone</w:t></w:r></w:ins>'
        )
        assert _reject_in_tree(root) == 1
        assert _text_of(root) == "keep"

    def it_restores_w_del_text_as_w_t(self):
        root = _parse(
            '<w:del><w:r><w:delText>restored</w:delText></w:r></w:del>'
        )
        assert _reject_in_tree(root) == 1
        assert root.find(qn("w:del")) is None
        # The delText should now be a regular w:t element with the same content.
        assert _text_of(root) == "restored"
        assert root.find(f".//{qn('w:delText')}") is None

    def it_drops_w_moveTo_and_unwraps_w_moveFrom(self):
        root = _parse(
            '<w:moveTo><w:r><w:t>gone</w:t></w:r></w:moveTo>'
            '<w:moveFrom><w:r><w:t>kept</w:t></w:r></w:moveFrom>'
        )
        _reject_in_tree(root)
        assert _text_of(root) == "kept"

    def it_is_a_no_op_when_no_revisions_present(self):
        root = _parse('<w:r><w:t>plain</w:t></w:r>')
        assert _reject_in_tree(root) == 0
        assert _text_of(root) == "plain"
