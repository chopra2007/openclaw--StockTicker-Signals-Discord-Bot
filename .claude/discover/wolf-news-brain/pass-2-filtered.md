# Pass 2 — Filtered, Prioritized, Safeguarded (wolf-news-brain)

All Pass-1 core components (C1–C9) survive: each is **spec-mandated** and each maps 1:1 to a verified Pass-0 gap, so there is nothing redundant to cut. Pass 2's work is therefore: per-component failure modes + safeguards, ranking (signal-quality × impact × feasibility), and the build sequence. Improvement items I1–I6 are folded in as safeguards where they belong (not separate features).

Heavy adversarial review + cross-model (ccg) + the **live vision probe** are deferred to Pass 3 by design (avoid duplicating the critic).

---

## Per-component: failure modes → safeguards

### C1 Reader rebuild
- **FM:** HTML has no usable text (image-only email) → extraction empty. **SG:** if text is thin, still run vision on charts; never early-exit on empty text the way the old watcher does.
- **FM:** chart `<img src>` are SendGrid click-wrapped, not direct CDN → URL filter misses them. **SG:** Pass-3 must verify against a REAL email; add a redirect-unwrap fallback if wrapped.
- **FM:** macro symbols still dropped. **SG:** LLM extraction path bypasses `extract_tickers` blacklist entirely; regex kept only as supplementary stock scan.
- **FM:** SCOPES mismatch breaks labeling. **SG:** align declared `SCOPES` to `gmail.modify` (token already has it).

### C2 Chart vision
- **FM (critical):** digit transposition / hallucinated levels → wrong trade levels. **SG (I1):** per-level `confidence`; `<0.7`→null; validate each level within ±30% of recent close (Finnhub/yfinance); prompt says "return null, never guess."
- **FM:** `from_uri` silently fails on arbitrary image URLs. **SG:** always download bytes → `from_bytes`.
- **FM:** quota burst (5 emails at once). **SG:** `rate_limiter.acquire("gemini")` (≥6s) + key rotation + `BudgetManager`; cap 5 charts/email; prioritize text-referenced charts (I2).

### C3 Thesis store / state machine
- **FM:** thesis sprawl; never-invalidating; stage flapping. **SG (I4):** sprawl caps (10 market/20 sector/30 stock); nightly price-invalidation check; 90-day stale auto-expiry; monotonic stage advance.
- **FM:** no key levels extracted → invalidation never fires. **SG:** flag `acting` theses with empty levels in the weekly recap (I3).
- **FM:** identifier aliasing ("S&P"/"SPX"/"SP500"). **SG:** canonical normalization at write time.

### C4 Confluence engine
- **FM:** double-counting one analyst's repeats. **SG:** dedup key `source_cluster|source_detail|day_bucket`.
- **FM:** scope creep (NVDA tweet counted toward market call). **SG:** exact-identifier match for stock/asset; bounded market-scope rule.
- **FM:** bonds/yields direction confusion. **SG (I5):** explicit asset-direction mapping in the extraction prompt + a unit test.
- **FM:** stale agreement (old calls counted). **SG:** ~21-day window only.

### C5 #news + proactive alerts
- **FM:** alert spam (every email pings). **SG:** alert only on stage-CHANGE, level-break, or confluence tier change — not every mention. Honor Alert Philosophy (quality over quantity).
- **FM:** @-mention silently suppressed by default `{"parse":[]}`. **SG:** dedicated critical-ping path overriding `allowed_mentions`; one owner id.
- **FM:** posting to wrong channel. **SG:** new `discord_news_channel_id`; never reuse #chat or #briefing ids.

### C6 Digest scheduler
- **FM:** midnight-crossing Wrap window (7pm–2am PT) never matches with the existing helper. **SG:** new two-branch window helper + a unit test crossing midnight.
- **FM:** duplicate digests on restart. **SG:** once-per-slot guard key (date+slot), Alfred-style transactional outbox.
- **FM:** quiet-day noise. **SG:** no email in window → no digest, no "nothing to report."
- **FM:** DST drift. **SG:** `ZoneInfo` (handles DST), not fixed offset.

### C7 Beneficiary inference
- **FM:** over-firing on small headlines; presenting inference as Wolf's view. **SG:** gate to big catalysts only; always label "bot inference."

### C8 Backfill
- **FM:** quota blowout reading All-Mail charts. **SG:** text-first; cap/skip charts on old emails; idempotent via `seen_gmail_messages`; run as a throttled one-shot, not in the live loop.

### C9 `!all` integration — **deferred to phase 2** (not built first).

---

## Ranking (H/M/L per axis)

| Comp | Signal-quality | Impact | Feasibility | Priority |
|---|---|---|---|---|
| C1 Reader | H | H (unblocks everything) | H (libs present) | **1** |
| C2 Vision | H | H (charts carry the signal) | M (accuracy risk) | **2** |
| C3 Thesis state | H | H (the "brain") | M | **3** |
| C4 Confluence | H | H (the big lever) | H (3/4 sources ready) | **4** |
| C5 #news alerts | M | H (the user-visible output) | M | **5** |
| C6 Digests | M | M | M (midnight window) | **6** |
| C7 Beneficiary | M | M | M | **7** |
| C8 Backfill | M | M (seeds state) | M | **8** |
| C9 !all | M | M | M | **later** |

Nothing falls to a "drop" tier — all are spec-required. C7/C8 are lower-priority but in-scope.

## Build sequence (each phase = user-observable outcome + verification)
Matches kickoff order; one VERIFIED phase beats three half-built.
1. **Reader+Vision (C1+C2):** *Outcome:* a real Wolf email → printed JSON of theses/levels/sectors/catalysts + chart reads. *Verify:* run against ≥3 real inbox emails, show actual text + chart output.
2. **State (C3):** *Outcome:* ingesting emails creates/updates/invalidates theses with correct stage. *Verify:* feed a sequence of real emails, dump `macro_theses`, confirm stage transitions + a price invalidation.
3. **Confluence (C4):** *Outcome:* a Wolf call shows "N others agree / divided" with correct tier. *Verify:* seed pool from real youtube/options/tweet rows; assert agree/disagree/tier on a known case.
4. **Alerts+Digests (C5+C6):** *Outcome:* dry-run #news post on a stage change + a nightly digest sample. *Verify:* sample output to a TEST channel; @-ping renders; midnight-window unit test green. **HARD GATE before any live channel/post.**
5. **Backfill (C8):** *Outcome:* All-Mail seeds N theses. *Verify:* count + spot-check theses; quota stayed in budget.
6. **Beneficiary (C7)** then **(later) C9 !all.**

## Verification anchors (carry to Pass 4 §8)
- Regression gate: `make test-baseline`; no green→red.
- Always-on: both services active, no GATEWAY drift, no LLM-health fail, symlink intact (after every restart).
- Shared-file tripwire tests if touched: `gmail_watcher.py`, `main.py`, `llm_client.py`, `config.py`+`consensus.yaml`, `db.py`, `narrator.py`+`aggregator.py`.
- Real-world: live vision read of a real chart; live read of ≥3 real emails; dry-run #news sample before any live post.
