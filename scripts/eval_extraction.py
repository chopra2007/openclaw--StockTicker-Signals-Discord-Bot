#!/usr/bin/env python3
"""Eval harness — runs the v2 pipeline against ``evals/youtube_videos.yaml``
and reports precision/recall + compliance across the curated corpus.

The harness drives Stage A → Stage B → Stage C, then scores each video
against the hand-curated ``expected`` block in the YAML.

Metrics:
- ticker_precision / ticker_recall  (high-conviction ticker set)
- exclusion_compliance              (suppressed/neutral fraction)
- setup_match_rate                  (matched expected setups)
- level_match_rate                  (matched expected levels)
- narrative_ok                      (any narrative phrase present)
- span_count_ok                     (>= expected min)

Usage:
    python3 scripts/eval_extraction.py
    python3 scripts/eval_extraction.py --ids 4mSyMr8PGLI
    python3 scripts/eval_extraction.py --summary
    python3 scripts/eval_extraction.py --corpus evals/youtube_videos.yaml

Exits 0 if aggregate precision >= threshold, else 1 (CI guardrail).
Also exits 0 with a ``skipped`` message when ``GEMINI_API_KEY`` is unset, so
it's safe to wire into CI without secrets on feature branches.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from consensus_engine.analysis.catalyst_resolver import resolve_and_verify_catalysts  # noqa: E402
from consensus_engine.analysis.gemini_video_parser import extract_evidence_with_gemini  # noqa: E402
from consensus_engine.analysis.video_classifier import (  # noqa: E402
    ClassificationResult,
    classify_evidence,
)
from consensus_engine.models import Conviction, Direction  # noqa: E402


DEFAULT_CORPUS = ROOT / "evals" / "youtube_videos.yaml"
DEFAULT_PRECISION_THRESHOLD = 0.7

log = logging.getLogger("eval_extraction")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class VideoMetrics:
    video_id: str
    channel: str
    ticker_precision: float = 0.0
    ticker_recall: float = 0.0
    exclusion_compliance: float = 1.0
    setup_match_rate: float = 1.0
    level_match_rate: float = 1.0
    narrative_ok: bool = True
    span_count_ok: bool = True
    span_count: int = 0
    latency_ms: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            self.ticker_precision >= DEFAULT_PRECISION_THRESHOLD
            and self.ticker_recall >= DEFAULT_PRECISION_THRESHOLD
            and self.exclusion_compliance >= DEFAULT_PRECISION_THRESHOLD
            and self.setup_match_rate >= DEFAULT_PRECISION_THRESHOLD
            and self.level_match_rate >= DEFAULT_PRECISION_THRESHOLD
            and self.narrative_ok
            and self.span_count_ok
        )


# ---------------------------------------------------------------------------
# Scoring primitives (pure, testable)
# ---------------------------------------------------------------------------

def _high_conviction_actual(result: ClassificationResult) -> set[str]:
    """Tickers that the pipeline would alert on."""
    return {
        s.ticker for s in result.signals
        if not s.suppressed
        and s.direction == Direction.LONG
        and s.conviction == Conviction.HIGH
    }


def _suppressed_or_neutral_actual(result: ClassificationResult) -> set[str]:
    """Tickers that the pipeline would NOT alert on."""
    return {
        s.ticker for s in result.signals
        if s.suppressed or s.direction == Direction.NEUTRAL
    }


def _precision_recall(actual: set[str], expected: set[str]) -> tuple[float, float]:
    if not actual and not expected:
        return 1.0, 1.0
    if not actual:
        return 0.0, 0.0
    if not expected:
        return 0.0, 1.0
    hits = len(actual & expected)
    precision = hits / len(actual)
    recall = hits / len(expected)
    return precision, recall


def _match_setup(result: ClassificationResult, exp: dict) -> bool:
    ticker = exp.get("ticker")
    lo, hi = exp.get("entry_low_min"), exp.get("entry_low_max")
    cat_date = exp.get("catalyst_date")
    for s in result.setups:
        if s.ticker != ticker or s.entry_low is None:
            continue
        if lo is not None and s.entry_low < lo:
            continue
        if hi is not None and s.entry_low > hi:
            continue
        if cat_date and s.catalyst_date != cat_date:
            # Allow approximate match — raw mentioned date may resolve later;
            # here we check direct equality on either raw or resolved.
            continue
        return True
    return False


def _match_level(result: ClassificationResult, exp: dict) -> bool:
    ticker = exp.get("ticker")
    level_type = exp.get("type")
    lo, hi = exp.get("price_min"), exp.get("price_max")
    for l in result.levels:
        if l.ticker != ticker or l.level_type != level_type:
            continue
        if lo is not None and l.price < lo:
            continue
        if hi is not None and l.price > hi:
            continue
        return True
    return False


def _narrative_contains_any(result: ClassificationResult, phrases: Iterable[str]) -> bool:
    text = ""
    if result.macro_thesis is not None:
        text = (result.macro_thesis.narrative or "") + " " + (result.macro_thesis.summary or "")
    low = text.lower()
    phrases = list(phrases or [])
    if not phrases:
        return True
    return any(p.lower() in low for p in phrases)


def score_video(
    entry: dict, result: ClassificationResult, span_count: int,
) -> VideoMetrics:
    """Compute per-video metrics given expected config and the pipeline output."""
    m = VideoMetrics(
        video_id=entry["video_id"], channel=entry.get("channel", "unknown"),
        span_count=span_count,
    )
    exp = entry.get("expected") or {}

    # Tickers
    expected_high = set(exp.get("high_conviction_tickers", []) or [])
    actual_high = _high_conviction_actual(result)
    m.ticker_precision, m.ticker_recall = _precision_recall(actual_high, expected_high)

    # Exclusions
    excluded = set(exp.get("excluded_tickers", []) or [])
    suppressed_or_neutral = _suppressed_or_neutral_actual(result)
    if excluded:
        observed_tickers = {s.ticker for s in result.signals}
        relevant = excluded & observed_tickers
        if relevant:
            compliant = sum(1 for t in relevant if t in suppressed_or_neutral)
            m.exclusion_compliance = compliant / len(relevant)
        else:
            # None of the excluded tickers were observed — no violation.
            m.exclusion_compliance = 1.0

    # Setups
    expected_setups = exp.get("setups", []) or []
    if expected_setups:
        hits = sum(1 for s in expected_setups if _match_setup(result, s))
        m.setup_match_rate = hits / len(expected_setups)

    # Levels
    expected_levels = exp.get("levels", []) or []
    if expected_levels:
        hits = sum(1 for l in expected_levels if _match_level(result, l))
        m.level_match_rate = hits / len(expected_levels)

    # Narrative
    m.narrative_ok = _narrative_contains_any(
        result, exp.get("narrative_must_contain_any", []) or [],
    )

    # Span count
    min_spans = exp.get("min_span_count")
    if isinstance(min_spans, int) and min_spans > 0:
        m.span_count_ok = span_count >= min_spans

    return m


# ---------------------------------------------------------------------------
# Pipeline runner (kept thin so tests can substitute a fake)
# ---------------------------------------------------------------------------

async def _run_pipeline(entry: dict) -> tuple[ClassificationResult, int, int]:
    """Return (ClassificationResult, span_count, latency_ms) for one video."""
    video_id = entry["video_id"]
    channel = entry.get("channel", "unknown")
    publish_ts = entry.get("publish_ts", "2026-04-01T00:00:00Z")

    bundle, telemetry = await extract_evidence_with_gemini(video_id, channel, publish_ts)
    if bundle is None:
        return ClassificationResult(), 0, telemetry.latency_ms

    result = classify_evidence(bundle)
    # Enrich catalysts with resolved dates + verification status.
    result.catalyst_candidates = await resolve_and_verify_catalysts(
        result.catalyst_candidates, publish_ts,
    )
    return result, len(bundle.spans), telemetry.latency_ms


# ---------------------------------------------------------------------------
# Corpus loading + orchestration
# ---------------------------------------------------------------------------

def load_corpus(path: Path) -> list[dict]:
    """Load the YAML corpus. Returns only non-skipped entries."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    videos = data.get("videos", []) or []
    return [v for v in videos if not v.get("skip")]


