# TODO #121 — Cached-data stock screener

**Status:** COMPLETE — approved bounded screener live and verified (2026-10-07 Pacific)
**Created:** 2026-10-07 Pacific

## Audit and agreed scope

Owner approved the bounded first release on October 7: screen recent alerts and
setups, intersect with a watchlist, filter cached price/day change/direction/age,
sort results, explain matches, inspect without losing state, save screens locally.

Live product was audited signed in on desktop and at 390 px. Current stack is
Next.js/React/TypeScript and a separate Python member API/database. Production
runs from `/opt/member-dashboard/current`; the bot producer uses its own checkout.
The original worktree lacked the web application; work starts from `vps/master`
commit `10d7d0b` on `codex/todo-121-screener`.

Claude plugin tools are not exposed. No Claude opinion, disagreement or consensus
is claimed. No paid-model call will be made for this work.

## Priorities

- P0: dedicated Screener navigation, explicit limited universe, AND filters,
  sortable table, price timestamps, match explanation, accessible inspection.
- P1: local named screens/column/sort/density preferences, watchlist intersection,
  saved chart reuse via read-only history, mobile essentials, refresh resilience.
- P2 deferred: broad-market coverage, volume/fundamental screening, percentile
  ranking, reliable alerts, comparisons, drag resizing/reordering. No trustworthy
  broad-universe snapshot exists in the current cached API.

## Data integrity and cost

`/setups/latest` and `/alerts/latest` return at most 30 recent cards each, observed
within seven days. They are not a complete stock universe. Current cached market
quotes contain symbol, price, previous-close change and quote time only; the quote
worker covers at most 100 index/watchlist/recent-alert symbols, once per minute.
API quote access is limited to authorized recent symbols and the member watchlist.
Quotes expire from API responses after 30 minutes since fetching.

Day change is `(price / previous close - 1) * 100`, calculated by the existing
backend. Age is elapsed hours since source observation. Neither formula changes.
Price filters use cached quotes only, never a historic alert price substituted
as current. Unknown observations cannot satisfy numeric criteria. Filters use
inclusive bounds; all active criteria combine with AND. No score filter or new
score is introduced. Trade levels remain dated calculated research, not promises.
No exchange-session calendar is present in this API; do not guess session status.

Existing research actions can spend the site's model budget. Screener inspection,
filtering, refresh, saving and chart reuse must perform no research/assistant POST.
Only existing dependencies are used; no new provider or subscription is needed.

## Baseline and validation ledger

- Existing frontend production build and typecheck passed before modifications.
- Existing lint failed at `chat.tsx:41` (`react-hooks/set-state-in-effect`).
- Existing browser suite initially could not launch missing Chromium; installed
  the version required by the existing Playwright dependency, then reran.
- Browser baseline identifies outdated expectations (e.g. keyboard test expects
  SPY on an empty mobile Alerts tab). Exact results retained in local `.e2e` logs.
- New tests precede implementation and cover filtering, invalid ranges, absent
  quotes, sorting with nulls last, saved state, refresh failures, inspection focus,
  absence of paid work submissions, and 390/768/1440 px layouts.

## Preserve

Keep Overview feeds, existing watchlist, history, research, assistant, source
permissions and dashboard feature switches. No bot/worker/data-provider changes.

## Implementation and review

Implemented a dedicated `/screener` over existing cached signals. Numeric filters
use inclusive bounds and explicit AND; applied criteria remain separate from
unapplied edits. Results sort with missing values last in either direction. Symbol
stays pinned during horizontal scrolling. Column visibility/order and compact or
comfortable density persist by member in this browser, alongside named screens.

Native modal inspection preserves the applied screen, restores keyboard focus,
explains each qualifying condition, dates quotes and calculated trade levels,
shows source evidence, and reuses authorized saved research charts via GET only.
No automatic research submission is added. Mobile filters collapse explicitly;
save controls use a disclosure so results remain easy to reach.

