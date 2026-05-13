"""F3 hallucination grounding: validate Whisper-extracted tickers against transcript text.

After Groq Whisper produces a transcript, the LLM extracts ticker candidates.
This module checks each candidate is literally supported by the transcript text,
reusing the grounding logic from ticker_grounding.py.

Tickers not found in the transcript are tagged grounding_status='ungrounded'.
The downstream classifier discards 'ungrounded' spans.
"""
from __future__ import annotations

import logging

from consensus_engine.analysis.ticker_grounding import is_ticker_grounded

log = logging.getLogger("consensus_engine.analysis.hallucination_grounding")

_UNGROUNDED = "ungrounded"
_GROUNDED = "grounded"


def ground_transcript_tickers(
    tickers: list[str],
    transcript: str,
) -> list[dict]:
    """Return tickers annotated with grounding_status.

    Each result dict: {"ticker": str, "grounding_status": "grounded"|"ungrounded"}.
    A ticker is grounded if is_ticker_grounded() finds it literally in transcript.
    """
    results = []
    for ticker in tickers:
        status = _GROUNDED if is_ticker_grounded(ticker, transcript) else _UNGROUNDED
        if status == _UNGROUNDED:
            log.debug("hallucination_grounding: %s not found in transcript — ungrounded", ticker)
        results.append({"ticker": ticker, "grounding_status": status})
    return results


def all_ungrounded(grounded_results: list[dict]) -> bool:
    """True if every ticker in the grounding result is ungrounded."""
    return all(r["grounding_status"] == _UNGROUNDED for r in grounded_results)
