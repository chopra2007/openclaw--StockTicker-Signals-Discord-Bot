# TODO #121 — Dashboard evidence and outcome repairs

**Status:** LIVE — implemented and verified; historical-data limits remain
**Created:** 2026-10-07 Pacific

## Scope and decisions

The owner withdrew the mobile-navigation complaint. Navigation was left alone.
The work addressed Account dismissal, analyst timestamps/images, combined
screening, inspection context, missing directions and track-record outcomes.
Codex proposed repairing the stored evidence and its presentation incrementally,
keeping the existing stack and separate bot/dashboard storage.

Claude collaboration could not be performed: no Claude plugin tool was available.
No Claude opinion or consensus is claimed. Independent Codex reviews found two
important problems: a combined-source request could conceal an access denial,
and cached raw charts needed retention checks and removal when permission ended.
Both were repaired and covered by tests. Final review reported no remaining P0/P1.
The simpler solution retains actual source evidence and calculated daily charts;
it adds no new model, score, data vendor or monitoring service.

## Problems and implemented repairs

1. **Account:** outside clicks and Escape close the menu; Escape restores focus.
2. **Analyst times:** preserve original embedded post times separately from
   collection times. Each call renders its timestamp and original post link.
   Historical records without a true post time use an explicitly labelled
   collection time. A bounded read of 19 original Discord source messages restored
   timestamps to 34 stored views, including 16 views with attributable media.
   Twelve recent group snapshots / 44 source-call entries were refreshed.
3. **MU chart:** TweetShift's separate image had already been joined successfully.
   Storage discarded raw image links unless the image qualified as directional
   evidence. Raw chart URLs now survive independently of classification. The
   original MU image is expandable in the dashboard; future Discord group cards
   include its link. A real subsequent MU Discord card was read back and contains
   both the chart link and the chart-attached explanation. Older Discord cards
   were not edited. A chart alone does not justify inventing bullish/bearish intent.
4. **Combined universe:** a third selection merges both sources without duplicate
   symbols, retaining setup and analyst context. Access denial takes precedence
   over a partial outage. Local saved-screen state supports this selection.
5. **Inspection:** explains inclusion in the recent-alert/setup source, active
   criteria and actual values; distinguishes source direction from computed trade
   direction; shows individual analysts, timestamps, original links and media.
   Daily price charts already obtained by setup computation are retained when
   allowed, so a personal saved research report is no longer required. AMZN was
   filled with 252 actual daily closes through the existing free Schwab path;
   its chart cache was written only after dashboard source-permission checks.
   Opening inspection makes no AI call. Generic historical catalysts such as
   “SEC filing” remain generic when no more specific evidence was stored.
6. **Directions:** persist actual bot alert directions and read them in the web
   adapter. An exact, unambiguous measurement-ledger join restored 1,960 older
   directions; no direction was guessed from price movement or generated levels.
7. **Track record:** retains bullish/bearish direction, grades price changes in
   that direction, excludes unknown direction from the favorable rate, and shows
   Pending / Unavailable / Market closed instead of unexplained blanks. Rolling
   synchronization now revisits older eligible records rather than starving them.
   Missing one-hour prices use the exact historical minute close when available
   within the existing provider's 30-day window, never a current-quote substitute.
   Small nonzero moves keep sufficient precision: the live HOOD example is
   “−0.03% · Favorable,” not “0.0% · Favorable.” Stock moves are not trade returns.

## Materially changed files

- Bot: `consensus_engine/db.py`, `main.py`, `hour_outcomes.py`,
  `scanners/discord_tweetshift.py`, `analysis/herding.py`, `alerts/discord.py`.
- Web backend: `member_dashboard/market_reader.py`, `contracts.py`,
  `publication.py`, `track_record.py`, `setup_levels.py`, `analysis_collector.py`,
  `source_policy.py`, `backup.py`, `operations.py`, `store.py`, `launch.py`,
  and migrations 013/014.
- Frontend: Account shell, source-call and alert-card components, screener state
  and logic, record line/panel, contract validation and a few responsive styles.
- Regression coverage: source parsing/storage, feed/chart retention, exact
  direction restoration, one-hour prices, outcome semantics, combined screening
  and browser interactions.

## Verification and rollout

- Focused dashboard Python checks: 248 passed, 1 skipped. Focused bot/media Linux
  checks: 175 passed. Additional exact-minute/direction tests passed.
- Affected browser checks passed (27 in the main validation pass). Both final
  outcome tests passed after the small-move regression was added.
- Production build/type checking and changed-file lint passed. Full lint retains
  the existing `chat.tsx` effect-state error and unused-variable warning.
- Isolated broad Linux run: 4,483 passed, 130 skipped, 12 failed. Every failure ID
  is in `.test-baseline`; these are the existing missing research-evidence checks.
  The full suite is not claimed green. Optional dashboard tests skipped by that
  interpreter were exercised separately in the locked web test environment.
- Live browser checks covered Account outside click/Escape, combined sources,
  bearish filtering, inspection/close preserving the screen, AMZN daily chart and
  chart periods/table alternative, MU original image and analyst times, and
  direction-aware track outcomes. Desktop, tablet and mobile layouts were checked.
  No browser console error was observed in the final live checks.
- Final live read confirmed all six MU analyst entries have original post times;
  the original chart loaded. A subsequent actual Discord MU alert contains the
  original chart URL. No synthetic public Discord message was sent for this work.
- QA found and fixed two new request/retention issues, a Windows backup-test file
  handle issue, stale one-hour test assumptions, and tiny-move rounding. The final
  small-move test initially omitted a required field; the fixture was corrected.
- Deployed code commits: `7e80fa3`, `fe03a1f`. Bot, gateway, API, frontend,
  supervisor, authority and quota services remained active after rollout. The
  expected OpenClaw symlink and recent model-health checks were verified.
  The disposable final QA member was disabled and its sessions revoked.
- Existing untracked production evidence was preserved. Dashboard rollback files
  and database snapshots are under `/opt/member-dashboard/rollback-oct7-fixes`.
  GitHub was not pushed mid-session.

## Remaining limits and next session

1. Follow a new chart-only post end to end and check the next day's alert outcomes.
   Improve visible source detail for generic catalysts only where actual stored
   source evidence supports it. Revisit source interpretation with human judgment
   when a chart is conditional or ambiguous; never force a directional label.
2. Audit outcome timing and historical observation quality: legacy spot observations
   and next-close fallbacks are disclosed, but are not uniform executable trade
   returns. Old prices beyond provider coverage remain unavailable. Add dependable
   exchange-holiday/short-session handling before claiming complete session coverage.
3. Repair the existing research-test evidence and lint backlog, keeping all access
   and source-permission checks intact. Broader-market filtering still depends on
   finding reliable, genuinely free coverage and licensing.

Whole-market screening, new volume/risk filters, automatic image reinterpretation,
composite trading scores, comparisons and server-monitored alerts were deferred.
No paid dependency, service, subscription or AI/model call was introduced by this
work. Existing trading/research calculations were not silently redefined.
