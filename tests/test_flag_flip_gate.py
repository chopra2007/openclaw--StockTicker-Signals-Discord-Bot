"""Unit test for the item-F flag-flip gate's pure logic (deterministic, no git/network)."""
import importlib.util
from pathlib import Path

_GATE = Path(__file__).resolve().parent.parent / "scripts" / "flag_flip_gate.py"
_spec = importlib.util.spec_from_file_location("flag_flip_gate", _GATE)
gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate)


def test_flatten_bools_names_nested_flags():
    cfg = {
        "wolf": {"vision": {"enabled": False, "pace_seconds": 8},
                 "confluence": {"links_enabled": True}},
        "social": {"stocktwits_enabled": False},
        "top_level": True,
    }
    flat = gate._flatten_bools(cfg)
    # nested booleans get their FULL dotted path (the grep bug collapsed these to one leaf)
    assert flat["wolf.vision.enabled"] is False
    assert flat["wolf.confluence.links_enabled"] is True
    assert flat["social.stocktwits_enabled"] is False
    assert flat["top_level"] is True
    # non-bool leaves are excluded
    assert "wolf.vision.pace_seconds" not in flat


def test_flip_detection_off_to_on_only():
    base = gate._flatten_bools({"a": {"x": False}, "b": True, "c": False})
    head = gate._flatten_bools({"a": {"x": True}, "b": True, "c": False, "d": True})
    flips = [k for k, v in head.items() if v is True and base.get(k) is False]
    # a.x flipped OFF->ON; b unchanged (already True); c unchanged; d is NEW (not a flip)
    assert flips == ["a.x"]


def test_two_nested_enabled_flags_are_distinct():
    """The exact grep failure: two different nested `enabled` flags must NOT collapse to one."""
    base = gate._flatten_bools({"x": {"enabled": False}, "y": {"enabled": False}})
    head = gate._flatten_bools({"x": {"enabled": True}, "y": {"enabled": False}})
    flips = [k for k, v in head.items() if v is True and base.get(k) is False]
    assert flips == ["x.enabled"]  # only x flipped; y stays — grep would have matched both
