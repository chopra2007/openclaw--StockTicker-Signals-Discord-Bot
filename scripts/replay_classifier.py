"""Offline classifier replay against the already-extracted 556 spans for 4mSyMr8PGLI.

Uses the persisted youtube_evidence_spans rows to rebuild an EvidenceBundle, then
runs classify_evidence + resolve_and_verify_catalysts WITHOUT calling Gemini.
Prints the classification result + re-runs the 7 P-verify assertions.
"""
import asyncio
import json
import sys

sys.path.insert(0, "/root/.openclaw/workspace")

from consensus_engine import db
from consensus_engine.models import EvidenceSpan, EvidenceBundle, MacroThesis
from consensus_engine.analysis.video_classifier import classify_evidence
from consensus_engine.analysis.catalyst_resolver import resolve_and_verify_catalysts

VIDEO_ID = "4mSyMr8PGLI"
PUBLISHED_AT = "2026-04-17T12:00:00Z"


async def load_bundle() -> EvidenceBundle:
    """Load spans from the JSON dump worker-pipeline's harness leaves behind."""
    with open("/tmp/yt_v2_dump.json") as f:
        dump = json.load(f)
    spans = []
    for r in dump.get("evidence_spans", []):
        tickers = json.loads(r.get("tickers_json") or "[]")
        numbers = json.loads(r.get("numbers_json") or "[]")
        dates = json.loads(r.get("dates_json") or "[]")
        spans.append(EvidenceSpan(
            ts_sec=int(r.get("ts_sec") or 0),
            quote=r.get("quote") or "",
            tickers=tickers,
            numbers=[float(n) for n in numbers if isinstance(n, (int, float))],
            dates_mentioned=dates,
        ))
    return EvidenceBundle(
        video_id=VIDEO_ID,
        duration_sec=None,
        publish_ts=PUBLISHED_AT,
        segments=[],
        spans=spans,
    )


async def main():
    bundle = await load_bundle()
    print(f"Loaded {len(bundle.spans)} spans for {VIDEO_ID}")
    if not bundle.spans:
        print("No spans in DB — run the Gemini extractor first.")
        return 1

    # Quick ticker census
    from collections import Counter
    t_cnt = Counter()
    for s in bundle.spans:
        for t in s.tickers:
            t_cnt[t] += 1
    print(f"Ticker census (top 15): {t_cnt.most_common(15)}")

    result = classify_evidence(bundle)
    resolved = await resolve_and_verify_catalysts(result.catalyst_candidates, PUBLISHED_AT)

    print(f"\nSignals: {len(result.signals)} ({sum(1 for s in result.signals if not s.suppressed)} active)")
    for s in result.signals:
        flag = "⨯" if s.suppressed else " "
        print(f"  {flag} {s.ticker:<6} {s.direction:<8} {s.conviction:<6} conf={s.classifier_confidence:.2f} reason={s.suppression_reason}")

    print(f"\nLevels: {len(result.levels)} ({sum(1 for l in result.levels if not l.suppressed)} active)")
    for l in result.levels:
        flag = "⨯" if l.suppressed else " "
        print(f"  {flag} {l.ticker:<6} {l.level_type:<12} ${l.price:<10.2f} conf={l.classifier_confidence:.2f} reason={l.suppression_reason}")

    print(f"\nSetups: {len(result.setups)}")
    for s in result.setups:
        print(f"  {s.ticker:<6} entry={s.entry_low}-{s.entry_high} stop={s.stop} tgts={s.targets} catalyst={s.catalyst_date}")

    print(f"\nResolved catalysts (first 10 of {len(resolved)}):")
    for c in resolved[:10]:
        mark = {1: "✓", 0: "?", -1: "⚠"}.get(c.verified, "?")
        print(f"  {c.ticker:<6} {c.catalyst_type:<10} mentioned={c.mentioned_date} → {c.resolved_date} {mark}")

    print(f"\nMacro:")
    m = result.macro_thesis
    print(f"  direction: {m.direction.value}")
    print(f"  themes:    {m.themes}")
    print(f"  narrative: {m.narrative[:500]!r}")

    # Assertions
    print("\n" + "=" * 78)
    print("P-verify assertions")
    print("=" * 78)
    msft_setups = [s for s in result.setups if s.ticker == "MSFT" and s.catalyst_date == "2026-04-29"]
    spy_support = [l for l in result.levels if l.ticker in ("SPY", "SPX", "ES") and l.level_type == "support" and not l.suppressed]
    ndx_support = [l for l in result.levels if l.ticker in ("NDX", "QQQ") and l.level_type == "support" and not l.suppressed]
    ndx_resist = [l for l in result.levels if l.ticker in ("NDX", "QQQ") and l.level_type == "resistance" and not l.suppressed]
    uso_short = [s for s in result.signals if s.ticker == "USO" and s.direction == "short" and not s.suppressed]
    tnv_active = [s for s in result.signals if s.ticker in ("TSLA", "NVDA") and not s.suppressed and s.conviction != "low"]
    narrative_keywords = ["sellers shut off", "draft pick", "fomo", "virgin poc"]
    narrative_hit = any(kw in m.narrative.lower() for kw in narrative_keywords)

    checks = [
        ("A1", len(msft_setups) >= 1, f"MSFT setup w/ 2026-04-29 catalyst ({len(msft_setups)} found)"),
        ("A2", len(spy_support) >= 1, f"SPY/SPX/ES has ≥1 active support ({len(spy_support)} found)"),
        ("A3", len(ndx_support) >= 1 and len(ndx_resist) >= 1,
         f"NDX support ({len(ndx_support)}) AND resistance ({len(ndx_resist)})"),
        ("A4", len(uso_short) == 0, "No active USO short signal"),
        ("A5", len(tnv_active) == 0, f"TSLA/NVDA not active hi/med ({len(tnv_active)})"),
        ("A6", narrative_hit, f"Narrative contains one of {narrative_keywords}"),
        ("A7", len({s.ts_sec // 60 for s in bundle.spans}) >= 3, "≥3 minute-buckets"),
    ]
    for code, ok, label in checks:
        print(f"  [{'✓' if ok else '✗'}] {code}: {label}")
    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"\n{passed}/{len(checks)} passed (REPLAY — no Gemini call)")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
