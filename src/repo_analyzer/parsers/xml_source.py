"""Line-preserving XML parser built on the standard-library ``xml.sax``.

Produces a lightweight element tree where every node carries its 1-based source
line range, so rules can attach real evidence without hardcoding line numbers
and without pulling in a heavyweight dependency such as lxml. Namespace prefixes
are preserved in ``qname`` and stripped in ``tag`` for convenient structural
matching (e.g. ``jdbc:embedded-database`` -> tag ``embedded-database``).

External DTD/entity resolution is disabled so parsing stays fully offline and
safe on untrusted repositories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import StringIO
from typing import Iterator
from xml.sax import ContentHandler, SAXParseException, make_parser
from xml.sax.handler import (
    feature_external_ges,
    feature_external_pes,
    feature_namespaces,
)

from .common import ParseIssue


@dataclass
class XmlNode:
    """One XML element with its 1-based source line range."""

    tag: str
    qname: str
    attrib: dict[str, str]
    start_line: int
    end_line: int
    text: str = ""
    children: list["XmlNode"] = field(default_factory=list)

    def find(self, tag: str) -> list["XmlNode"]:
        """Direct children whose local tag equals ``tag``."""

        return [c for c in self.children if c.tag == tag]

    def first(self, tag: str) -> "XmlNode | None":
        for child in self.children:
            if child.tag == tag:
                return child
        return None

    def text_of(self, tag: str) -> str | None:
        node = self.first(tag)
        if node is None:
            return None
        stripped = node.text.strip()
        return stripped or None

    def iter(self) -> Iterator["XmlNode"]:
        yield self
        for child in self.children:
            yield from child.iter()

    def iter_tag(self, tag: str) -> Iterator["XmlNode"]:
        for node in self.iter():
            if node.tag == tag:
                yield node


@dataclass
class XmlDocument:
    path: str
    root: XmlNode | None = None
    issues: list[ParseIssue] = field(default_factory=list)


def _local(name: str) -> str:
    return name.rsplit(":", 1)[-1]


class _Handler(ContentHandler):
    def __init__(self) -> None:
        super().__init__()
        self._locator = None
        self.root: XmlNode | None = None
        self._stack: list[XmlNode] = []

    def setDocumentLocator(self, locator) -> None:  # noqa: N802 (SAX API)
        self._locator = locator

    def _line(self) -> int:
        if self._locator is not None:
            line = self._locator.getLineNumber()
            if line is not None and line > 0:
                return line
        return 1

    def startElement(self, name, attrs) -> None:  # noqa: N802 (SAX API)
        line = self._line()
        node = XmlNode(
            tag=_local(name),
            qname=name,
            attrib={_local(key): attrs.getValue(key) for key in attrs.getNames()},
            start_line=line,
            end_line=line,
        )
        if self._stack:
            self._stack[-1].children.append(node)
        else:
            self.root = node
        self._stack.append(node)

    def characters(self, content) -> None:
        if self._stack:
            self._stack[-1].text += content

    def endElement(self, name) -> None:  # noqa: N802 (SAX API)
        node = self._stack.pop()
        node.end_line = max(node.end_line, self._line())


def parse_xml(text: str, path: str) -> XmlDocument:
    """Parse ``text`` into a line-located :class:`XmlDocument`.

    Parse failures are recorded as a ``ParseIssue`` (``xml_parse_error``) rather
    than raised, matching the "never silently ignore, never crash" contract.
    """

    doc = XmlDocument(path=path)
    parser = make_parser()
    parser.setFeature(feature_namespaces, False)
    for feature in (feature_external_ges, feature_external_pes):
        try:
            parser.setFeature(feature, False)
        except Exception:  # pragma: no cover - not all parsers expose these
            pass
    handler = _Handler()
    parser.setContentHandler(handler)
    try:
        parser.parse(StringIO(text))
    except SAXParseException as exc:
        doc.issues.append(ParseIssue("xml_parse_error", str(exc)))
        return doc
    except Exception as exc:  # pragma: no cover - defensive
        doc.issues.append(ParseIssue("xml_parse_error", str(exc)))
        return doc
    doc.root = handler.root
    if doc.root is None:
        doc.issues.append(ParseIssue("xml_empty", "document has no root element"))
    return doc
