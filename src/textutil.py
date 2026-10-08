"""Small text helpers (stdlib only).

Job descriptions from the boards are full of HTML. We strip that to plain text
before showing it to the model or logging it, using Python's built-in HTML parser
so there's no extra dependency to install.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "li", "div", "tr", "h1", "h2", "h3", "h4"):
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def strip_html(text: str | None) -> str:
    """Turn an HTML (or plain) string into readable plain text."""
    if not text:
        return ""
    # If it doesn't look like HTML, just unescape entities and tidy whitespace.
    if "<" not in text:
        return _collapse_whitespace(html.unescape(text))
    parser = _TextExtractor()
    try:
        parser.feed(text)
        parser.close()
        out = parser.text()
    except Exception:
        # Never let a malformed description crash a run — fall back to a
        # crude tag strip.
        out = re.sub(r"<[^>]+>", " ", text)
        out = html.unescape(out)
    return _collapse_whitespace(out)


def _collapse_whitespace(text: str) -> str:
    # Collapse runs of blank lines and trailing spaces into something compact.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def truncate(text: str, max_chars: int) -> str:
    """Cut text to max_chars, adding a marker if anything was removed."""
    if not text or max_chars <= 0 or len(text) <= max_chars:
        return text or ""
    return text[:max_chars].rstrip() + " …[truncated]"
