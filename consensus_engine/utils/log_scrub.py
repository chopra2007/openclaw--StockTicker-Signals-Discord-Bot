"""Credential-safe scrubber for exception strings before structured logging.

Real Gemini SDK leak paths observed in `repr(exc)` / `str(exc)`:
  - AIza... (Google API canonical, 39 chars)
  - x-goog-api-key / api_key headers in gRPC metadata
  - Authorization: Bearer ... from proxy intercepts
  - ?key=... query-string fragments
  - gsk_... (Groq), sk-... (OpenAI-style)
  - JWT tokens (eyJ-prefixed three-segment)
  - Long hex / base64 blobs

Patterns and approach from pass-3-security.md §H1. Apply to BOTH `str(exc)`
and `repr(exc)` since gRPC errors put the secret in the repr but not the str
(or vice versa).
"""
from __future__ import annotations

import re

_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"(?i)(?:x-goog-api-key|api[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"[?&]key=[A-Za-z0-9_\-]{20,}"),
    re.compile(r"gsk_[A-Za-z0-9]{40,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
]

_REDACTION = "[REDACTED]"


def scrub(s: str, maxlen: int = 500) -> str:
    """Replace every secret-shaped substring with [REDACTED], then truncate.

    Returns an empty string for None/empty input. The truncation cap
    (default 500 chars) protects log lines from runaway exception messages.
    """
    if not s:
        return ""
    out = s
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub(_REDACTION, out)
    return out[:maxlen]
