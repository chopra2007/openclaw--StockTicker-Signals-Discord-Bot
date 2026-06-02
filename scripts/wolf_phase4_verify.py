#!/usr/bin/env python3
"""Phase-4 #2 shadow verification (no flag flip, no Discord post).

Applies the v18 migration, runs the REAL beneficiary precompute over the live active
theses (real RS / catalyst / flow, read-only), prints what landed in wolf_beneficiaries,
then renders a midday digest with surfacing forced ON locally and prints the beneficiaries
section. Touches only the wolf_beneficiaries table (isolation). Run as openclaw.
"""
import asyncio
import json

from consensus_engine import config as cfg, db
from consensus_engine.alerts import wolf_news
from consensus_engine.alerts.wolf_digest import gather_digest
from consensus_engine.analysis import wolf_beneficiaries as wb


async def main():
    await db.init_db()  # applies v18 (CREATE TABLE IF NOT EXISTS wolf_beneficiaries)
    ver = await (await db.get_db()).execute("SELECT MAX(version) AS v FROM schema_version")
    print("schema version:", (await ver.fetchone())["v"])

    print("\n=== running real precompute over live active theses ===")
    n = await wb.run_cycle()
    print(f"run_cycle wrote beneficiaries for {n} thesis/es")

    print("\n=== wolf_beneficiaries rows (live) ===")
    theses = await db.get_active_theses()
    for t in theses:
        rows = await db.get_beneficiaries(t["id"])
        if rows:
            print(f"\nthesis {t['id']} {t['scope_type']}/{t['scope_key']}/{t['direction']} (stage={t['stage']}):")
            for r in rows:
                sig = json.loads(r["signals_json"] or "{}")
                print(f"   {r['tier']:6} {r['ticker']:5} conf={r['confidence']:.2f} "
                      f"rs_delta={sig.get('rs_delta')} cat={sig.get('catalyst')} "
                      f"flow={sig.get('flow_bullish')} — {r['reason']}")

    # isolation check: only wolf_beneficiaries should have been written this run
    print("\n=== isolation: counts (we only write wolf_beneficiaries) ===")
    for tbl in ("wolf_beneficiaries", "ticker_signals", "signal_events"):
        cur = await (await db.get_db()).execute(f"SELECT COUNT(*) AS c FROM {tbl}")
        print(f"   {tbl}: {(await cur.fetchone())['c']} rows (informational)")

    print("\n=== rendered digest beneficiaries section (surfacing forced ON locally) ===")
    _orig = cfg.get
    def _patched(k, d=None):
        if k == "wolf.beneficiaries.enabled":
            return True
        if k == "wolf.beneficiaries.surface_in_digest":
            return True
        return _orig(k, d)
    cfg.get = _patched
    try:
        payload = await gather_digest("midday")
        embed = wolf_news.format_digest("midday", payload)
        benf = [f for f in embed["fields"] if "Bot's read" in f["name"]]
        if not benf:
            print("   (no beneficiaries section — no acting/imminent macro thesis has fresh picks)")
            print("   beneficiaries payload entries:", len(payload.get("beneficiaries", [])))
        for f in benf:
            print(f"   [{f['name']}]\n   " + f["value"].replace("\n", "\n   "))
    finally:
        cfg.get = _orig


if __name__ == "__main__":
    asyncio.run(main())
