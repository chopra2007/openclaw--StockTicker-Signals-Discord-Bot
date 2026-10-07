# Member dashboard design round: rules for every builder (2026-10-06)

Read first: `todo/member-dashboard-design-review.md` (problems P1-P28, design plan, gap list). Your own brief names
the problems and features you own. Three builders work in the SAME working tree at the same time.

## Hard rules
- No paid data. Only Schwab (already logged in), the bot database, SEC EDGAR, Nasdaq public pages, Bing/Google News,
  Finnhub free tier, yfinance. Never sign up for anything.
- Never print or log keys, tokens or passwords. Never read `/etc/member-dashboard/*.json` secrets into output.
- A bare `/ticker/X` address must never start research by itself (link-cost safety). In-site links may start it on
  click (see `src/components/ticker-link.tsx`).
- Times shown to members are Pacific (`America/Los_Angeles`). Never show "ET".
- Keep the iPhone look: system font, existing colour tokens in `globals.css :root`. Green/red only for price direction.
- Don't add or re-enable member throttles (testing phase). Keep the $3/day AI cap and the Schwab 15/min share.
- Schwab budget: every new Schwab call must go through the dashboard's existing provider/quota path (look at how
  `analysis_collector.py` and `setup_levels.py` get their client). No new tight loops; at most one extra call per
  report, and at most one quotes call per minute for any background snapshot.
- Minimal code. Match the existing (dense) code style. No new npm or pip dependencies (draw charts as inline SVG).

## Shared files: edit surgically
`web/member-dashboard/src/app/globals.css`, `web/member-dashboard/src/lib/contracts.ts`,
`member_dashboard/contracts.py`, `web/member-dashboard/src/lib/format.ts` are shared. Use the Edit tool with small,
unique `old_string` blocks; re-read the part you change right before editing; never rewrite the whole file; put new
CSS in a block with a comment header naming your area (e.g. `/* Report: hero + chart */`). Never touch a file
another brief owns.

## Checks you must run before reporting done
1. Python tests for what you touched:
   `sudo -u openclaw /opt/member-dashboard/testvenv/bin/python -m pytest tests/member_dashboard/<files> -q -p no:cacheprovider`
   Known failing before this round (ignore only these): test_migration_is_idempotent,
   test_twenty_member_local_projection_and_poll_latency, two test_isolation tests, test_synthetic_auth_boundary.
   Add or update tests for new backend behaviour.
2. Type-check + lint in your own scratch copy (the repo has no node_modules):
   ```
   T=/root/.claude/jobs/83eb540c/tmp/tc-<your-name>; mkdir -p $T
   rsync -a --delete --exclude node_modules --exclude .next /home/openclaw/.openclaw/workspace/web/member-dashboard/ $T/
   ln -sfn /opt/member-dashboard/current/web/member-dashboard/node_modules $T/node_modules
   cd $T && npx tsc --noEmit && npx eslint src
   ```
   (`chat.tsx` has one known lint error from before; don't add new ones.)
3. Do NOT run `deploy/member-dashboard/release.sh`, do NOT restart services, do NOT commit. The lead releases once,
   checks live, and commits.
4. Report back: files changed, what each P-number / feature now does, test + type-check output (pass/fail counts),
   anything you could not do and why.
