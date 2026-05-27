"""Shared markdown helpers for Discord link formatting."""

import re

_MD_LINK_ESCAPE = str.maketrans({
    "\\": "\\\\",
    "[": "\\[",
    "]": "\\]",
    "(": "\\(",
    ")": "\\)",
    "`": "\\`",
})


def _escape_md_link_text(text: str) -> str:
    """Escape characters that break Discord markdown links inside link text.

    Escapes: \\ [ ] ( ) `
    Collapses \\r and \\n to a single space.
    """
    text = re.sub(r"[\r\n]+", " ", text)
    return text.translate(_MD_LINK_ESCAPE)
