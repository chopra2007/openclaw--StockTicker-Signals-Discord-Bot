# Kickoff — Wolf macro-brain Phase-4: intelligent beneficiary inference (#2) + fixes #3/#4/#5 (TODO #20)

The user ran `discover:` pointing here. **Run the full discover workflow (Pass 0–5).** Phase-1 (conviction tracker),
Phase-2 (confluence), and Phase-3 (Gmail backfill + midday/nightly/Sunday digests) are ALL LIVE in #news. This run
adds the **"actionable trades" layer** (beneficiary inference — the headline) plus three smaller fixes.

The user explicitly wants to be **wowed by thoughtfulness + coding prowess** on #2 — bias toward a genuinely excellent,
well-researched design, not a quick hack. Setup-question note: the user prefers the **native** (no-tmux) layout and a
**separate-session Pass-5 handoff** (they paste the resume line later); confirm in the setup questions but default there.

---

## Context — what already exists (VERIFY in Pass 0, reuse — do NOT rebuild)
- **Seeded data is live:** 72 `macro_theses` (38 active) from the Phase-3 backfill of 79 Wolf emails. Real content exists now.
- **Digests already render a payload with a `beneficiaries` slot that is intentionally EMPTY** (graceful omit). This run
  fills it. Renderer: `wolf_news.format_digest`; composer: `wolf_digest.gather_digest`; payload includes
  acting/imminent/watchlist/scoreboard.
- **Signals to REUSE for #2 (the whole point — these already exist):**
  - `data/peer_groups.yaml` (sub-industry peer layer) + `data/sector_map.yaml` (ticker→sector ETF). Don't mutate sector_map.
  - **Peer relative-strength** (5-day RS vs sub-industry peers) — #6 `!all` lever; RS is already computed somewhere reusable.
  - **Options flow** — `get_options_flow_for_ticker` (#18), autonomous unusual-flow detection.
  - **News catalyst** mining (direction-aware) — the `!all` catalyst pipeline.
  - **Confluence** — `wolf_confluence_checks` (agree/disagree/tier/sources per thesis); `db.get_confluence_check`.
  - `macro_theses` (scope_type/scope_key/direction/stage); `wolf_scope.resolve_scope` + `proxy_symbol` (+ `_SCOPE_PROXY`/`_NAME_ALIASES`).
- **DB schema is at v17** (Phase-3 added `wolf_call_outcomes` + `wolf_emails_processed.received_at`). New tables/columns = **v18**.
- **Engine/Gmail/DB ops** (stop/start/restart, any script touching the live DB or Gmail token) MUST run as the **`openclaw`**
  user with `.env.service` sourced (the GEMINI/OpenRouter/Discord keys are in `.env.service`, NOT `.env`); NEVER as root
  (DB `-wal`/`-shm` + token.json ownership traps). Pattern that worked in Phase-3:
  `sudo -u openclaw bash -c 'set -a; . /home/openclaw/.openclaw/.env.service; set +a; python3 <script>'`.
  See memory `project_wolf_phase3_built`, `reference_env_ownership_trap`, `reference_service_env_file`.

---

## THE BUILD

### #2 — Intelligent beneficiary inference  (HEADLINE — research-heavy, ccg-gated)
**Goal:** turn a Wolf macro call into a **RANKED list of specific stocks that benefit (long) or get hurt (short)**, as the
bot's clearly-labeled *inference* (NOT presented as Wolf's words), surfaced in the digest `beneficiaries` slot.

**Explicit user requirement — do NOT violate:** it must NOT be "the 2 stocks with the highest % gain in the sector."
Rank by an **intelligent composite**: news/catalyst direction + **7-day relative strength vs peers** + options flow +
confluence. Anti-patterns to design AGAINST: picking the highest-beta name (just amplifies the index), the biggest recent
gainer (mean-reversion trap), crowded trades, correlation≠causation, surfacing a name with no catalyst.

**Pass-1 research (REQUIRED — the user wants real research behind this, not a guess):**
- How production/quant systems map a macro/sector thesis → beneficiary names: RS leadership (leaders vs laggards),
  catalyst→supply-chain winners/losers, factor exposure, volume/accumulation, analyst-revision momentum.
- The hard part = the **macro→equities mapping**: OIL bull → producers (XOM/CVX/OXY); YIELDS↑ → banks benefit / long-duration
  tech hurt; DXY↑ → exporters/multinationals hurt; SEMIS bull → SMH constituents by RS; market top/bottom → defensives vs
  high-beta. Research a principled, MAINTAINABLE way to express this (curated macro→candidate-universe map vs deriving from
  sector_map/peer_groups) — weigh both.
- Free/public data only (yfinance OHLCV + existing options-flow + existing news/confluence). No new paid source without a flag.

**Design (Pass 2/4) must nail:** scope→candidate-universe mapping; the composite ranking formula (explicit weights for
RS / catalyst / flow / confluence + how to combine); how many names + a confidence value; **intellectual-honesty labeling**
("bot's inference from RS+flow+catalyst — not Wolf's pick"); **isolation** (new `wolf_beneficiaries` table OR digest-time
compute; writes ONLY to wolf_*; NEVER `!all`/`ticker_signals`/`signal_events`); graceful degradation when signals are thin
(omit rather than emit a weak guess).

