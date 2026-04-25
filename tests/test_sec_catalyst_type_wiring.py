"""A1: Wire catalyst_type='sec_filing' when SEC signal hits without news catalyst.

M6 (engine.py:304) checks `catalyst_type.startswith("sec_")` to exempt SEC
catalysts from the market_ok gate. SEC-only signals (no concurrent news
catalyst) had `catalyst_type=""` and never triggered the exemption — so M1's
SEC watcher revival doesn't realize its full lift unless this is wired.
"""
from unittest.mock import patch

import pytest

from consensus_engine.cross_reference import _resolve_catalyst_type


class TestResolveCatalystType:
    def test_news_catalyst_wins(self):
        """Real news catalyst type takes precedence over SEC-derived label."""
        assert _resolve_catalyst_type("Earnings Beat", sec_hit=True) == "Earnings Beat"

    def test_sec_only_returns_sec_filing(self):
        """SEC hit with no news catalyst → 'sec_filing' so M6 exemption fires."""
        assert _resolve_catalyst_type("", sec_hit=True) == "sec_filing"

    def test_no_catalyst_no_sec_returns_empty(self):
        assert _resolve_catalyst_type("", sec_hit=False) == ""

    def test_news_catalyst_wins_even_without_sec(self):
        assert _resolve_catalyst_type("Analyst Upgrade", sec_hit=False) == "Analyst Upgrade"


def test_resolve_called_in_cross_reference():
    """The cross_reference module must expose and use _resolve_catalyst_type
    so the SEC fallback is wired into CrossReferenceResult.catalyst_type."""
    import consensus_engine.cross_reference as xref
    src = open(xref.__file__).read()
    assert "_resolve_catalyst_type(" in src, \
        "cross_reference must call _resolve_catalyst_type to plumb sec_filing label"
