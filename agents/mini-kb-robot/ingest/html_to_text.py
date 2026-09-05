"""Convert one FAQ answer's HTML into plain text plus extracted links/images.

The source column only ever contains a small, known tag set (p, br, strong, u,
span, a, img) - this is a purpose-built parser for that shape, not a general
HTML-to-text converter.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class Link:
    text: str
    url: str


@dataclass
class ParsedAnswer:
    text: str
    image_urls: list[str] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)


class _AnswerParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._link_stack: list[tuple[str, list[str]]] = []  # (url, buffered text parts)
        self.image_urls: list[str] = []
        self.links: list[Link] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag in ("p", "br"):
            self._emit("\n")
        elif tag == "img":
            src = attrs_dict.get("src")
            if src:
                self.image_urls.append(src)
                self._emit("[图片]")
        elif tag == "a":
            href = attrs_dict.get("href", "")
            self._link_stack.append((href, []))

    def handle_endtag(self, tag: str) -> None:
        if tag == "p":
            self._emit("\n")
        elif tag == "a" and self._link_stack:
            url, buffered = self._link_stack.pop()
            link_text = "".join(buffered).strip()
            if url:
                self.links.append(Link(text=link_text, url=url))
                self._emit(f"{link_text}（{url}）" if link_text else url)
            else:
                self._emit(link_text)

    def handle_data(self, data: str) -> None:
        self._emit(data)

    def _emit(self, text: str) -> None:
        if self._link_stack:
            self._link_stack[-1][1].append(text)
        else:
            self._parts.append(text)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        # collapse runs of whitespace-only lines, trim each line
        lines = [ln.strip() for ln in raw.splitlines()]
        lines = [ln for ln in lines if ln]
        return "\n".join(lines)


def parse_answer_html(raw_html: str) -> ParsedAnswer:
    unescaped = html.unescape(raw_html or "")
    parser = _AnswerParser()
    parser.feed(unescaped)
    parser.close()
    text = parser.get_text()
    # belt-and-suspenders: collapse any accidental multi-space runs left by tags
    text = re.sub(r"[ \t]+", " ", text)
    return ParsedAnswer(text=text, image_urls=parser.image_urls, links=parser.links)
