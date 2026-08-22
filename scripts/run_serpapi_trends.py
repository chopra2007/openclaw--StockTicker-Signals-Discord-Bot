#!/usr/bin/env python3
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "SERPAPI2_API_KEY" in os.environ and not os.environ.get("SERPAPI_API_KEY"):
    os.environ["SERPAPI_API_KEY"] = os.environ["SERPAPI2_API_KEY"]

async def main():
    from consensus_engine import config as cfg, db
    from consensus_engine.scanners.social import scan_google_trends_serpapi, scan_apewisdom
    from consensus_engine.models import TickerSignal, SourceType, Sentiment
    from consensus_engine.main import _is_weekend_pause
    from consensus_engine.utils.http import close_session
    if _is_weekend_pause():
        print("SerpAPI Google Trends: Skipped (weekend pause)")
        return
    await db.init_db()
    try:
        db_tickers = await db.get_active_tickers(min_signals=1)
        ape_signals = await scan_apewisdom()
        ape_tickers = [s.ticker for s in ape_signals[:20]]
        seen = set(db_tickers)
        combined = list(db_tickers) + [t for t in ape_tickers if t not in seen]
        active = combined[:10]
        if not active:
            print("SerpAPI Google Trends: No tickers to scan.")
            return
        trends = await scan_google_trends_serpapi(active)
        if not trends:
            print("SerpAPI Google Trends: No data returned.")
            return
        for ticker, delta in trends.items():
            await db.insert_signal(TickerSignal(
                ticker=ticker, source_type=SourceType.GOOGLE_TRENDS,
                source_detail=f"serpapi delta={delta:.1f}",
                raw_text=f"Google Trends (SerpAPI): {delta:.1f}%",
                sentiment=Sentiment.BULLISH if delta > 0 else Sentiment.NEUTRAL))

        print("SerpAPI Google Trends Results:")
        for ticker, delta in sorted(trends.items(), key=lambda x: -abs(x[1]))[:10]:
            sign = "+" if delta >= 0 else ""
            print(f"  ${ticker}: {sign}{delta:.1f}%")
    finally:
        await db.close_db()
        await close_session()

if __name__ == "__main__":
    asyncio.run(main())
