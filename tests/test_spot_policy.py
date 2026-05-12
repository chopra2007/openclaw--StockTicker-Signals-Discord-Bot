"""Tests for W1 global spot_policy."""
import pytest

from consensus_engine.analysis.spot_policy import (
    SpotAction,
    SpotPolicy,
    resolve_spot,
)


def test_valid_spot_returns_ok():
    p = resolve_spot(123.45)
    assert p.is_ok
    assert p.action == SpotAction.OK
    assert p.reason == "ok"


def test_none_demotes_for_replay():
    p = resolve_spot(None)
    assert not p.is_ok
    assert p.action == SpotAction.DEMOTE_FOR_REPLAY
    assert p.reason == "spot_is_none"


def test_zero_demotes_for_replay():
    p = resolve_spot(0.0)
    assert not p.is_ok
    assert p.action == SpotAction.DEMOTE_FOR_REPLAY
    assert p.reason == "spot_non_positive"


def test_negative_demotes_for_replay():
    p = resolve_spot(-12.5)
    assert not p.is_ok
    assert p.action == SpotAction.DEMOTE_FOR_REPLAY


def test_non_numeric_demotes_for_replay():
    p = resolve_spot("100")  # type: ignore[arg-type]
    assert not p.is_ok
    assert p.action == SpotAction.DEMOTE_FOR_REPLAY
    assert p.reason == "spot_not_numeric"


def test_int_is_ok():
    p = resolve_spot(100)
    assert p.is_ok
