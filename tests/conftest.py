"""Shared pytest fixtures for the consensus_engine test suite."""
import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture(autouse=True)
def no_discord_alerts():
    """Prevent any test from firing real Discord alerts."""
    with patch(
        "consensus_engine.scanners.youtube._send_youtube_alert",
        new=AsyncMock(),
    ):
        yield


@pytest.fixture(autouse=True)
def _reset_http_singleton():
    """Reset the shared aiohttp session globals between tests.

    Some tests patch `aiohttp.ClientSession` globally to intercept the
    singleton creation inside `consensus_engine.utils.http.get_session`. When
    the patch is reverted, the polluted `_session` global persists into the
    next test, causing AttributeError on `_session.closed` checks. Reset both
    `_session` and `_lock` so every test starts from a clean slate.
    """
    yield
    from consensus_engine.utils import http as _http
    _http._session = None
    _http._lock = None


@pytest.fixture(autouse=True)
def _audit_flags_default_off(monkeypatch):
    """The 2026-06-08 go-live flipped several user-visible !all / Wolf flags ON in
    config/consensus.yaml. The bulk of the suite was written against their documented
    default (OFF) and reads the live config, so the flip makes those tests assert
    against the wrong (ON) behavior. Force the flipped flags OFF here so tests stay
    deterministic regardless of the deployed config. The dedicated feature tests force
    their own flag in-body (that patch wins), so their ON/OFF coverage is unaffected."""
    from consensus_engine import config as _cfg
    _real = _cfg.get
    _off = {
        "all_command.market_cap_gate_enabled": False,
        "all_command.sparse_banner.enabled": False,
        "all_command.risk_price_gate_strict": False,
        "all_command.levels.technical_engine_enabled": False,
        "sec_watcher.named_insiders_in_alert": False,
        "wolf.confluence.board_show_levelless": False,
        "wolf.confluence.links_enabled": False,
        "wolf.direction_guard.enabled": False,
        # Phase-1 signal features (signal-features-2026-06-09) — keep OFF so the
        # baseline suite stays green; dedicated feature tests force their own flag.
        "features.earnings_magnitude.enabled": False,
        "features.regime_context_line.enabled": False,
        "features.score_display_honesty.enabled": False,
        "features.analyst_accuracy_weight.enabled": False,
        "features.sec_graduated_scoring.enabled": False,
        "features.options_graduated_scoring.enabled": False,
        "features.youtube_score.direction_aware": False,
        "features.youtube_score.recency_decay": False,
        "features.youtube_score.channel_reliability": False,
        "features.youtube_score.level_confluence": False,
        "wolf.outcomes.benchmark_adjusted": False,
        # Phase-2 signal features (signal-features-2026-06-09 Waves 3-4) — keep
        # OFF for the baseline suite; dedicated feature tests force their own flag.
        "features.contradiction_index_live.enabled": False,
        "features.strong_requires_hard_evidence.enabled": False,
        "features.manufactured_agreement_gate.enabled": False,
        "features.apewisdom_zscore.enabled": False,
        "features.single_score.enabled": False,
        "features.consensus_logodds.enabled": False,
        "features.regime_widening_graduated.enabled": False,
        "features.cross_asset.enabled": False,
        "features.cross_asset.fred_leg_enabled": False,
        "features.finra_short_volume.enabled": False,
        "features.fundamentals_oneliner.enabled": False,
        "wolf.confluence.weighted_votes_enabled": False,
    }

    def _patched(key, default=None):
        if key in _off:
            return _off[key]
        return _real(key, default)

    monkeypatch.setattr(_cfg, "get", _patched)
    yield


@pytest.fixture(autouse=True)
def _isolate_db(tmp_path, monkeypatch):
    """Hard floor (item B, deep-dive-2026-06-08): no test may ever write the live
    consensus.db. Force db.DB_PATH to a throwaway per-test file. This is separate latent
    hardening — it would NOT have stopped the 5 hallucinated rows (those came from the live
    engine), but it stops a future test→prod write. Tests that set db.DB_PATH in-body win
    (monkeypatch precedence), exactly like _audit_flags_default_off coexists with feature
    tests. Drop any cached connection so init_db re-runs on the temp path."""
    from consensus_engine import db as _db
    monkeypatch.setattr(_db, "DB_PATH", str(tmp_path / "test_consensus.db"))
    _db._db = None
    yield
    _db._db = None


@pytest.fixture(autouse=True)
def _isolate_level_quote(monkeypatch):
    """Item C (deep-dive-2026-06-08): the display/save level-sanity gate now fetches a live
    Finnhub quote. Unit tests must not hit the network (and must be deterministic), so default
    the quote to None for the whole suite — the gate then uses the _INDEX_RANGE band for index
    scopes and fail-open (KEEP) for equities, which preserves pre-gate test behavior. Tests
    that exercise the gate's drop logic patch the quote in-body (that wins). Also clear the
    module's 60s quote cache so a real value can't leak between tests."""
    from consensus_engine.analysis import level_display_sanity as _lds
    from unittest.mock import AsyncMock
    _lds._quote_cache.clear()
    monkeypatch.setattr(_lds, "get_live_quote_price", AsyncMock(return_value=None))
    yield
    _lds._quote_cache.clear()


@pytest.fixture(autouse=True)
def _flush_narrator_cache():
    """Pass 5 Step 11 added a module-level synthesis cache to narrator.py
    (see _synthesis_cache). Without this, cached narratives leak between
    tests and break expectations like "synthesize returns empty on failure"."""
    from consensus_engine.alerts.all_command import narrator as _narrator
    _narrator.flush_synthesis_cache()
    yield
    _narrator.flush_synthesis_cache()
