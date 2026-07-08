"""Stage-6 — the shared insider_display renderer stays byte-identical when the new
optional insider-disclosure context is absent, and appends the line(s) when present.

Covers all four surfaces via the three render functions:
  render_cards      -> !sec + Score card
  render_all_field  -> !all Full Analysis card
  render_evidence   -> the !all write-up LLM evidence text
"""
from __future__ import annotations

from consensus_engine.alerts.insider_display import (
    InsiderSummary,
    render_cards,
    render_all_field,
    render_evidence,
)

_S = [InsiderSummary(name="Jane Doe", role="CFO", direction="Buy", shares=1000.0,
                     avg_price=100.0, value=100000.0, date="2026-07-01", n_fills=1,
                     price_lo=100.0, price_hi=100.0)]

_CTX = ["⚠️ Intent-to-sell: 2 insider(s) filed discretionary Form 144 ~$3.4M"]


def test_render_cards_byte_identical_when_absent():
    base = render_cards(_S, 0)
    assert render_cards(_S, 0, context_lines=None) == base
    assert render_cards(_S, 0, context_lines=[]) == base


def test_render_cards_appends_context():
    out = render_cards(_S, 0, context_lines=_CTX)
    assert _CTX[0] in out
    assert len(out) > len(render_cards(_S, 0))
    assert out.endswith("```")  # context stays INSIDE the fence


def test_render_all_field_byte_identical_when_absent():
    base = render_all_field(_S, 0)
    assert render_all_field(_S, 0, context_lines=None) == base
    assert render_all_field(_S, 0, context_lines=[]) == base


def test_render_all_field_appends_context():
    out = render_all_field(_S, 0, context_lines=_CTX)
    assert out.endswith(_CTX[0])
    assert len(out) > len(render_all_field(_S, 0))


def test_render_evidence_byte_identical_when_absent():
    assert render_evidence(_S, 0, True) == render_evidence(_S, 0, True, context_lines=None)
    # empty case stays empty
    assert render_evidence([], 0, False) == []
    assert render_evidence([], 0, False, context_lines=None) == []


def test_render_evidence_appends_context():
    out = render_evidence(_S, 0, True, context_lines=_CTX)
    assert out[-1] == _CTX[0]
    assert out[:-1] == render_evidence(_S, 0, True)  # everything before is unchanged
    # context surfaces even with NO open-market trades (e.g. 144 on a no-buy ticker)
    only_ctx = render_evidence([], 0, False, context_lines=_CTX)
    assert only_ctx == _CTX
