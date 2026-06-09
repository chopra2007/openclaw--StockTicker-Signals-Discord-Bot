"""Tests for the OpenRouter migration of Wolf chart vision (ITEM #4).

Confirms _call_vision_image builds an OpenAI-style content array carrying the
image as a base64 data URL, parses+validates the model response, and falls
through to the next model when the first returns an empty string. read_chart is
exercised end-to-end (with the budget + fetch stubbed) to confirm the byte-based
mime sniff and that the validated dict is returned.
"""
import base64
import json

import pytest

from consensus_engine.analysis import wolf_vision


_GOOD_JSON = json.dumps({
    "instrument": "QQQ",
    "direction": "bearish",
    "levels": [{"price": 735.5, "role": "support", "confidence": 0.9}],
})

# 2-byte JPEG magic header so the byte-sniff resolves to image/jpeg.
_FAKE_JPEG = b"\xff\xd8fake-jpeg-bytes"
_FAKE_PNG = b"\x89PNGfake-png-bytes"


def _make_capture(returns):
    """Return (fake_vision_completion, calls). Each element of `returns` is either a
    plain content string (treated as a 200 success/parse) or a (content, status, body)
    tuple for failure injection. Mirrors the new vision_completion (content, status, body)."""
    seq = list(returns)
    calls = []

    async def fake_vision_completion(model, messages, *, max_tokens=512, temperature=0.0):
        calls.append({"model": model, "messages": messages,
                      "max_tokens": max_tokens, "temperature": temperature})
        idx = len(calls) - 1
        item = seq[idx] if idx < len(seq) else seq[-1]  # repeat last -> pool-size agnostic
        if isinstance(item, tuple):
            return item
        return (item, 200, item)  # content -> 200 success

    return fake_vision_completion, calls


@pytest.mark.asyncio
async def test_call_vision_builds_data_url_and_parses(monkeypatch):
    fake_cc, calls = _make_capture([_GOOD_JSON])
    monkeypatch.setattr(wolf_vision, "vision_completion", fake_cc)

    parsed = await wolf_vision._call_vision_image(_FAKE_JPEG, "image/jpeg")

    # parsed -> validated gives the right dict.
    assert parsed is not None
    v = wolf_vision._validate(parsed, recent_price=737.0)
    assert v["instrument"] == "QQQ"
    assert v["direction"] == "bearish"
    assert len(v["levels"]) == 1 and v["levels"][0]["price"] == 735.5

    # exactly one model call; messages is a content-array carrying a data: image URL.
    assert len(calls) == 1
    messages = calls[0]["messages"]
    assert isinstance(messages, list) and messages[0]["role"] == "user"
    content = messages[0]["content"]
    parts = {p["type"]: p for p in content}
    assert "text" in parts and "image_url" in parts
    data_url = parts["image_url"]["image_url"]["url"]
    assert data_url.startswith("data:image/jpeg;base64,")
    b64 = data_url.split(",", 1)[1]
    assert base64.b64decode(b64) == _FAKE_JPEG
    # temperature pinned to 0.0 for deterministic extraction.
    assert calls[0]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_call_vision_rotates_on_quota_to_second_model(monkeypatch):
    # First model 429 (quota) -> rotate to the second model, which succeeds.
    # Force a 2-model pool in-body so this tests the rotation LOGIC regardless of the
    # production config (prod is a single paid model since the 2026-06-09 go-live).
    pool = ["model-a", "model-b"]
    _real_get = wolf_vision.cfg.get
    monkeypatch.setattr(wolf_vision.cfg, "get",
                        lambda k, d=None: pool if k == "wolf.vision.models"
                        else (True if k == "wolf.vision.rotation_helps" else _real_get(k, d)))
    fake_cc, calls = _make_capture([("", 429, "rate limit exceeded"), _GOOD_JSON])
    monkeypatch.setattr(wolf_vision, "vision_completion", fake_cc)

    parsed = await wolf_vision._call_vision_image(_FAKE_JPEG, "image/jpeg")

    assert parsed is not None and parsed["instrument"] == "QQQ"
    assert len(calls) == 2
    assert calls[0]["model"] == "model-a"
    assert calls[1]["model"] == "model-b"


@pytest.mark.asyncio
async def test_call_vision_all_models_quota_returns_none(monkeypatch):
    fake_cc, calls = _make_capture([("", 429, "rate limit")])  # every call -> 429 (repeat last)
    monkeypatch.setattr(wolf_vision, "vision_completion", fake_cc)
    n_models = len(wolf_vision.cfg.get("wolf.vision.models", wolf_vision._DEFAULT_VISION_MODELS))

    parsed = await wolf_vision._call_vision_image(_FAKE_PNG, "image/png")

    assert parsed is None
    assert len(calls) == n_models  # one quota attempt per pool model, then exhausted


@pytest.mark.asyncio
async def test_read_chart_sniffs_png_mime_and_returns_validated(monkeypatch):
    fake_cc, calls = _make_capture([_GOOD_JSON])
    monkeypatch.setattr(wolf_vision, "vision_completion", fake_cc)

    async def fake_fetch(url):
        return _FAKE_PNG

    monkeypatch.setattr(wolf_vision, "fetch_chart_bytes", fake_fetch)

    class _Budget:
        async def can_consume(self, *a, **k):
            return True

        async def consume(self, *a, **k):
            return True

    import consensus_engine.engine as engine
    monkeypatch.setattr(engine, "BudgetManager", lambda *a, **k: _Budget())

    result = await wolf_vision.read_chart(
        "https://wolfonwallstreet-trade.com/wp-content/uploads/x.jpg",
        recent_price=737.0,
    )

    assert result is not None
    assert result["instrument"] == "QQQ"
    assert result["source_url"].endswith("x.jpg")
    # bytes had a PNG-ish header (not 0xFFD8), so mime sniffs to image/png.
    data_url = calls[0]["messages"][0]["content"][1]["image_url"]["url"]
    assert data_url.startswith("data:image/png;base64,")