Claude collaboration could not be performed: no Claude plugin tool was available.
A separate Codex reviewer examined the implementation and reran browser checks;
this is not described as Claude agreement or consensus. The reviewer challenged
stale inspection and authorization handling, quote-fetch failure recovery,
watchlist synchronization, and quote timestamps. These were verified and fixed.
The final design retains the simpler bounded cached-data approach approved by the
owner rather than adding broad-market infrastructure or undocumented scores.

Material files: new screener route/component/filter logic/read hook and two test
files; updated app shell, global styles, watchlist hook/button; synthetic test-case
auth isolation and its Python test. Production backend, calculation formulas,
quote worker, bot and dependency manifests are unchanged.

## Final QA evidence

- New browser/filter tests: 20 passed, 16.8 seconds. Includes inclusive bounds,
  negative/zero/missing values, invalid/conflicting criteria, zero matches, sorting,
  refresh outage, source withdrawal during quote outage, quote denial in an open
  drawer, watchlist changes locally/from another browser, saved reload/delete,
  column visibility/order, density, universe changes, keyboard dialog focus,
  heading focus, 390/768/1440 layouts and 720px desktop zoom-reflow equivalent,
  light/dark media modes, chart period buttons/pointer readout/data table, and no
  research/assistant POST from screening or inspection.
- Local and staged Linux production builds passed. Typecheck and changed-file
  lint passed. Full lint retains the original `chat.tsx:41` effect-state error and
  unused-variable warning; no lint rule was disabled.
- Full member API tests: 723 passed, 17 skipped, 8 failed in 114.32 seconds. All
  eight failures reproduce using the original `HEAD` synthetic module. They are
  existing Windows `strftime('%-d')`, SQLite backup lock, Linux `/proc` assumptions
  and a related unavailable analysis collection result. Detailed logs are local
  ignored `.e2e/final-python.log` and `.e2e/python-head-baseline.log`.
- Synthetic auth isolation proof: exhaustion still blocks within a case; the
  GET readiness probe does not issue challenges; explicit test boundary resets
  challenge storage. Production auth limits were not changed.
- Performance: the screen bounds work to at most 30 source candidates, computes
  cheap filters/sorts locally, serializes reads, polls visible screens only, and
  retains usable cached data during transient failure. Typical complete synthetic
  browser workflows took about 0.8–1.1 seconds; these are not a live latency SLA.
  No measured need for virtualization or an additional chart/table dependency.

Bugs caught and fixed in test/review: tablet navigation overflow; stale drawer
content after source/quote withdrawal; restoring withdrawn cards after a quote
outage; stale shared watchlist membership; silent watch errors/concurrent writes;
drawer remaining after removal from a watchlist-only screen; focus lost when
loading settings replaced the heading; mobile results pushed below the fold;
ambiguous saving of unapplied edits; test-suite challenge-budget exhaustion.

- Independent full browser suite: 30 passed, 17 failed in 5.3 minutes. All 20
  new tests and all 9 original passes remain green; no new original failing ID.
  The original ticker-chat test recovered. The remaining 17 failures are the
  original baseline IDs, mainly outdated report/history/status expectations.

## Remaining limits and next priorities

No claim of whole-market screening: this source is at most 30 recent cards per
universe, not complete exchange coverage. No cached company/volume/market-cap
snapshot exists for these results; company and charts appear only if saved
research supplies them. Data is cached, not guaranteed real time. Missing data
cannot satisfy an active numeric filter. No exchange calendar is available, so
market session status is not guessed. Relative volume, percentiles, z-scores and
new composite scores are intentionally absent.

Named screens are browser/member-local (up to 20), not cross-device sync. The
inspector uses the latest report for a symbol within the latest 100 owned saved
reports; older charts remain accessible through History. Saved charts can have gaps
or short histories. Chart point inspection uses the existing pointer behavior;
daily closing data is also available as a table. No full WCAG certification is
claimed. Column resizing/dragging, comparisons, reliable monitored alerts, broad
fundamentals/event filters and a complete market universe are deferred.

