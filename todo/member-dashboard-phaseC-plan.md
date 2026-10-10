# Member dashboard Phase C: working plan (2026-10-05)

**Status:** OPEN — live dashboard; data coverage, regression checks and launch follow-ups remain
**CURRENT STATUS (2026-10-10 Pacific):** Dashboard and cached-data screener are live. Live checkout synchronized while preserving the other session's options-flow work. Feed concurrency repair deployed: all 60 live HTTPS reads succeeded in a 20-member burst; authentication and permission checks remain enforced. Full dashboard backend suite: 803 passed, seven skipped, no failures. Next: worker egress allowlist, browser-test backlog, dedicated Drive client and owner-triggered end of testing mode. Outcome/calendar and insider-total repairs from PR #37 remain deployed. Other launch follow-ups remain open.

Kickoff: `todo/member-dashboard-phaseC-kickoff.md` (user decisions). This file is the step list and progress log.

## What the code really has (found at start)

- Production role code (`member_dashboard/operations.py`) is hard-wired closed: empty provider list,
  `authority_current=lambda:False`, no assistant, quota policies forced unverified at startup.
- No real composition of the research page exists anywhere; only test fakes (`synthetic.py`).
- Assistant transport is OpenAI-direct; API side needs the transport fingerprint too (it includes the key's hash).
- No Python 3.12 on the server (`uv` can install it). Node 24 exists. No nginx (not needed: no public address).
- Bot stays on its old budget path unless activated, so starting the dashboard's spend ledger can't block the bot.

## Steps (each with its check)

1. Env: Python 3.12 venv from `requirements-web.lock` (`/opt/member-dashboard/venv`), dashboard backend tests
   pass there (baseline). Check: test count vs PC (688 backend).
2. Assistant over OpenRouter, `openai/gpt-4o-mini-2024-07-18`; reservation = strict upper bound from request size;
   $3/day cap as a dollar scope in the spend ledger, configured from `quota.json`. Check: unit tests (cap denies,
   model id, no key in repr/logs).
3. Production wiring: denial-authority freshness as `authority_current`; owner-attested source permissions
   provisioned by a script; feed reads bot DB read-only with a lineage map; real symbol list. Check: unit tests.
4. Research sections with real data: options + expected moves, SEC, analysis (dashboard's own, not `!all`).
   Check: one real ticker page with every section completed or honestly unavailable.
5. Server setup: users, folders, keys, configs, systemd units (localhost only, no public address). Key copied by
   script, verified by length/hash only. Check: all units active; ownership/modes as designed.
6. Live proof: one real assistant answer; cap stops spending (lowered cap test); feed shows real cards.
7. Bot speed comparison with dashboard running (`!all`/`!sec`/`!options`/`!em` timings, no sustained >10% rise);
   disk `df -h /` ≥10 GiB and ≥15% free.
8. Full suites once (bot + dashboard), separate verifier agent, ownership check, commit. List go-live remainder, ask user.

## Progress log

- 23:00–23:35 PDT: Python 3.12 env at `/opt/member-dashboard` (venv + testvenv); dashboard baseline 684 pass /
  3 known fails (2 = `.openclaw` path trap in isolation audit, 1 = 20-member timing test on busy box).
- Assistant on OpenRouter + $3/day dollar scope; API twin descriptor; quota startup re-applies policy.
- Fixed design bugs found while deploying: tombstones never pruned + service restart deletes cgroup
  (supervisor would brick); authority expired after >5 min downtime (no recovery); sockets left behind
  blocked restart; cgroup dir mode 0770 hid it from broker; web DB 0640 capped ACLs.
- Services running (localhost only): authority, quota, api, worker (gated compute child). Feed reads bot DB
  read-only; owner permissions recorded; cards publishing. `deploy/member-dashboard/provision.sh`, `release.sh`.
- Symbols: SEC company + fund lists (39,021) at `/etc/member-dashboard/symbols.json`.
- Schwab ROTATES the refresh token on every refresh (seen 23:31). Dashboard must never refresh:
  `SchwabContext.refresh_allowed=False`, no OAuth route, timer copies the bot's access token each minute.
- 23:55–00:10: assistant PROVEN live (3/3 sourced NVDA answers, ~6 s, ~$0.0001/turn real). Fixes: lineage
  source_version must equal evidence version; prompt names exact tools + plain-text answer rule.
- Cap PROVEN: cap set to spent+$0.0005 → next question refused, 0 new paid calls; restored to $3.
- Research PROVEN on NVDA: SEC, options, em_daily (±$4.27), em_weekly (±$6.76). Fix: Schwab chain call needs
  includeUnderlyingQuote=true (spot time). Analysis section: delegated to fork agent (user: "!all on a web page",
  AI write-up counts toward the same $3 cap).
- HTTPS: Let's Encrypt cert for akash.ignorelist.com (expires 2027-01-04), certbot in /opt/certbot, ports 80/443
  closed (user choice). Auto-renew timer was BLOCKED by the safety classifier (opens port 80 itself) — user decides.
- Disk 00:10: 29 GB free, 61% used — passes.
- Research (old note): SEC (EDGAR) + Schwab options/EM wired; analysis section NOT wired (needs a dashboard-owned
  collector for ResearchInputs + LLM synthesis) — stays "unavailable".


### Session notes — 2026-10-06 (paused at user request, ~00:20 PDT)
- **Worked on:** live deploy on this server (localhost only); assistant, $3 cap, feed, SEC/options/EM proven;
  analysis section built by a fork agent and deployed (`analysis_collector.py`, settings at
  `/etc/member-dashboard/analysis-settings.json`); HTTPS cert issued; bot speed A/B for !sec/!options/!em (no change).
- **Decisions (user):** cert only, ports 80/443 closed; analysis = !all on a web page, AI write-up shares the $3 cap;
  speed test approved; agents allowed.
- **State:** NOTHING COMMITTED YET (many files changed; run ownership check + focused tests before commit).
  All dashboard services running + enabled? -> api/worker/frontend/quota/authority are started but NOT `enable`d at
  boot; schwab-sync timer is enabled. Test member `phasec_probe` exists (delete/suspend before go-live).
- **Next (in order):**
  1. AMD analysis write-up fell back to data-only (AI write-up didn't run) — find why (cap charge? endpoint
     mapping for the analysis model call? quota policy for its endpoint?). AMD em_weekly unavailable — check.
  2. Idle CPU still 26% of a core (was 71%): supervisor feed loop + authority RPC per transaction; trim.
  3. !all fresh-compute A/B not done (bot caches !all 15 min/ticker): space runs ≥15 min or use distinct tickers.
  4. Cert auto-renew timer was blocked by the safety classifier (it opens port 80 itself) — user to decide.
  5. Full suites once (bot + dashboard in testvenv), separate verifier agent, `scripts/check_ownership.py`, commit.
  6. Go-live list for the user: nginx/HTTPS proxy + open 443, first admin (`manage create-admin`, needs their
     password), backups/archive timer, egress restriction, delete probe member, enable units at boot.

### 2026-10-06 ~00:30 PDT — resumed after compact
- **User decision:** go-live AUTHORIZED ("go live as soon as everything is ready"); full suites once at the end only.
- Fixed: analysis AI write-up read only the first network chunk (OpenRouter sends keep-alive newlines first) →
  full read; AMD write-up now real. Overnight Schwab token went stale (bot refreshes only when used) →
  `member-dashboard-schwab-renew.service` runs the bot's own locked refresh (5 min early) before each copy.
- AMD em_weekly "unavailable" = bot's own quote-quality refusal overnight (honest, not a bug).
- Idle CPU: supervisor loop 0.1 s → 1 s; ~25% → ~13% of a core.
- Go-live prep: nginx installed; provision.sh step 10 renders the HTTPS site; origin = https://akash.ignorelist.com.
  Cert reminder task 2026-12-15 (auto-renew still owner decision); nginx reload deploy hook added.
- Fresh `!all` A/B (distinct tickers, no cache): OFF 90.1/92.3/70.3 s, ON 101.9/30.1/91.7 s → medians 90.1 vs 91.7 s (+2%). PASS.
- GO-LIVE 00:50: nginx 443 for akash.ignorelist.com, units enabled at boot, public sign-in + research proven.
- Feed disk bug: bot `ticker_signals` (1.55M backlog, ~55k/day) was being published card-per-row with 90-day
  retention (~12 GB). Raw mentions now never publish (`bot_feed_lineage` returns None for TICKER).
- Backups NOT enabled: backup tool caps the DB at 64 MB (owner decision, TODO #121 follow-up).
- Market-hours proof task scheduled 07:00 PDT (`/root/task_system/member-dashboard-check/run.sh` → notifications.log).
- CI red (run 37420925542): 8 research tests pass here but fail in CI (local data) → restored to `.test-baseline`.

## Session notes 2026-10-06 (afternoon/evening)
Owner fix rounds 1-3 done and live; details and done-tests in [UX fixes](member-dashboard-ux-fixes.md).
Commits fea6f73 (assistant live data, news + analyst calls in analysis, SEC 90 days), 55e8b47 (Apple-style
redesign, chat assistant, Ask in place), 03ca05f (risks after plan, real article links). Testing phase: member
throttles lifted. Open: browser test suite not run (port 3444 is the live site), egress allowlist, ideas list in TODO #121.

## Session notes 2026-10-06 (round 4: analysis as good as Gemini — paused mid-work)
- **Worked on:** New `member_dashboard/trade_map.py` (levels from swing highs/lows, 3-month most-traded price,
  20/50/200-day averages, 52-week range, largest option open interest, options-implied week/month ranges; plan with
  a reason per level), `street.py` (Nasdaq targets, ratings, earnings date), Bing News with summaries + direct
  links (Google link decoding now 429-blocked), collector `study()` shared by analysis, assistant and setup cards,
  write-up on google/gemini-3.8-flash with a number fact-check (`check_note`), contract fields `Level.note` +
  `horizons`, page parser + Analysis block. Live probes NVDA + MU: notes on par with Gemini, no invented figures.
  57 related tests pass; 5 full-suite failures all pre-existing (TODO #121 follow-up 7).
- **Decisions:** keep the bot's signal/score; replace only the plan; Gemini 3.8 Flash (~1.5 cents/report) inside the
  $3/day cap; drop Google link decoding (server gets blocked).
- **Next:** CSS for `.outlook` and level reasons, `npm run typecheck && build`, release.sh (backend + --web),
  live browser check NVDA + MU desktop/phone, then mark round 4 live.

### Session notes 2026-10-06 (round 5: redesign, #alerts on home, Market Edge)
- **Done + live:** round-4 analysis styling released (outlook rows, plan reasons, news summaries); checked live NVDA + MU,
  desktop/phone, light/dark. #alerts group alerts on Overview: bot saves each post to `swarm_alerts`
  (`db.insert_swarm_alert`, called from `send_swarm_alert`); dashboard source `swarm_alerts` -> `/api/v1/alerts/latest`
  (newest per ticker, feed access); 54 posts from the last 7 days copied from the channel. Renamed to "Market Edge".
  Ticker links open reports on tap (`TickerLink`); a bare /ticker address shows "Get X report" (never auto-starts work).
  Home lists capped with "Show all"; History rebuilt (switch, tap rows, bubbles, phone back).
- **Commits:** 2482ccc and the two after it. Tests: 710 pass, same 5 pre-existing failures.
- **Next:** 2026-10-07 13:10 PDT task checks the first new alert reached the site (notifications.log); e2e suite not re-run.

## Session notes 2026-10-06 (night: design review round)
- **Done (LIVE, commit a1323fb):** fresh-eyes review + competitor gap check + build, per
  `todo/member-dashboard-design-review-kickoff.md`. Report: price, day change, after hours, key stats, chart with
  trade-plan lines; Overview market strip; `/watchlist`; `/record` alert track record; sign-in/Assistant/History polish.
  All pages score 4+; details, scores and "not possible free" list in `todo/member-dashboard-design-review.md`.
- **Tests (once, at end):** site 733 passed / 4 known failures (migration test now fixed); bot 4,488 passed / 6 baseline.
- **Open:** P15 "Next year" paragraph still long; 1-hour track-record rule ignores exchange holidays; Schwab
  individual-developer terms for showing data to members not checked; e2e suite still not run (port 3444).

### Session notes 2026-10-07 (00:05 PDT: on/off switch)
- Added `scripts/dashboard_power.sh on|off|status` (commit f6c1f1f) and the trigger skill `~/.claude/skills/dashboard-power`
  ("turn off/on the dashboard"). Off = disable --now the 5 dashboard services + 3 timers (stays off after reboot), frees ~350 MB;
  on = Schwab token sync first, then everything, site back in ~10 s. Tested live twice each way; left ON.
- Limits: while off the site shows nginx's plain 502 page; `release.sh` restarts api/worker/frontend even when off.

### Session notes — 2026-10-07 Pacific (TODO #121 screener)

- Approved bounded cached-data screener implemented and deployed; actual desktop,
  tablet/mobile interactions and source/missing-data behavior verified.
- Twenty new tests pass. Independent full browser run: 30 passed, 17 original
  failures; Python: 723 passed, 17 skipped, 8 existing failures reproduced.
- Next-session checklist saved in `todo/member-dashboard-screener.md`: missing
  day change, existing checks, and free broader-universe feasibility, in that order.
- No paid service or model call introduced. Claude plugin was unavailable; separate
  Codex review was performed and is not represented as Claude consensus.

### Session notes — 2026-10-07 Pacific (password rule follow-up)

- Five-character lowercase-only passwords now work for signup and reset, verified
  locally in a browser and through the deployed HTTPS API. Existing passwords work.
  Temporary QA member disabled and sessions revoked. Functional commit: 102020f.
- Account/admin checks: 128 passed, 2 skipped. All 20 screener checks plus new
  password browser workflow and two existing sign-in checks passed. Build and type
  check pass. Routine regression: 4,488 passed, 121 skipped, six existing research
  failures; no failures outside .test-baseline. Existing chat lint issue remains.
- Latest live cache has previous close for all 56 fresh stock quotes. Next session
  verifies daily changes across trading sessions and missing-data cases, repairs
  existing dashboard checks, then assesses dependable free broader stock coverage.
  Full evidence remains in `todo/member-dashboard-screener.md`. No paid additions.

### Session notes — 2026-10-09 Pacific (SEC details, news and readability)

- Fixed the Form 4 fetch/display mismatch: all displayed trades are checked, sorted newest first,
  and labeled green Buy / red Sell. Scan up to 100 candidates, hide routine grants, withholding,
  gifts and exercises before applying the 15-row limit; partial coverage is stated explicitly.
- Distinct-person totals cover the checked 90-day list. Live MSFT: 4 sellers / $71.4M.
  Share counts and amounts are bold; personal names display Amy Hood, Satya Nadella,
  Judson Althoff and Takeshi Numoto. Form 144 name order is reconciled against Form 4 identities.
- Form 144 descriptions show the person, proposed shares, estimated value and approximate date.
  The linked Nadella notice is 86,525 shares (~$43.9M), around Sep 1, 2026; it is not a deadline.
- 8-K documents are read for the actual event. MSFT shows Reporting segment changes:
  FY2027, Agents and Infra / Devices and Consumer. Short descriptions replace form definitions;
  important details are bold. No extra AI call; successful detail reads are reused while the worker runs.
- Latest news searches the company name, covers 30 days and excludes call/put option activity
  and quote pages. Desktop analysis permits five lines; mobile retains two plus per-group Expand all.
- Relevant final Python checks: 98 passed; five focused browser checks, lint/build and independent
  review passed. Live HTTPS MSFT reports verified after restart; dashboard and bot services active.
- Broader dashboard checks: 756 passed, 7 skipped, 3 existing failures. Feed latency, synthetic-auth
  ordering and the backup permission fixture remain open and are recorded in TODO #121.
- Remaining requests: investigate site/ticker response time and decide which additional company
  events are actionable. Paid-data restrictions were removed from the requested next-step list.
- Code saved locally through 13fda9e; the bye command starts the background gate and branch PR merge.
  No comm-check-fail entries were saved this session. The first bye was incorrectly treated as a farewell;
  the user corrected it and the repository session-close procedure was then invoked.

### Session notes — 2026-10-10 Pacific (feed concurrency and checkout sync)

- Synchronized the live checkout to merged PR #37 after matching stale dashboard
  edits to committed versions and saving exact originals. The unrelated
  options-flow files retained their original SHA256 hashes.
- Repaired concurrent feed reading without caching or skipping permissions.
  Authentication shares the admitted transaction; queued sessions are checked
  at admission; temporary contention stays within the bounded request budget.
- Deployed only two dashboard feed files, restarted API/worker, and verified
  60/60 real HTTPS reads from 20 temporary members. Administration remained 403;
  every temporary member was suspended and sessions revoked.
- Six Linux isolation checks pass after fixing umask-dependent test fixtures;
  one cgroup check skipped. Final full dashboard suite: 803 passed, seven skipped,
  no failures in 296.74 seconds. Independent review found no actionable issue.
- Evidence and limits: [feed repair report](member-dashboard-feed-concurrency.md).