def aggregate(metrics: list[VideoMetrics]) -> dict[str, float]:
    if not metrics:
        return {}
    def mean(key: str) -> float:
        return sum(getattr(m, key) for m in metrics) / len(metrics)
    return {
        "ticker_precision": mean("ticker_precision"),
        "ticker_recall": mean("ticker_recall"),
        "exclusion_compliance": mean("exclusion_compliance"),
        "setup_match_rate": mean("setup_match_rate"),
        "level_match_rate": mean("level_match_rate"),
        "narrative_ok_rate": sum(1 for m in metrics if m.narrative_ok) / len(metrics),
        "span_count_ok_rate": sum(1 for m in metrics if m.span_count_ok) / len(metrics),
    }


def _format_report(
    per_video: list[VideoMetrics], agg: dict[str, float], summary_only: bool,
) -> str:
    lines: list[str] = []
    if not summary_only:
        lines.append("=" * 72)
        lines.append(" Per-video results")
        lines.append("=" * 72)
        for m in per_video:
            status = "PASS" if m.passed else "FAIL"
            lines.append(
                f"[{status}] {m.video_id} ({m.channel}): "
                f"prec={m.ticker_precision:.2f} rec={m.ticker_recall:.2f} "
                f"excl={m.exclusion_compliance:.2f} setups={m.setup_match_rate:.2f} "
                f"levels={m.level_match_rate:.2f} narrative={'Y' if m.narrative_ok else 'N'} "
                f"spans={m.span_count} latency={m.latency_ms}ms"
            )
            for note in m.notes:
                lines.append(f"    note: {note}")
    lines.append("=" * 72)
    lines.append(" Aggregate")
    lines.append("=" * 72)
    for k, v in agg.items():
        lines.append(f"  {k}: {v:.3f}")
    return "\n".join(lines)


