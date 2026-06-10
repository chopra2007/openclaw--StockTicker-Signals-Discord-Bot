"""Common-recency-window synchronizer (signal-features-2026-06-09 Phase 2).

Proves the §8.B contract: a stale leg (older than its source's freshness cap)
does NOT count toward multi-source confluence/contradiction — no phantom
confluence — while fresh legs, unconfigured sources, and the disabled flag
keep legs flowing unchanged.
"""

from datetime import datetime, timedelta, timezone

from consensus_engine import config as cfg
from consensus_engine.analysis.recency_window import SourceLeg, filter_fresh, is_fresh

NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _ago(minutes: float) -> datetime:
    return NOW - timedelta(minutes=minutes)


def test_fresh_leg_inside_cap_kept():
    # sec cap is 120 min (config) — a 30-min-old Form-4 counts.
    assert is_fresh("sec", _ago(30), now=NOW) is True


def test_stale_leg_outside_cap_dropped():
    # The phantom-confluence case: a 12h-old leg paired with a 1-min-old one.
    legs = [
        SourceLeg(source="sec", as_of=_ago(1)),
        SourceLeg(source="finra_short_volume", as_of=_ago(12 * 60)),  # cap 1440 — kept
        SourceLeg(source="sec", as_of=_ago(121)),                     # cap 120 — dropped
    ]
    kept = filter_fresh(legs, now=NOW)
    assert len(kept) == 2
    assert all(leg.as_of != _ago(121) for leg in kept)


def test_null_timestamp_is_stale():
    # Mirrors the I1 null-ts rule: unknown as-of can never count as fresh.
    assert is_fresh("tweet", None, now=NOW) is False
    assert filter_fresh([SourceLeg(source="tweet", as_of=None)], now=NOW) == []


def test_unparseable_timestamp_is_stale():
    assert is_fresh("options", "not-a-date", now=NOW) is False


def test_naive_datetime_assumed_utc():
    naive = (NOW - timedelta(minutes=10)).replace(tzinfo=None)
    assert is_fresh("options", naive, now=NOW) is True  # cap 90


def test_iso_string_and_epoch_accepted():
    assert is_fresh("youtube", _ago(60).isoformat(), now=NOW) is True
    assert is_fresh("youtube", _ago(60).timestamp(), now=NOW) is True


def test_unconfigured_source_kept():
    # Caps are opt-in per source — an unknown source must not silently delete signal.
    assert is_fresh("some_future_source", _ago(10_000), now=NOW) is True


def test_far_future_timestamp_is_bad_data():
    assert is_fresh("sec", NOW + timedelta(hours=2), now=NOW) is False
    # Small clock skew is tolerated.
    assert is_fresh("sec", NOW + timedelta(minutes=5), now=NOW) is True


def test_disabled_flag_is_noop(monkeypatch):
    _real = cfg.get

    def _patched(key, default=None):
        if key == "features.recency_window.enabled":
            return False
        return _real(key, default)

    monkeypatch.setattr(cfg, "get", _patched)
    legs = [SourceLeg(source="sec", as_of=None), SourceLeg(source="sec", as_of=_ago(9999))]
    assert len(filter_fresh(legs, now=NOW)) == 2
    assert is_fresh("sec", None, now=NOW) is True