Highest-value next work: (1) reconcile old browser expectations/lint and make
backend date/backup tests portable; (2) establish a reliable free broad-universe
snapshot before adding volume/liquidity/market-cap screening; (3) improve chart
coverage labels and keyboard point navigation across the existing report UI.
Human judgment remains necessary for trustworthy data coverage and desired
screening universes, and for evaluating research risk. No score promises returns.

No paid API, data source, component library, subscription, hosting/database
feature or other service was introduced. Existing locked dependencies and the
existing official Playwright browser were used. No paid Claude/model request was
made. No new worker, monitoring system, or automatic research job was added.

## Live deployment and browser verification

Frontend-only release is live at https://akash.ignorelist.com/screener. All 50
original deployed source files were hash-verified against the starting commit
before replacement. The old complete frontend is retained at
`/opt/member-dashboard/todo-121-frontend-rollback`; the pre-wording-refinement
build is retained at `/opt/member-dashboard/todo-121-frontend-before-chart-note`.
Only frontend was restarted. API, worker, authority, quota, consensus bot and
gateway remained active; public route and frontend health returned 200. Current
frontend logs show ready startup without application errors. No GitHub push.

Real signed-in Chrome checks covered price bounds ($10–$100 produced 5 of 30
setup candidates), ascending price sort, OPCH observed/required match explanation
and dated levels, named screen save/reload/reset/reopen/remove, NVDA watchlist
add/remove and automatic closing when removed from a watchlist-only screen,
setups/alerts universe switching, mobile filtering, tablet layout, History
navigation and browser Back with filters retained. Temporary watchlist and saved
screen changes were removed, and empty original watchlist was verified. Browser
viewport overrides were reset. Final console warning/error check returned [].

Live data limitation observed: cached quotes returned prices but absent day-change
values; cells show a dash, and active change filters exclude missing observations.
Current source direction is often unclear. Neither value is fabricated or
inferred from trade-plan direction. Saved chart availability is explicit; only
the newest owned report for that symbol is inspected, and History offers others.

Final build, typecheck and changed-component lint passed after the chart-coverage
wording clarification; all 20 screener tests were rerun and passed again. Live
screenshot is retained locally at
`web/member-dashboard/.e2e/screenshots/live-screener-final.jpg`.

Next data priority: verify previous-close coverage in the existing quote source
before expanding performance filters; preserve explicit missing-data outcomes.

## Next-session checklist — highest-value work

Saved at the owner's request on 2026-10-07 Pacific. These are open follow-ups
under TODO #121; the approved bounded screener remains complete. Start with the
existing implementation and live data, preserve source permissions and bot/API
isolation, and introduce no paid services or dependencies. Confer with Claude
before consequential decisions if the plugin is available without paid access;
otherwise state its absence and proceed only with free work.

### 1. Restore trustworthy day-change coverage

- Trace an actual cached quote from the existing provider through worker storage,
  member API and screener rendering. Determine why previous close/change is absent;
  do not assume a formatting problem or change the formula without evidence.
- Starting points: the quote collection/cache path, `/market/quotes`, existing
  market-board tests, `src/lib/use-screener.ts` and `src/lib/screener.ts`.
- Acceptance: where previous close is available, displayed and filtered change
  uses the existing `(price / previous close - 1) * 100` definition. Test positive,
  negative, zero and missing values, quote/session timestamps and refresh behavior.
  Unsupported observations remain missing; never substitute an old alert price.
- Recheck current live data: the missing values observed this session may change.

### 2. Make the existing regression checks dependable

- Reproduce the exact existing failing IDs recorded in the implementation ledger:
  17 browser tests, 8 Python tests and the `chat.tsx:41` lint error. Keep the 20 new
  screener tests and all original passing tests green.
