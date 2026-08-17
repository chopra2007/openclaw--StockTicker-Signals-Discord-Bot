# EVIDENCE COPY — original path: tests/test_alfred_vault.py
# copied 2026-08-17 for TODO #87 (read-only evidence, do not edit)
# full file, 17 lines

import os
import pytest
from consensus_engine.briefing import alfred


async def test_write_vault_briefing_creates_dated_file(tmp_path):
    await alfred._write_vault_briefing(
        "2026-04-21",
        "## Morning Brief\nhello",
        str(tmp_path),
    )
    expected = tmp_path / "macro" / "briefings" / "2026-04-21.md"
    assert expected.exists()
    content = expected.read_text()
    assert "Morning Brief" in content
    # Atomic — no leftover .tmp
    assert not (tmp_path / "macro" / "briefings" / "2026-04-21.md.tmp").exists()
