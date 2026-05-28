"""Snapshot tests for Layer 1 prompt hardening constraints."""


def test_evidence_prompt_has_grounding_constraint():
    from consensus_engine.analysis.gemini_video_parser import _EVIDENCE_PROMPT
    assert "do NOT infer tickers" in _EVIDENCE_PROMPT or \
           "Do NOT infer tickers" in _EVIDENCE_PROMPT
    assert "literally spoken" in _EVIDENCE_PROMPT.lower()
