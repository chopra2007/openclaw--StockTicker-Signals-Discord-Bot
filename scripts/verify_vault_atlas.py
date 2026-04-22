"""End-to-end smoke test for Vault/Atlas/Alfred.

Usage: python3 scripts/verify_vault_atlas.py
Requires: OPENROUTER_API_KEY, DISCORD_BOT_TOKEN, DISCORD_BRIEFING_CHANNEL_ID.
Runs Atlas for NVDA, then Alfred in DRY-RUN mode (no Discord post).
"""
import asyncio
import sys

sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv("/root/.openclaw/.env")

from consensus_engine import db, config as cfg
from consensus_engine.research.atlas import enqueue_atlas_job, run_one_job
from consensus_engine.briefing import alfred
from consensus_engine.research.sessions import current_et_session


async def main():
    await db.init_db()

    print("=== Atlas: NVDA ===")
    job_id = await enqueue_atlas_job("NVDA", "manual")
    print("Enqueued:", job_id)
    ran = await run_one_job()
    print("Ran:", ran)

    sections = await db.get_research_sections("NVDA")
    for src, row in sections.items():
        print(f"  {src}: status={row['status']} "
              f"has_content={bool(row['content'])} "
              f"has_last_good={bool(row.get('last_good_content'))}")

    vault_path = cfg.get("vault.path", "/root/.openclaw/vault")
    print(f"\n=== Vault note ({vault_path}/tickers/NVDA.md) ===")
    try:
        with open(f"{vault_path}/tickers/NVDA.md") as fh:
            print(fh.read()[:2000])
    except FileNotFoundError:
        print("(not written — check logs above)")

    print("\n=== Alfred: DRY-RUN ===")
    cfg.dry_run = True
    start, end, key = current_et_session()
    data = await alfred.build_briefing_data(start, end)
    print(f"Session {key}: {len(data['alerts'])} alerts, "
          f"{len(data['levels'])} levels, "
          f"{len(data['top_tickers'])} top tickers")
    await alfred.post_briefing(key, data)
    run = await db.get_briefing_run(key)
    print(f"briefing_runs[{key}].status = {run['status']}")


if __name__ == "__main__":
    asyncio.run(main())