async def run_corpus(
    corpus_path: Path, ids: list[str] | None = None,
) -> list[VideoMetrics]:
    entries = load_corpus(corpus_path)
    if ids:
        wanted = set(ids)
        entries = [e for e in entries if e["video_id"] in wanted]
    out: list[VideoMetrics] = []
    for entry in entries:
        try:
            result, span_count, latency_ms = await _run_pipeline(entry)
            metrics = score_video(entry, result, span_count)
            metrics.latency_ms = latency_ms
        except Exception as e:
            log.exception("pipeline error for %s: %s", entry.get("video_id"), e)
            metrics = VideoMetrics(
                video_id=entry.get("video_id", "?"),
                channel=entry.get("channel", "?"),
            )
            metrics.notes.append(f"pipeline-error: {e}")
        out.append(metrics)
    return out


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--corpus", default=str(DEFAULT_CORPUS),
        help="Path to the YAML eval corpus (default: evals/youtube_videos.yaml)",
    )
    p.add_argument(
        "--ids", nargs="*", default=None,
        help="Subset of video_ids to run (default: all non-skipped).",
    )
    p.add_argument(
        "--summary", action="store_true",
        help="Print aggregate only, not per-video rows.",
    )
    p.add_argument(
        "--threshold", type=float, default=DEFAULT_PRECISION_THRESHOLD,
        help="Aggregate precision threshold for exit code (default: 0.7).",
    )
    p.add_argument(
        "--json", action="store_true",
        help="Emit machine-readable JSON instead of formatted text.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv)

    if not os.environ.get("GEMINI_API_KEY"):
        print("eval_extraction: skipped (no GEMINI_API_KEY in environment)")
        return 0

    corpus = Path(args.corpus)
    if not corpus.exists():
        print(f"eval_extraction: corpus not found at {corpus}", file=sys.stderr)
        return 2

    metrics = asyncio.run(run_corpus(corpus, args.ids))
    agg = aggregate(metrics)

    if args.json:
        print(json.dumps({
            "videos": [asdict(m) for m in metrics],
            "aggregate": agg,
        }, indent=2))
    else:
        print(_format_report(metrics, agg, args.summary))

    if not agg:
        return 0
    return 0 if agg.get("ticker_precision", 0.0) >= args.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