- Repair stale report/history/status selectors and assistant labels. Resolve
  Windows date formatting, SQLite backup locking and Linux-only test assumptions
  with appropriate implementation fixes or platform-specific tests.
- Use the existing isolated synthetic composition and locked test dependencies;
  no production research submissions or paid model calls are needed.
- Acceptance: affected checks pass, or a genuine platform limitation is explicitly
  separated from product behavior. Do not delete tests, disable lint rules or
  weaken authentication, privacy and withdrawal assertions to obtain green output.

### 3. Establish whether broader screening can be supported for free

- Inventory existing data first. Assess complete universe membership, company,
  volume/average volume, market cap, timestamps and historical sample coverage.
- Verify that any proposed source is genuinely free for this use, with usable
  licensing, rate limits and predictable coverage. No signups, billing upgrades,
  usage-based charges or replacement of a working dependency for fashion.
- Acceptance before implementing filters: documented coverage/freshness/missing
  data and definitions, a bounded performance measurement, and a realistic free
  collection/cache plan. Add relative volume only with comparable volume periods
  and sufficient observations. Never imply unusualness predicts returns.
- If no reliable free snapshot exists, retain the current signal shortlist and
  document the evidence instead of manufacturing broad-market functionality.

Lower priority after these: chart coverage labels and keyboard point navigation.
Comparison, monitored alerts and speculative ranking models remain deferred.

### Follow-up — 2026-10-07 Pacific (password rule and regression review)

- Owner requested a minimum of five characters, without uppercase or digit
  requirements. Changed the shared server password rule and signup/reset form
  from 15 to 5; maximum remains 128. Existing passwords continue to work.
- Added a real browser signup/login/reset workflow and server tests for the
  five-lowercase boundary, invalid lengths, invite preservation and old-password
  rejection after reset. Updated operational documentation and obsolete password
  rejection fixtures. Commit: 102020f.
- Local account/admin checks: 128 passed, 2 skipped. Browser: new password workflow,
  two existing authentication checks and all 20 screener checks passed. Production
  build, type check and changed-file lint passed. Full lint retains the existing
  chat.tsx:41 error and unused-variable warning.
- Deployed the frontend and API; live HTTPS signup, login, reset and old-password
  rejection passed with a generated five-letter lowercase password. Four characters
  were rejected. Disabled the temporary QA member and revoked its sessions.
  No existing member credentials changed. Backup: /opt/member-dashboard/todo121-password-rollback.
- Previous session's background gate completed: 4,488 passed, 121 skipped, six
  failures already listed in .test-baseline; push completed. The fresh routine
  regression run also finished with 4,488 passed, 121 skipped and exactly those six
  existing research failures; no failure IDs outside .test-baseline. The routine
  server interpreter skips dashboard tests because their optional web dependencies
  are absent; the separate locked web test environment ran the 128 account/admin
  checks above, and the deployed HTTPS probe verified the actual production API.
- Rechecked live quote coverage at 2:15 PM Pacific: all 56 cached stock quotes
  were fresh within the API's 30-minute window and contained previous close; none
  had a zero change. The earlier missing-value observation is not current.
  Next session should trace day-change accuracy across regular/after-hours sessions,
  refreshes and missing-data cases before choosing a fix. Keep the existing formula.
- Next priorities remain reliable market-data presentation, existing regression
  repair, and whether dependable broader-market screening is possible without
  additional cost. No paid service, dependency or AI call introduced.

### Session notes — 2026-10-07 Pacific (session close)

Approved cached-data screener is live and verified. Commits dd84bb6 and e9f2a6a
contain implementation and live QA; d9ce7a1 saves the next-session priorities.
All 20 new tests pass, with no new original regression failures. Existing full
suite/lint failures remain documented. Next session starts with missing previous
close/day-change coverage, then regression portability/selectors, then reliable
free broader-universe feasibility. No paid service/dependency/model call added.
All work is committed; session-close gate/publish uses the authoritative VPS
master checkout, which already contains this session's implementation commits.
