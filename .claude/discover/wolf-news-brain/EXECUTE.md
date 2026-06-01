# EXECUTE — wolf-news-brain Pass 5 (build)

Resume trigger (fresh session): `discover: resume wolf-news-brain`

> ⚠️ NEXT SESSION: phase-1 is already BUILT + committed (`ebf4ed1`) and a sample
> posted to #news. The user gave two refinements before going live — read
> **`RESUME-NEXT-SESSION.md`** in this same folder FIRST; it supersedes the
> build steps below (which are already done).

## What's done (Passes 0–4b)
Full discover pipeline complete + adversarially reviewed. Read these first:
- `.claude/discover/wolf-news-brain/final-plan.md` ← THE BUILD SPEC (incl. the "PLAN REVISION" section at the bottom — it supersedes earlier scope)
- `.claude/discover/wolf-news-brain/codex-adversarial-review.md` ← cross-model review (codex was DOWN → Gemini + code-verifier; both REVISE; converged on the confluence-data BLOCKER + thin-v1)
- `.claude/discover/wolf-news-brain/pass-3-stress-tested.md` ← critic + security findings (all folded into the plan)
- `.claude/discover/wolf-news-brain/state.json` ← decisions[] + plan_revision
- `todo/wolf-macro-brain.md` ← product spec (fixed)

## Scope for this build = PHASE 1 ONLY (thin, dry-run)
reader → vision → extraction → thesis → #news alert. **Confluence (P2), digests (P3), beneficiary (P4), backfill (P5), !all (later) are DEFERRED.**

## Build order (each step: commit locally per CLAUDE.md; do NOT push mid-session)
0. **Baseline (do first):** `make test-baseline` + commit `.test-baseline` (it was empty). No green→red after this.
1. **db.py:** add `macro_theses` table to SCHEMA + bump `_SCHEMA_VERSIONS` to (15,"wolf macro-brain") + access fns (`upsert_thesis`/`get_active_theses`/`invalidate_thesis`). Tripwire file — read exact current content before editing.
2. **`analysis/wolf_vision.py` (new):** SSRF-guarded fetch (https-only, host allowlist=newsletter CDN, allow_redirects=False, 10MB cap, reject private IPs) → native Gemini `from_bytes` + model fallback `[gemini-flash-latest, gemini-2.5-flash, gemini-flash-lite-latest]` (PROVEN live in Pass 3) → confidence<0.7 drop + ±30% price-range validation.
3. **`analysis/wolf_email_parser.py` (new):** BeautifulSoup(lxml) text + chart-URL extract (first 5 distinct non-tracking by appearance; keep `wp-content/uploads/`, drop sendgrid/tracking/≤5px); LLM JSON via `call_with_fallback(role="primary",...)` with anti-injection clause; **validate every field** (enum clamp direction/stage, ticker regex `^[A-Z\^]{1,10}$`, level range, confidence gate); append ChartRead as structured fields (no multimodal prompt).
4. **`analysis/wolf_theses.py` (new):** match/create/advance(allow downgrade)/invalidate; level-less→surface tier; sprawl cap→invalidate oldest-LRU of scope; 90d stale expiry; store price_at_creation.
5. **`scanners/gmail_watcher.py` (REBUILD, tripwire):** `_decode_body`→(text,html) w/ BeautifulSoup; **skip subject substring gate for the trusted Wolf sender** (sender allowlist pins it); align SCOPES to gmail.modify; tighten `_auth_results_pass` to word-boundary regex; replace lines ~275-354 body-extract block with parse_email→theses.ingest; keep dedup/caps. **Loop already uses `stop_event` internally** — the only wiring fix is in main.py.
6. **`main.py` (tripwire, 1-line):** at ~line 676 pass the real `stop_event` (available at ~:552) to `gmail_watcher_loop`, NOT `combined_stop` (so it survives the weekend pause).
7. **`alerts/wolf_news.py` (new):** post stage-change/level-break to #news (model on `briefing/alfred.py:_send_discord_briefing`, channel=`api_keys.discord_news_channel_id`); critical @-ping (validated-fields-only content, override allowed_mentions) ≤3/hr — post message immediately, suppress only the @-ping on limit.
8. **config:** extend `gmail_watcher` (+charts_per_email_cap, cdn_allowlist, wrap detection); add `api_keys.discord_news_channel_id`/`discord_owner_user_id`. Keep `enabled:false`.

## Paths/gotchas (verified)
- Data files are `consensus_engine/data/*.yaml` (sector_map.yaml, peer_groups.yaml).
- Service: `sudo systemctl restart consensus-engine`; reads `.env.service` (NOT workspace/.env). New env vars → BOTH `.env` and `.env.service`, then `chown openclaw:openclaw` + `chmod 600`. `chmod 600 credentials.json`.
- bs4 4.14.3 + lxml + google.genai installed. Gemini keys in env (GEMINI_API_KEY/2).
- After any restart: both services active, no GATEWAY drift, no LLM-health fail, `/root/.openclaw`→`/home/openclaw/.openclaw` intact.

## HARD GATE (stop for sign-off)
Before creating the #news channel, posting to ANY live channel the user sees, or flipping `enabled:true`. Show a dry-run/sample first. (Creating #news + first live post = the gate.)

## Phase-1 verification (Evidence Standard — show real output)
- Live read of ≥3 REAL Wolf inbox emails → printed validated JSON (text + chart reads).
- Thesis transitions across a real email sequence (dump macro_theses).
- Unit tests: stop_event-not-paused, level-less→surface, injection→neutral, SSRF reject, ticker-clamp.
- Dry-run #news sample to a TEST channel before any live post.
- Regression: full suite, no green→red vs `.test-baseline`.
