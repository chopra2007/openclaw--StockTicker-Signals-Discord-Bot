# Open Questions

## speed-accuracy-optimization - 2026-03-30
- [ ] Should the parallel news cascade preserve tier preference order (Finnhub > Google > Brave > SearXNG) when multiple tiers return results simultaneously? — Affects whether we use FIRST_COMPLETED or gather-then-pick-best
- [ ] What is the acceptable API call budget per cycle on Finnhub free tier (60 req/min)? — Parallel cascade + scanner loops could exceed this if not coordinated
- [ ] Should the persistent xref cache use the existing consensus.db or a separate cache.db? — Separate DB avoids WAL contention but adds complexity
- [ ] Is the current 5-minute xref cache TTL appropriate, or should it be configurable per-ticker based on volatility? — High-volatility tickers may need shorter TTL
- [ ] After Phase 2.1 (parallel cascade), should we still respect the tier ordering in config, or make it purely "first valid result wins"? — User may want to prioritize Finnhub for data quality reasons
