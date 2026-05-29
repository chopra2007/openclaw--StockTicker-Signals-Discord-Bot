"""Reference-video E2E harness for the v2 two-stage YouTube pipeline.

Runs process_video() on 4mSyMr8PGLI with youtube.use_two_stage=true and asserts
the 7 spec checks from task #10.
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "/root/.openclaw/workspace")

from consensus_engine import db, config as cfg
from consensus_engine.scanners.youtube import process_video


VIDEO_ID = "4mSyMr8PGLI"
CHANNEL_ID = "UC-REFERENCE"


async def _seed_channel(channel_id: str, trust: float = 1.0) -> None:
    conn = await db.get_db()
    await conn.execute(
        """INSERT OR REPLACE INTO youtube_channels
           (channel_id, display_name, approved, trust_score)
           VALUES (?, ?, 1, ?)""",
        (channel_id, "ShadowTrader (ref)", trust),
    )
    await conn.commit()


async def _dump_run(video_id: str) -> dict:
    conn = await db.get_db()
    out = {}

    cur = await conn.execute(
        "SELECT id, parser_version, status, input_tokens, output_tokens, latency_ms, "
        "json_parse_ok, span_count, filter_drop_count FROM youtube_analysis_runs "
        "WHERE video_id = ? ORDER BY id DESC",
        (video_id,),
    )
    out["analysis_runs"] = [dict(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT id, ts_sec, quote, tickers_json, numbers_json, dates_json "
        "FROM youtube_evidence_spans WHERE video_id = ? ORDER BY ts_sec",
        (video_id,),
    )
    out["evidence_spans"] = [dict(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT ticker, direction, conviction, classifier_confidence, suppressed, suppression_reason, video_timestamp_sec "
        "FROM youtube_signals WHERE video_id = ?",
        (video_id,),
    )
    out["signals"] = [dict(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT ticker, level_type, price, classifier_confidence, suppressed, suppression_reason, video_timestamp_sec "
        "FROM youtube_levels WHERE video_id = ?",
        (video_id,),
    )
    out["levels"] = [dict(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT ticker, setup_type, entry_low, entry_high, stop_price, targets_json, "
        "classifier_confidence, suppressed, suppression_reason, video_timestamp_sec "
        "FROM youtube_setups WHERE video_id = ?",
        (video_id,),
    )
    out["setups"] = [dict(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT ticker, catalyst_type, mentioned_date, resolved_date, verified, suppressed "
        "FROM youtube_catalysts WHERE video_id = ?",
        (video_id,),
    )
    out["catalysts"] = [dict(r) for r in await cur.fetchall()]

    cur = await conn.execute(
        "SELECT direction, timeframe, summary, narrative FROM youtube_macro WHERE video_id = ?",
        (video_id,),
    )
    out["macro"] = [dict(r) for r in await cur.fetchall()]

    return out


async def run_once(db_path: str) -> dict:
    cfg.load_config()
    # Force two-stage on for this harness.
    cfg._config["youtube"]["use_two_stage"] = True
    cfg._config["youtube"]["legacy_fallback"] = False
    cfg._config["youtube"]["standalone_alerts"] = False  # keep it offline
    # This cron regression-tests Gemini's chart-vision output specifically, so
    # force the Gemini video path ONLY: disable the captions + whisper fallbacks
    # (now the production primary/fallbacks) so a Gemini failure surfaces honestly
    # instead of being masked by a fallback path that can't produce chart levels.
    # gemini.disabled_for_test stays False (default) so F2 runs.
    cfg._config["youtube"].setdefault("captions", {})["enabled"] = False
    cfg._config["youtube"].setdefault("whisper", {})["enabled"] = False
    cfg._config["database"]["path"] = db_path

    await db.init_db()
    await _seed_channel(CHANNEL_ID, trust=1.0)

    sem = asyncio.Semaphore(1)
    video_meta = {
        "video_id": VIDEO_ID,
        "channel_id": CHANNEL_ID,
        "title": "ShadowTrader reference video",
        "published_at": "2026-04-17T12:00:00Z",
    }

    with tempfile.TemporaryDirectory() as td:
        await process_video(video_meta, sem, ["en"], td)

    return await _dump_run(VIDEO_ID)


def evaluate(result: dict) -> tuple[list[tuple[str, bool, str]], dict]:
    """Return a list of (assertion_name, passed, detail) + the dump."""
    checks = []

    # A1 — MSFT setup with catalyst_date 2026-04-29
    msft_setups = [s for s in result["setups"] if s["ticker"] == "MSFT" and not s["suppressed"]]
    msft_catalysts = [
        c for c in result["catalysts"]
        if c["ticker"] == "MSFT" and c.get("resolved_date") == "2026-04-29"
    ]
    checks.append((
        "A1: MSFT setup exists AND MSFT catalyst resolved_date=2026-04-29",
        bool(msft_setups) and bool(msft_catalysts),
        f"msft_setups={len(msft_setups)}, msft_2026-04-29_catalysts={len(msft_catalysts)}",
    ))

    # A2 — SPY has at least one support level
    spy_supports = [lv for lv in result["levels"]
                    if lv["ticker"] == "SPY" and lv["level_type"] == "support" and not lv["suppressed"]]
    checks.append((
        "A2: SPY has ≥1 support level",
        bool(spy_supports),
        f"spy_support_count={len(spy_supports)}",
    ))

    # A3 — NDX has support ~26165 AND resistance ~27200
    ndx_levels = [lv for lv in result["levels"] if lv["ticker"] == "NDX" and not lv["suppressed"]]
    ndx_support_26165 = any(lv for lv in ndx_levels
                            if lv["level_type"] == "support" and abs(lv["price"] - 26165) <= 100)
    ndx_resistance_27200 = any(lv for lv in ndx_levels
                               if lv["level_type"] == "resistance" and abs(lv["price"] - 27200) <= 100)
    checks.append((
        "A3: NDX support≈26165 AND resistance≈27200",
        ndx_support_26165 and ndx_resistance_27200,
        f"ndx_levels={len(ndx_levels)} support≈26165={ndx_support_26165} resistance≈27200={ndx_resistance_27200}",
    ))

    # A4 — No USO short signal unsuppressed
    uso_shorts = [s for s in result["signals"]
                  if s["ticker"] == "USO" and s["direction"] == "short" and not s["suppressed"]]
    checks.append((
        "A4: No unsuppressed USO short",
        not uso_shorts,
        f"uso_unsuppressed_short_count={len(uso_shorts)}",
    ))

    # A5 — TSLA/NVDA signals absent OR suppressed
    rogue = [s for s in result["signals"]
             if s["ticker"] in ("TSLA", "NVDA") and not s["suppressed"]]
    checks.append((
        "A5: TSLA/NVDA absent OR suppressed",
        not rogue,
        f"unsuppressed_tsla_nvda={[s['ticker'] for s in rogue]}",
    ))

    # A6 — narrative contains one of the expected phrases
    narratives = " ".join(
        (m.get("narrative") or "") + " " + (m.get("summary") or "")
        for m in result["macro"]
    ).lower()
    markers = ["sellers shut off", "draft pick", "fomo", "virgin poc"]
    hit = [m for m in markers if m in narratives]
    checks.append((
        "A6: narrative contains one of ['Sellers Shut Off','draft pick','FOMO','Virgin POC']",
        bool(hit),
        f"hits={hit} narrative_len={len(narratives)}",
    ))

    # A7 — segments ≥3 (derived from evidence spans — we don't persist segments,
    # but Stage A returns them. So read the latest analysis run's span_count as proxy:
    # if spans cover many distinct timestamps, segments were present. We use the
    # Stage A bundle indirectly — approximate by checking distinct ts_sec buckets.)
    spans = result["evidence_spans"]
    distinct_minutes = len({(s["ts_sec"] or 0) // 60 for s in spans})
    checks.append((
        "A7: evidence spans cover ≥3 distinct minute-buckets (segments proxy)",
        distinct_minutes >= 3,
        f"distinct_minute_buckets={distinct_minutes} total_spans={len(spans)}",
    ))

    return checks, result


async def main():
    print("=" * 70)
    print("v2 reference-video E2E harness — 4mSyMr8PGLI")
    print("=" * 70)

    with tempfile.TemporaryDirectory() as td:
        db_path = os.path.join(td, "p_verify.db")

        print("\n[1] First run ...")
        await db.close_db()  # ensure clean slate
        dump1 = await run_once(db_path)
        print(f"    analysis_runs: {len(dump1['analysis_runs'])}")
        print(f"    evidence_spans: {len(dump1['evidence_spans'])}")
        print(f"    signals: {len(dump1['signals'])}")
        print(f"    levels: {len(dump1['levels'])}")
        print(f"    setups: {len(dump1['setups'])}")
        print(f"    catalysts: {len(dump1['catalysts'])}")
        print(f"    macro rows: {len(dump1['macro'])}")

        if dump1["analysis_runs"]:
            run = dump1["analysis_runs"][0]
            print(f"    run telemetry: tokens in/out {run['input_tokens']}/{run['output_tokens']}, "
                  f"latency={run['latency_ms']}ms, json_ok={run['json_parse_ok']}, "
                  f"span_count={run['span_count']}, filter_drops={run['filter_drop_count']}")

        print("\n[2] Idempotency: second run on the same video ...")
        conn = await db.get_db()
        before_levels = (await (await conn.execute(
            "SELECT COUNT(*) AS c FROM youtube_levels WHERE video_id = ?",
            (VIDEO_ID,),
        )).fetchone())["c"]
        before_signals = (await (await conn.execute(
            "SELECT COUNT(*) AS c FROM youtube_signals WHERE video_id = ?",
            (VIDEO_ID,),
        )).fetchone())["c"]
        before_spans = (await (await conn.execute(
            "SELECT COUNT(*) AS c FROM youtube_evidence_spans WHERE video_id = ?",
            (VIDEO_ID,),
        )).fetchone())["c"]

        # Reset "processed" flag and rerun
        await conn.execute(
            "UPDATE youtube_videos SET transcript_status='pending' WHERE video_id = ?",
            (VIDEO_ID,),
        )
        await conn.commit()
        await db.close_db()
        dump2 = await run_once(db_path)

        conn = await db.get_db()
        after_levels = (await (await conn.execute(
            "SELECT COUNT(*) AS c FROM youtube_levels WHERE video_id = ?",
            (VIDEO_ID,),
        )).fetchone())["c"]
        after_signals = (await (await conn.execute(
            "SELECT COUNT(*) AS c FROM youtube_signals WHERE video_id = ?",
            (VIDEO_ID,),
        )).fetchone())["c"]
        after_spans = (await (await conn.execute(
            "SELECT COUNT(*) AS c FROM youtube_evidence_spans WHERE video_id = ?",
            (VIDEO_ID,),
        )).fetchone())["c"]

        print(f"    levels: before={before_levels} after={after_levels} "
              f"{'IDEMPOTENT' if after_levels == before_levels else 'DRIFT'}")
        print(f"    signals: before={before_signals} after={after_signals} "
              f"{'IDEMPOTENT' if after_signals == before_signals else 'DRIFT'}")
        print(f"    evidence_spans: before={before_spans} after={after_spans} "
              f"{'IDEMPOTENT' if after_spans == before_spans else 'DRIFT'}")
        # NOTE: this is REPORT-ONLY, not a pass/fail gate. Gemini is a live LLM
        # whose extraction varies run-to-run, so exact-count equality across two
        # real runs cannot hold (and never could once the chain stopped being
        # mocked). Re-process dedup/replace is a separate persistence concern.
        idempotent = (
            after_levels == before_levels
            and after_signals == before_signals
            and after_spans == before_spans
        )

        await db.close_db()

        print("\n[3] Assertions (A1-A7) ...")
        checks, _ = evaluate(dump1)
        passed = 0
        for name, ok, detail in checks:
            mark = "✅" if ok else "❌"
            print(f"    {mark} {name}")
            print(f"        {detail}")
            if ok:
                passed += 1

        print("\n" + "=" * 70)
        print(f"SUMMARY: {passed}/{len(checks)} assertions passed, "
              f"idempotency={'PASS' if idempotent else 'DRIFT (informational; live-LLM)'}")
        print("=" * 70)

        # Write full dump for inspection. Use a per-user temp path so a file left
        # by a prior run as a different user can't cause a PermissionError crash.
        out_path = Path(tempfile.gettempdir()) / f"yt_v2_dump_{os.getuid()}.json"
        try:
            out_path.write_text(json.dumps(dump1, indent=2, default=str))
            print(f"Full dump written to {out_path}")
        except OSError as e:
            print(f"(could not write dump to {out_path}: {e})")

        # Exit gates on the A1-A7 assertions only. Idempotency is informational
        # (see note above). A1/A2/A3 currently require TODO #17 Task C to wire
        # visual_evidence (chart numbers) into youtube_levels/setups/catalysts.
        return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
