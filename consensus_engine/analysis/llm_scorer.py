"""LLM Confidence Scoring via OpenRouter.

Sends aggregated signal data from Stages 1-3 to an LLM
for a final confidence assessment (0-100).
"""

import json
import logging
import re
from typing import Optional

import aiohttp

from consensus_engine import config as cfg
from consensus_engine.models import (
    TwitterConsensus, SocialConsensus, CatalystResult, TechnicalResult,
)

log = logging.getLogger("consensus_engine.analysis.llm_scorer")

_SYSTEM_PROMPT = """You are a stock market analyst AI. You evaluate whether a stock ticker
represents a high-confidence early-stage breakout opportunity.

Given the following multi-source signal data, provide:
1. A confidence score from 0-100 (where 70+ means high-confidence breakout)
2. A brief 1-2 sentence reasoning

Respond ONLY in this exact JSON format:
{"confidence": <number>, "reasoning": "<string>"}

Scoring guidelines:
- 80-100: Strong multi-source agreement, clear catalyst, strong technicals, high conviction
- 70-79: Good agreement across sources, identifiable catalyst, decent technicals
- 50-69: Mixed signals, weak catalyst, or incomplete confirmation
- 30-49: Mostly hype, no clear catalyst, or bearish technicals
- 0-29: Likely noise, conflicting signals, or pump-and-dump risk"""


def _sanitize_text(text: str, max_len: int = 150) -> str:
    """Sanitize external text for LLM prompt injection safety."""
    sanitized = text[:max_len].encode('utf-8', errors='replace').decode('utf-8')
    sanitized = ''.join(c for c in sanitized if c.isprintable() or c in '\n\t')
    return sanitized


def _build_user_prompt(ticker: str,
                       twitter: Optional[TwitterConsensus],
                       social: Optional[SocialConsensus],
                       catalyst: Optional[CatalystResult],
                       technical: Optional[TechnicalResult]) -> str:
    """Build the analysis prompt from aggregated signal data."""
    parts = [f"Evaluate breakout potential for ${ticker}:\n"]

    if twitter:
        parts.append(f"TWITTER/X SIGNALS:")
        parts.append(f"- {twitter.count} analysts mentioned within {twitter.window_minutes:.0f} minutes")
        parts.append(f"- Analysts: {', '.join(twitter.analysts[:10])}")
        sample_texts = twitter.raw_texts[:3]
        for t in sample_texts:
            parts.append(f"  > \"{_sanitize_text(t)}\"")
        parts.append("")

    if social:
        parts.append(f"SOCIAL SIGNALS:")
        parts.append(f"- Reddit mentions: {social.reddit_mentions}")
        parts.append(f"- StockTwits trending: {social.stocktwits_trending}")
        if social.apewisdom_rank:
            parts.append(f"- ApeWisdom rank: #{social.apewisdom_rank}")
        parts.append(f"- Platforms confirming: {social.platforms_confirming}")
        parts.append("")

    if catalyst:
        parts.append(f"NEWS CATALYST:")
        parts.append(f"- Type: {catalyst.catalyst_type}")
        parts.append(f"- Summary: {_sanitize_text(catalyst.catalyst_summary, 200)}")
        parts.append(f"- Sources: {', '.join(catalyst.news_sources[:5])}")
        parts.append(f"- Catalyst confidence: {catalyst.confidence:.0%}")
        parts.append("")

    if technical:
        parts.append(f"TECHNICAL DATA:")
        parts.append(f"- Price: ${technical.price:.2f} ({technical.price_change_pct:+.1f}%)")
        for f in technical.filters:
            status = "PASS" if f.passed else "FAIL"
            parts.append(f"  [{status}] {f.name}: {f.value} (threshold: {f.threshold})")
        parts.append(f"- Filters passed: {technical.passed_count}/{technical.total_count}")
        parts.append("")

    parts.append("Based on the above, provide your confidence score (0-100) and brief reasoning.")
    return "\n".join(parts)


async def score_confidence(ticker: str,
                           twitter: Optional[TwitterConsensus],
                           social: Optional[SocialConsensus],
                           catalyst: Optional[CatalystResult],
                           technical: Optional[TechnicalResult]) -> tuple[float, str]:
    """Get LLM confidence score for a ticker.

    Returns (score, reasoning). Score defaults to 0 on failure.
    """
    api_key = cfg.get_api_key("openrouter")
    if not api_key:
        log.warning("OpenRouter API key not configured — returning 0")
        return 0.0, "LLM scoring unavailable (no API key)"

    model = cfg.get("llm.model", "minimax/minimax-m2.5")
    max_tokens = cfg.get("llm.max_tokens", 1024)
    user_prompt = _build_user_prompt(ticker, twitter, social, catalyst, technical)
    content = ""

    try:
        async with aiohttp.ClientSession() as session:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            }

            async with session.post(url, headers=headers, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    log.warning("OpenRouter API error (%d): %s", resp.status, error_text[:200])
                    return 0.0, f"API error: {resp.status}"

                data = await resp.json()

        # Extract the response text
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return 0.0, "Empty LLM response"

        # Parse JSON from response (handle markdown code blocks)
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r'^```(?:json)?\s*', '', content)
            content = re.sub(r'\s*```$', '', content)

        parsed = json.loads(content)
        score = float(parsed.get("confidence", 0))
        reasoning = str(parsed.get("reasoning", "No reasoning provided"))

        # Clamp score to 0-100
        score = max(0, min(100, score))

        log.info("LLM score for %s: %.0f/100 — %s", ticker, score, reasoning[:100])
        return score, reasoning

    except json.JSONDecodeError as e:
        log.warning("Failed to parse LLM response for %s: %s (raw: %s)", ticker, e, content[:200])
        # Try to extract score from non-JSON response
        match = re.search(r'"?confidence"?\s*:\s*(\d+)', content)
        if match:
            score = float(match.group(1))
            return max(0, min(100, score)), "Parsed from non-standard response"
        return 0.0, f"Parse error: {e}"

    except Exception as e:
        log.warning("LLM scoring error for %s: %s", ticker, e)
        return 0.0, f"Error: {e}"
