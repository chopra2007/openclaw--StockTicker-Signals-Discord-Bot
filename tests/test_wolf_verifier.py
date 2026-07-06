"""Tests for the #64 trap-proof Wolf extractor->verifier layer.

These are network-free: the consolidation + confidence gate are pure functions, and the
verifier LLM call is mocked. They lock in the ANTI-TRAP invariant — the pipeline can only
VETO/DOWNGRADE a thesis, never mint one — so a future edit that reintroduces the IGV
false-bull fails CI. (The full live eval-corpus gate lives in scripts/eval_wolf_extractor.py.)
"""
import json

import pytest

from consensus_engine.analysis import wolf_verifier as wv


def _cand(scope_key, direction, agreement=1.0, intent="none", levels=None):
    return {
        "scope_type": "sector", "scope_key": scope_key, "direction": direction,
        "identifier_raw": scope_key, "position_intent": intent,
        "levels": levels or [], "snippet": "x", "_agreement": agreement, "_n_runs": 3,
    }


# ───────────────────────── consolidation (self-consistency vote) ─────────────────────────

def test_consolidate_picks_majority_direction_with_agreement():
    runs = [
        [{"scope_type": "sector", "scope_key": "IGV", "direction": "bull",
          "levels": [{"price": 100, "role": "target"}], "position_intent": "none", "identifier_raw": "IGV"}],
        [{"scope_type": "sector", "scope_key": "IGV", "direction": "bear",
          "levels": [{"price": 100, "role": "resistance"}], "position_intent": "none", "identifier_raw": "IGV"}],
        [{"scope_type": "sector", "scope_key": "IGV", "direction": "bear",
          "levels": [], "position_intent": "none", "identifier_raw": "IGV"}],
    ]
    c = wv.consolidate(runs)
    assert len(c) == 1
    assert c[0]["direction"] == "bear"                     # 2/3 bear beats 1/3 bull
    assert c[0]["_agreement"] == pytest.approx(2 / 3, abs=0.01)
    # richest representative kept (the one with a level)
    assert c[0]["levels"] == [{"price": 100, "role": "resistance"}]


def test_consolidate_never_invents_a_scope():
    runs = [[_cand("SMH", "bear")], [_cand("SMH", "bear")], []]
    c = wv.consolidate(runs)
    assert {x["scope_key"] for x in c} == {"SMH"}


# ───────────────────────── the confidence gate (deterministic) ─────────────────────────

def test_gate_contradict_vetoes_the_false_bull():
    keep, phase = wv._gate(
        _cand("IGV", "bull", 0.67),
        {"verdict": "contradict", "assertion": "planned",
         "is_expected_bounce_to_fade": True, "is_explicit_reversal": False}, 0.5)
    assert keep is False and phase == "neutral_context"


def test_gate_recap_mention_vetoed():
    keep, _ = wv._gate(
        _cand("GOOG", "bull", 1.0),
        {"verdict": "entail", "assertion": "recap_or_none",
         "is_expected_bounce_to_fade": False, "is_explicit_reversal": False}, 0.5)
    assert keep is False


def test_gate_unstable_and_unentailed_abstains():
    keep, _ = wv._gate(
        _cand("X", "bull", 0.34),
        {"verdict": "neutral", "assertion": "planned",
         "is_expected_bounce_to_fade": False, "is_explicit_reversal": False}, 0.5)
    assert keep is False


def test_gate_emits_pending_bear_as_counter_trend_bounce():
    keep, phase = wv._gate(
        _cand("IGV", "bear", 0.67),
        {"verdict": "entail", "assertion": "planned",
         "is_expected_bounce_to_fade": True, "is_explicit_reversal": False}, 0.5)
    assert keep is True and phase == "counter_trend_bounce"


def test_gate_active_intent_marks_active():
    keep, phase = wv._gate(
        _cand("SMH", "bear", 1.0, intent="started"),
        {"verdict": "entail", "assertion": "active",
         "is_expected_bounce_to_fade": False, "is_explicit_reversal": False}, 0.5)
    assert keep is True and phase == "active"


def test_gate_explicit_reversal_wins_phase():
    keep, phase = wv._gate(
        _cand("IGV", "bear", 1.0),
        {"verdict": "entail", "assertion": "planned",
         "is_expected_bounce_to_fade": False, "is_explicit_reversal": True}, 0.5)
    assert keep is True and phase == "reversal"


def test_gate_stable_view_emits_pending():
    keep, phase = wv._gate(
        _cand("DXY", "bull", 1.0),
        {"verdict": "entail", "assertion": "planned",
         "is_expected_bounce_to_fade": False, "is_explicit_reversal": False}, 0.5)
    assert keep is True and phase == "pending"


def test_gate_missing_verdict_keeps_only_stable():
    # judge returned verdicts but not for this id -> keep only if the extractor was stable
    assert wv._gate(_cand("A", "bear", 0.67), None, 0.5)[0] is True
    assert wv._gate(_cand("B", "bear", 0.34), None, 0.5)[0] is False


# ───────────────────────── verify_and_gate (mocked judge) ─────────────────────────

async def test_verify_and_gate_is_discriminative(monkeypatch):
    """The judge can only remove: a contradicted bull is vetoed and nothing is invented."""
    candidates = [
        _cand("IGV", "bull", 0.67, levels=[{"price": 100, "role": "target"}]),
        _cand("SMH", "bear", 1.0, intent="started"),
    ]

    async def fake_call(*a, **k):
        return json.dumps({"verdicts": [
            {"id": 0, "verdict": "contradict", "assertion": "planned",
             "is_expected_bounce_to_fade": True, "is_explicit_reversal": False},
            {"id": 1, "verdict": "entail", "assertion": "active",
             "is_expected_bounce_to_fade": False, "is_explicit_reversal": False},
        ]})

    monkeypatch.setattr(wv, "call_with_fallback", fake_call)
    out = await wv.verify_and_gate(candidates, "body text")
    assert {t["scope_key"] for t in out} == {"SMH"}           # IGV bull vetoed, none minted
    assert out[0]["phase"] == "active"
    assert all("_agreement" not in t and "_n_runs" not in t for t in out)  # scratch keys stripped


async def test_verify_outage_returns_none_for_safe_baseline(monkeypatch):
    async def fake_call(*a, **k):
        return ""   # judge produced no JSON = total outage

    monkeypatch.setattr(wv, "call_with_fallback", fake_call)
    out = await wv.verify_and_gate([_cand("IGV", "bull")], "body")
    assert out is None   # caller falls back to the single-shot baseline
