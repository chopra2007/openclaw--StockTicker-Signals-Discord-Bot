"""Logging filter that redacts bearer tokens from log records."""
import logging
import os
import re
from typing import ClassVar


class RedactingFilter(logging.Filter):
    """Removes bearer token values from log records.

    Install on the root logger at engine startup so all handlers are covered:
        logging.getLogger().addFilter(RedactingFilter())
    """

    _BEARER_RE: ClassVar[re.Pattern] = re.compile(r'Bearer\s+[A-Fa-f0-9]{64}')
    _REDACTED: ClassVar[str] = 'Bearer ***REDACTED***'

    def __init__(self) -> None:
        super().__init__()
        # Collect all live token values at install time so literal substrings are
        # also redacted (e.g. a token that appears in a URL without the Bearer prefix).
        raw_tokens = [
            os.environ.get(k, '')
            for k in os.environ
            if k.startswith('INGEST_BEARER_TOKEN')
        ]
        self._literal_tokens: list[str] = [t for t in raw_tokens if len(t) >= 16]

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.msg = self._scrub(str(record.msg))
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._scrub(str(v)) for k, v in record.args.items()}
            else:
                record.args = tuple(self._scrub(str(a)) for a in record.args)
        return True

    def _scrub(self, text: str) -> str:
        text = self._BEARER_RE.sub(self._REDACTED, text)
        for token in self._literal_tokens:
            if token in text:
                text = text.replace(token, '***REDACTED***')
        return text
