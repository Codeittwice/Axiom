"""Text cleanup helpers for console, TTS, and tool output."""

from __future__ import annotations

import re
import sys
import unicodedata


DROP_CHARS = {"\u034f"}
DROP_CATEGORIES = {"Cf"}


def clean_text(value: object, collapse_whitespace: bool = False) -> str:
    """Remove invisible/problematic Unicode while preserving normal text."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    cleaned = []
    for ch in text:
        category = unicodedata.category(ch)
        if ch in DROP_CHARS or category in DROP_CATEGORIES:
            continue
        if category == "Cc" and ch not in "\n\r\t":
            continue
        cleaned.append(ch)

    result = "".join(cleaned)
    if collapse_whitespace:
        result = re.sub(r"\s+", " ", result)
    return result.strip()


def console_text(value: object) -> str:
    """Return text that can be printed even on narrow Windows code pages."""
    text = clean_text(value)
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")
