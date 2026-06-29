"""C4 (reliability-hardening): no blank thesis / silent score-collapse.

When every model in the configured chain 429s at once (shared openrouter
account quota), call_with_fallback returns "" and score_confidence today
returns (0.0, "LLM scoring unavailable (all models failed)") — a silent,
misleading-looking result. The instant alert still fires (it is base_score
gated, LLM-independent; the LLM only adds bounded bonus points), but the thesis
is blank and the bonus is lost.

C4 (flag llm.score_fallback_enabled, default OFF): retry once on a dedicated
non-openrouter (Groq) chain; if that also fails, emit an ERROR + increment a
counter and return an HONEST degraded note ("(thesis unavailable — ...)")
instead of a silent blank. Flag OFF = byte-identical to today."""
import pytest

from consensus_engine.analysis import llm_scorer


def _cfg(monkeypatch, *, fallback_on, groq_model="groq/llama-3.3-70b-versatile"):
    real = llm_scorer.cfg.get
    cfgmap = {
        "llm.score_fallback_enabled": fallback_on,
        "llm.groq_fallback_model": groq_model,
        "llm.max_tokens": 1024,
    }
    monkeypatch.setattr(llm_scorer.cfg, "get", lambda k, d=None: cfgmap.get(k, real(k, d)))
    monkeypatch.setattr(llm_scorer.cfg, "get_api_key", lambda k: "fake-key")


def _patch_cwf(monkeypatch, primary_result, groq_result):
    seen = {"primary": 0, "groq": 0}

    async def fake(role, messages, **kw):
        if kw.get("chain"):
            seen["groq"] += 1
            return groq_result
        seen["primary"] += 1
        return primary_result

    monkeypatch.setattr(llm_scorer, "call_with_fallback", fake)
    return seen


async def test_flag_off_unchanged(monkeypatch):
    _cfg(monkeypatch, fallback_on=False)
    seen = _patch_cwf(monkeypatch, primary_result="", groq_result='{"confidence":80,"reasoning":"x"}')
    score, reasoning = await llm_scorer.score_confidence("AAPL", None, None, None, None)
    assert score == 0.0
    assert reasoning == "LLM scoring unavailable (all models failed)"
    assert seen["groq"] == 0, "flag OFF must NOT attempt the Groq fallback"


async def test_groq_fallback_recovers(monkeypatch):
    _cfg(monkeypatch, fallback_on=True)
    seen = _patch_cwf(monkeypatch, primary_result="",
                      groq_result='{"confidence": 72, "reasoning": "groq carried the thesis"}')
    score, reasoning = await llm_scorer.score_confidence("AAPL", None, None, None, None)
    assert score == 72.0
    assert reasoning == "groq carried the thesis"
    assert seen["groq"] == 1, "must retry once on the Groq chain when primary is empty"


async def test_all_fail_honest_degrade_and_counter(monkeypatch, caplog):
    _cfg(monkeypatch, fallback_on=True)
    _patch_cwf(monkeypatch, primary_result="", groq_result="")
    before = llm_scorer._llm_unavailable_count
    with caplog.at_level("ERROR"):
        score, reasoning = await llm_scorer.score_confidence("AAPL", None, None, None, None)
    assert score == 0.0
    assert "unavailable" in reasoning.lower()
    assert reasoning != "LLM scoring unavailable (all models failed)", \
        "the C4 honest note must be distinct from the silent flag-off string"
    assert llm_scorer._llm_unavailable_count == before + 1, "must increment the unavailable counter"
    assert any(r.levelname == "ERROR" for r in caplog.records), "must ERROR-log the total failure"


async def test_no_groq_model_skips_retry(monkeypatch):
    _cfg(monkeypatch, fallback_on=True, groq_model="")
    seen = _patch_cwf(monkeypatch, primary_result="", groq_result="should-not-be-used")
    score, reasoning = await llm_scorer.score_confidence("AAPL", None, None, None, None)
    assert seen["groq"] == 0, "no configured Groq model -> no retry"
    assert score == 0.0
    assert "unavailable" in reasoning.lower()


async def test_primary_success_no_fallback(monkeypatch):
    _cfg(monkeypatch, fallback_on=True)
    seen = _patch_cwf(monkeypatch, primary_result='{"confidence": 65, "reasoning": "fine"}',
                      groq_result="unused")
    score, reasoning = await llm_scorer.score_confidence("AAPL", None, None, None, None)
    assert score == 65.0 and reasoning == "fine"
    assert seen["groq"] == 0, "a healthy primary must not trigger the Groq fallback"
