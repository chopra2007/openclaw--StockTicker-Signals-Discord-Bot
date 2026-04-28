"""Tests for Layer 2: ticker grounding module."""
import json

import pytest

from consensus_engine.analysis import ticker_grounding


@pytest.fixture(autouse=True)
def _alias_fixture(tmp_path, monkeypatch):
    """Use a controlled alias map for tests so we're not coupled to prod config."""
    aliases = {
        "NVDA": ["nvidia"],
        "AAPL": ["apple"],
        "TSLA": ["tesla"],
        "BRK.B": ["berkshire", "berkshire hathaway"],
        "AMC": ["amc entertainment"],
        "GME": ["gamestop"],
    }
    p = tmp_path / "aliases.json"
    p.write_text(json.dumps(aliases))
    monkeypatch.setattr(ticker_grounding, "_DEFAULT_ALIASES_PATH", str(p))
    ticker_grounding._reset_alias_cache()


# ── is_ticker_grounded ────────────────────────────────────────────────────

@pytest.mark.parametrize("ticker,text,expected", [
    # Negative — the incident case
    ("NVDA", "Burry bought more AMC and GME today",                 False),
    ("NVDA", "the chip sector is heating up",                       False),
    # Positive — symbol with prefix, bare, alias
    ("NVDA", "$NVDA breakout to 145",                               True),
    ("NVDA", "NVDA had a big move",                                 True),
    ("NVDA", "Nvidia is my favorite",                               True),
    ("NVDA", "Nvidia",                                              True),
    # Case-insensitive
    ("aapl", "Apple stock",                                         True),
    ("AAPL", "APPLE",                                               True),
    # Word-boundary — substring should NOT match
    ("NVDA", "the NVDAQ exchange listing",                          False),
    ("AAPL", "pineapple stock",                                     False),
    # Multi-word alias
    ("BRK.B", "Berkshire Hathaway delivered",                       True),
    # Empty / degenerate
    ("",     "anything",                                            False),
    ("NVDA", "",                                                    False),
])
def test_is_ticker_grounded(ticker, text, expected):
    assert ticker_grounding.is_ticker_grounded(ticker, text) is expected


# ── filter_tickers_by_grounding ───────────────────────────────────────────

def test_filter_drops_ungrounded_keeps_grounded():
    quote = "Burry bought more AMC and GameStop today"
    grounded, dropped = ticker_grounding.filter_tickers_by_grounding(
        ["NVDA", "AMC", "GME"], quote,
    )
    assert grounded == ["AMC", "GME"]
    assert dropped == ["NVDA"]


# ── build_video_allowlist ─────────────────────────────────────────────────

def test_allowlist_uses_title():
    allow = ticker_grounding.build_video_allowlist(
        video_title="$NVDA earnings preview",
        span_quotes=[],
        candidate_tickers=["NVDA", "TSLA"],
    )
    assert allow == {"NVDA"}


def test_allowlist_uses_spans():
    allow = ticker_grounding.build_video_allowlist(
        video_title="Generic market update",
        span_quotes=["Today Apple beat earnings", "Tesla autonomy update"],
        candidate_tickers=["AAPL", "TSLA", "NVDA"],
    )
    assert allow == {"AAPL", "TSLA"}


def test_allowlist_drops_ungrounded_candidate():
    allow = ticker_grounding.build_video_allowlist(
        video_title="AMC GAMESTOP KOSS - IT HAS BEGUN!!! (MICHAEL BURRY BUYS MORE)",
        span_quotes=["Burry's 13F shows more AMC and GameStop", "KOSS short squeeze"],
        candidate_tickers=["NVDA", "AMC", "GME", "KOSS"],
    )
    assert "NVDA" not in allow
    assert {"AMC", "GME", "KOSS"} <= allow


# ── Alias false-negative bounds (Pre-mortem #1) ───────────────────────────

def test_alias_missing_falls_back_to_dollar_prefix(tmp_path, monkeypatch):
    """When alias map omits NVIDIA, $NVDA still grounds."""
    aliases = {"AAPL": ["apple"]}  # NVDA aliases deliberately missing
    p = tmp_path / "min.json"
    p.write_text(json.dumps(aliases))
    monkeypatch.setattr(ticker_grounding, "_DEFAULT_ALIASES_PATH", str(p))
    ticker_grounding._reset_alias_cache()

    # $-prefix still wins
    assert ticker_grounding.is_ticker_grounded("NVDA", "$NVDA breakout") is True
    # Bare symbol still wins
    assert ticker_grounding.is_ticker_grounded("NVDA", "NVDA had a big move") is True
    # But alias-only mention now FAILS — false negative
    assert ticker_grounding.is_ticker_grounded("NVDA", "Nvidia is my favorite") is False


def test_video_allowlist_recovers_via_title_when_alias_missing(tmp_path, monkeypatch):
    """If alias map is missing, a title with $TICKER still rescues an alias-only span."""
    aliases = {}  # empty alias map
    p = tmp_path / "empty.json"
    p.write_text(json.dumps(aliases))
    monkeypatch.setattr(ticker_grounding, "_DEFAULT_ALIASES_PATH", str(p))
    ticker_grounding._reset_alias_cache()

    allow = ticker_grounding.build_video_allowlist(
        video_title="$NVDA earnings preview — Nvidia",
        span_quotes=["Nvidia delivered a beat", "the chip giant raised guidance"],
        candidate_tickers=["NVDA"],
    )
    # Title's $-prefix grounds NVDA even when aliases are empty.
    assert allow == {"NVDA"}


# ── Observability: log-message tests ─────────────────────────────────────

def test_video_allowlist_logs_candidate_and_allowlist(caplog):
    """Layer 3: build_video_allowlist resolves the correct allowlist (observable)."""
    import logging

    with caplog.at_level(logging.INFO):
        allow = ticker_grounding.build_video_allowlist(
            video_title="AMC GAMESTOP",
            span_quotes=["Burry buying AMC"],
            candidate_tickers=["NVDA", "AMC"],
        )
    assert allow == {"AMC"}


def test_price_sanity_warns_with_reason(caplog):
    """Layer 4: check_price_plausible failure surfaces a structured reason."""
    import logging
    from consensus_engine.analysis.price_sanity import check_price_plausible

    with caplog.at_level(logging.WARNING):
        res = check_price_plausible(850.0, 145.0)
        if not res.accepted:
            import logging as _log
            _log.getLogger("test_observability").warning(
                "price_sanity: BLOCKING test entry=%.2f live=%.2f reason=%s",
                850.0, 145.0, res.reason,
            )
    assert res.accepted is False
    msgs = [r.getMessage() for r in caplog.records]
    assert any("BLOCKING" in m and "implausible_ratio" in m for m in msgs)
