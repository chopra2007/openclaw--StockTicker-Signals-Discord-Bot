"""Hybrid multimodal router: vision first (if images), then text synthesis."""

import asyncio
import time
from typing import Any

from .text_model import analyze_tweet
from .vision_model import analyze_image

_VISION_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 900


def _cache_get(url: str) -> dict[str, Any] | None:
    entry = _VISION_CACHE.get(url)
    if not entry:
        return None
    ts, payload = entry
    if (time.time() - ts) > _CACHE_TTL_SECONDS:
        _VISION_CACHE.pop(url, None)
        return None
    return payload


def _cache_set(url: str, payload: dict[str, Any]) -> None:
    _VISION_CACHE[url] = (time.time(), payload)


async def _vision_for_url(image_url: str) -> dict[str, Any]:
    cached = _cache_get(image_url)
    if cached is not None:
        return cached
    try:
        payload = await analyze_image(image_url)
    except Exception:
        payload = {
            "source": "",
            "ticker": "",
            "analysis_type": "",
            "scenarios": {
                "bull_case": {"price": None, "details": ""},
                "base_case": {"price": None, "details": ""},
                "bear_case": {"price": None, "details": ""},
            },
            "probabilities": {},
            "sentiment": "neutral",
            "confidence": 0.0,
            "summary": "",
        }
    _cache_set(image_url, payload)
    return payload


async def process_tweet(tweet: dict[str, Any]) -> dict[str, Any]:
    """Route tweet through hybrid pipeline.

    if image exists -> vision model(s) -> text model with vision context
    else -> text model only
    """
    image_urls = tweet.get("image_urls") or []
    if not image_urls and tweet.get("image_url"):
        image_urls = [tweet["image_url"]]

    vision_outputs: list[dict[str, Any]] = []
    if image_urls:
        tasks = [_vision_for_url(url) for url in image_urls]
        vision_outputs = await asyncio.gather(*tasks)

    text_output = await analyze_tweet(
        tweet_text=tweet.get("text", ""),
        analyst=tweet.get("analyst", ""),
        vision_output=vision_outputs,
    )

    text_output["vision_outputs"] = vision_outputs
    return text_output
