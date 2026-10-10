# TODO #121: feed concurrency repair — 2026-10-10 Pacific

The feed repair is deployed and verified. TODO #121's other follow-ups remain open.

## Problem and change

The existing 20-member feed test failed with `sqlite3.OperationalError: interrupted`.
Twenty threads repeatedly executing small SQLite permission queries contended with
each other: the same work completed below one second when reads were admitted one
at a time. Permission decisions are still made for every card; none are cached or
skipped. Writes keep their separate bounded reconciliation path.

The first deployed repair passed the direct service test but the real HTTPS burst
still had failures. Authentication had its own database transaction before feed
admission. Authentication and delivery now share one admitted, reconciled
transaction. Session lookup, expiry, account status/version, session touch and
revalidation still use the existing authentication code. Source permissions,
features, retractions and outside authority checks remain enforced.

Browser requests use a single three-second feed or seven-second latest-card
budget, including queuing. This combines the former two-second authentication
lock wait with the one-second/five-second feed budget. Trusted internal callers
retain their original one-second/five-second budgets. A browser can wait up to
two seconds for a short supervisor write, still bounded by the request deadline.
Overload returns a private 503 response; a failed read releases the admission lock.

## Verification

- Existing failing concurrency test now passes: 20 reads in 0.862 seconds.
- Final feed tests: 76 passed. Authentication/source-policy checks: 190 passed,
  one skipped before the last deadline and short-writer additions; those additions
  were exercised in the final feed checks.
- Linux isolation checks: six passed, one skipped. Two fixtures depended on the
  process umask: `mkdir(mode=0750)` became 0700 under umask 077. Explicit fixture
  chmod restores the intended group traversal, without group write access.
  Secret directories remain 0700; source files remain 0640. Production permissions
  were not relaxed. The failures reproduced before the fixture change.
- Full locked Linux dashboard suite: 803 passed, seven skipped, no failures in
  296.74 seconds under umask 077. This is the dashboard suite, not the whole bot
  suite or the separate browser suite.
- Independent review covered admission, timeout recovery, authentication,
  raw-token handling, chart permissions and the isolation fixtures; no actionable
  issue remained.
- Actual deployed HTTPS burst: 20 distinct temporary members, 20 successful reads
  on each of `/feed`, `/alerts/latest`, `/setups/latest` (60/60 HTTP 200).
  Batch wall times were 1.629, 1.866 and 2.709 seconds; largest individual response
  was 2.650 seconds. Responses contained 50 feed records, 13 alert cards and 30
  setup cards respectively. Member access to administration returned 403.
- The initial live burst had 11 unavailable responses across those 60 reads.
  These are observed batches, not an endurance benchmark or a capacity guarantee.
  The probe makes GET requests only; it creates no research or assistant job.
- Temporary QA members from every probe were suspended and their sessions revoked.

## Checkout synchronization and rollout

The live checkout was behind merged PR #37. Every old dirty dashboard file was
matched to a committed revision before replacing it. Exact original files and a
binary worktree patch were backed up, then the checkout advanced to `da799b0`.
The three unrelated options-flow files retained their exact SHA256 hashes;
existing untracked evidence was left in place.

Only `member_dashboard/publication.py` and `member_dashboard/routes/feed.py` were
copied into the deployed application, with hash verification. API and worker were
restarted; bot source was not copied into the deployed dashboard. Source rollback
copies are under `/opt/member-dashboard/rollback-todo121-oct10-feed`, with the
intermediate auth/writer rollout snapshots alongside it. Checkout preservation
is under `/opt/member-dashboard/rollback-todo121-oct10-sync`.

Bot, gateway and dashboard services were active after restart. The OpenClaw
symlink resolved correctly and no recent model-chain/AI-health failure matched
the required log check. Final checks and saved changes are in the Phase C log.

## Still open

Worker egress restrictions, the separately recorded browser-test backlog, a
dedicated Drive OAuth client and the owner-triggered end of testing mode remain.
The calendar needs its next year added before current coverage ends. This work
does not claim the whole TODO is complete or whole-market screening is available.
