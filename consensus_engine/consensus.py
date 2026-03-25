"""Consensus Evaluator.

The core logic that determines whether a ticker has achieved
multi-source agreement and should trigger an alert.

A ticker passes consensus when ALL gates are satisfied:
1. Twitter: >=3 analysts within 30 minutes
2. Social: elevated on >=1 platform (Reddit, StockTwits, ApeWisdom)
3. Catalyst: credible news source explains the movement
4. Technical: all 6 technical filters pass
5. LLM Confidence: score >= 70/100
"""

import json
import logging
import time

from consensus_engine import config as cfg
from consensus_engine import db
from consensus_engine.models import ConsensusResult, AlertPayload
from consensus_engine.scanners.twitter import evaluate_twitter_consensus
from consensus_engine.scanners.social import evaluate_social_consensus
from consensus_engine.scanners.news import evaluate_catalyst
from consensus_engine.analysis.technical import verify_technical
from consensus_engine.analysis.llm_scorer import score_confidence
from consensus_engine.alerts.discord import send_alert

log = logging.getLogger("consensus_engine.consensus")


async def evaluate_ticker(ticker: str) -> ConsensusResult:
    """Run the full consensus evaluation pipeline for a single ticker.

    Gates are evaluated in order, with early termination on failure
    to minimize unnecessary API calls.
    """
    result = ConsensusResult(ticker=ticker)

    # Gate 1: Twitter consensus
    if cfg.get("consensus.require_twitter", True):
        twitter = await evaluate_twitter_consensus(ticker)
        result.twitter = twitter
        if not twitter or not twitter.passed:
            log.debug("Consensus FAIL for %s: Twitter gate (need %d analysts in %d min)",
                       ticker,
                       cfg.get("twitter.min_analysts", 3),
                       cfg.get("twitter.rolling_window_minutes", 30))
            return result

    # Gate 2: Social confirmation
    if cfg.get("consensus.require_social", True):
        social = await evaluate_social_consensus(ticker)
        result.social = social
        if not social or not social.passed:
            log.debug("Consensus FAIL for %s: Social gate", ticker)
            return result

    # Gate 3: Catalyst found
    if cfg.get("consensus.require_catalyst", True):
        catalyst = await evaluate_catalyst(ticker)
        result.catalyst = catalyst
        if not catalyst or not catalyst.passed:
            log.debug("Consensus FAIL for %s: Catalyst gate", ticker)
            return result

    # Gate 4: Technical verification
    if cfg.get("consensus.require_technical", True):
        technical = await verify_technical(ticker)
        result.technical = technical
        if not technical or not technical.all_passed:
            log.debug("Consensus FAIL for %s: Technical gate (%s)",
                       ticker,
                       f"{technical.passed_count}/{technical.total_count}" if technical else "no data")
            return result

    # Gate 5: LLM confidence score
    if cfg.get("consensus.require_llm_confidence", True):
        score, reasoning = await score_confidence(
            ticker, result.twitter, result.social, result.catalyst, result.technical,
        )
        result.llm_confidence = score
        if score < cfg.get("llm.min_confidence", 70):
            log.info("Consensus FAIL for %s: LLM confidence %.0f < 70", ticker, score)
            return result

    log.info("CONSENSUS ACHIEVED for %s! All gates passed.", ticker)
    return result


async def run_consensus_cycle():
    """Run a single consensus evaluation cycle.

    Checks all active tickers in the database and evaluates those
    with sufficient signal density.
    """
    start = time.time()

    # Get all tickers with at least 2 signals (from any source)
    active_tickers = await db.get_active_tickers(min_signals=2)
    if not active_tickers:
        log.debug("No active tickers to evaluate")
        return

    log.info("Evaluating consensus for %d active tickers: %s",
             len(active_tickers), ", ".join(active_tickers[:20]))

    alerts_sent = 0
    max_alerts = cfg.get("alerts.max_alerts_per_hour", 5)

    for ticker in active_tickers:
        # Check cooldown before expensive evaluation
        if not await db.check_alert_cooldown(ticker):
            log.debug("Skipping %s: alert cooldown active", ticker)
            continue

        result = await evaluate_ticker(ticker)

        if result.all_gates_passed:
            # Build and send alert
            payload = AlertPayload(
                ticker=ticker,
                confidence_score=result.llm_confidence,
                catalyst_summary=result.catalyst.catalyst_summary if result.catalyst else "",
                catalyst_type=result.catalyst.catalyst_type if result.catalyst else "Unknown",
                analyst_mentions=result.twitter.analysts if result.twitter else [],
                analyst_window_minutes=result.twitter.window_minutes if result.twitter else 0,
                technical=result.technical,
                consensus=result,
                news_urls=result.catalyst.source_urls if result.catalyst else [],
                price=result.technical.price if result.technical else 0,
            )

            success = await send_alert(payload)
            if success:
                alerts_sent += 1
                if alerts_sent >= max_alerts:
                    log.warning("Max alerts per cycle reached (%d), stopping", max_alerts)
                    break
        else:
            # Log which gates failed for debugging
            gates = result.gate_summary()
            failed = [g for g, passed in gates.items() if not passed]
            if failed:
                log.debug("No alert for %s: failed gates: %s", ticker, ", ".join(failed))

    elapsed = time.time() - start
    await db.record_metric("consensus_cycle_seconds", elapsed)
    log.info("Consensus cycle complete: %d tickers evaluated, %d alerts sent in %.1fs",
             len(active_tickers), alerts_sent, elapsed)