**HARD PRECONDITION (user requirement):** the Pass-4 plan for #2 MUST pass **ccg** (Claude-Codex-Gemini cross-model review)
— or **Codex** at minimum — BEFORE any #2 code is written. Probe Codex file access first (its bubblewrap sandbox can't read
the 0700 workspace and silently falls back to stale GitHub → use a `/tmp` bundle + inline the plan; memory
`feedback_verify_codex_file_access`). Fold every valid finding in. This is non-negotiable.

### #3 — Live thesis-alert send-retry  (small; consistency)
Mirror the Phase-3 digest retry (commit `1977cd9`, `wolf_news._post_digest_event`) onto the LIVE thesis-alert path
(`wolf_news.post_event`, thesis branch): on a `create_pending_alert` dedupe collision, retry the send if the existing row
is NOT `status='posted'`; never re-send a 'posted' row (no double-post). Shared file → re-test Phase-1/2 alerts. Honestly
low value (a thesis re-posts on its next escalation under a new key) — it just completes the reliability story.

### #4 — Deeper parser-scoping fix  (small; touches the LIVE reader)
Extend `wolf_scope.resolve_scope` / `_NAME_ALIASES` so the email reader canonicalizes index/macro names: `NAS100`→NDX,
`TRANSPORTS`→ Dow-Transports, etc. — so a thesis threads into the canonical thread (e.g. NDX) instead of a stray
`stock/NAS100` thread. Phase-3 already fixed the *outcome-scoring* symptom in `proxy_symbol` (NAS100→QQQ, TRANSPORTS→IYT);
this fixes the *threading* upstream. Touches the LIVE path (gmail_watcher → wolf_email_parser → resolve_scope) → replay a
real Wolf email to verify, and re-run the wolf test suite. Decide: remap the existing mis-scoped backfilled theses (optional
one-off) vs leave them.

### #5 — Email + domain whitelist  (small; config clarity)
The capability already EXISTS — `gmail_watcher.sender_allowlist` (checked in `_sender_allowed`) already accepts exact
addresses AND `*@domain` globs, and the watcher only reads allowlisted senders. This task just splits that one combined
list into two explicit, clearly-labeled config lists: `allowed_emails:` + `allowed_domains:`, with `_sender_allowed`
checking both (keep backward-compat / the Wolf sender working; the backfill query also reads the sender). Pure
manageability/clarity.

---

## Sequencing
#2 is the research → design → **ccg gate** → build headline. #3/#4/#5 are small and well-specified. Suggested order:
bank the low-risk wins first (#5 config split, #4 scoping, #3 retry — each verified + the live reader/alerts re-tested),
THEN the #2 headline (with its ccg gate as the hard precondition before #2 code). Pass-5 executor may reorder, but #2 code
never precedes its ccg/Codex gate.

## Hard rules (carry from Phase-1/2/3 — these are a FLOOR)
1. **Verify, don't assume** — run live tests + view REAL output: replay a real Wolf email; render the real digest WITH a
   populated beneficiaries section against the seeded DB; read it. CLAUDE.md DoD + evidence standard apply.
2. **ccg/Codex gate on the #2 plan before building** (probe Codex file access first).
3. **Regression gate:** refresh/confirm `.test-baseline` first; no passing test may start failing; a SEPARATE verifier
   re-runs the full suite at the end and diffs the baseline.
4. **Isolation:** Wolf writes ONLY to wolf_*/macro_theses/wolf_call_outcomes/(new wolf_beneficiaries); NEVER
   `ticker_signals`/`signal_events`/`contradiction_index`/`get_active_tickers`/the live `!all` pipeline.
5. **Stop gates:** sign-off before any LIVE Discord post and before flipping any new flag `enabled:true`. Ship behind a flag
   (default OFF) like Phase-2/3.
6. **Engine ops as `openclaw` + `.env.service` sourced; never root.** Commit locally after each functional change; do NOT
   push mid-session (push + full gate at session close on "bye"). Code changes never use `--no-verify`.
7. **Found a better way → take it; thought of an improvement → build it.** The user wants thoughtfulness + prowess on #2
   especially — invest in a genuinely good design.

## Definition of done
- **#2:** the digest `beneficiaries` section renders a RANKED, clearly-labeled list of beneficiary names derived from real
  seeded theses, justified by RS + catalyst + flow + confluence (NOT % gainers); the plan passed ccg/Codex; isolation
  verified; flag default OFF + sign-off before any live post. Real end-to-end render inspected.
- **#3/#4/#5:** implemented + tested; live reader / thesis-alert path re-verified; config/flags safe.
- Full suite green vs baseline (separate verifier); TODO #20 + `todo/wolf-macro-brain.md` + memory updated; any new
  follow-ups logged BEFORE declaring done.
