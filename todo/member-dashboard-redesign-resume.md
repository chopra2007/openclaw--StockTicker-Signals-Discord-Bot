# Resume: dash.groups.id redesign (TODO #121) — what the next session does

**Written:** 2026-10-20 Pacific, after Phase E closed. Owner will start a new session and say "resume #121".

## Where things are
- Build repo: `/opt/member-dashboard/redesign-20261020`, branch `todo121-redesign` (git, root-owned, NOT the
  workspace). Phases A, A2, B, C, D, E committed. Read `.redesign/PROGRESS.md` (every phase's results) and
  `docs/superpowers/plans/2026-10-20-dashboard-redesign-decisions.md` (binding rules; wins on conflict).
- Codex (gpt-6-astra) ran out of usage at 10:41 PDT Oct 20; its limit resets **Oct 27, 12:07 AM**.
  Phase E was finished by Claude (commit e5467d9, see PROGRESS.md "## Phase E"; all checks pass). Owner said they will finish the rest
  later; whoever does it (Claude now, or Codex after Oct 27) follows the steps below.
- Live sites: dash.groups.id (preview, ports 3454/3455, code in `/opt/member-dashboard/phase3-preview/current`)
  is still the OLD version. Main site akash.ignorelist.com (3444/3445) must never be touched.

## Remaining steps (in order)
1. **Phase F — full check.** `source .redesign/test-env.sh` (ports 3463/3464/3465 only). Run every check
   from Phase A again: lint, typecheck, build, every `playwright*.config.ts` mode (unit, default, home, ideas,
   smart-money, funds, insiders, company, events, sec), backend `pytest tests/member_dashboard` with
   `/opt/member-dashboard/testvenv/bin/python`. Compare with `.redesign/baseline.txt`: no test that passed
   at baseline may fail. Run browser modes one at a time (memory is tight, no swap).
   Option: resume Codex with `cd .redesign && setsid nohup ./run-phases.sh F >/dev/null 2>&1 </dev/null &`
   (only after Oct 27 or if credits are bought); then set `oom_score_adj` 800 on those pids only.
2. **Phase F — screenshots + report.** 1440/768/390 × dark/light of every page into `.redesign/after/`;
   Lighthouse on signed-in pages; write `.redesign/REPORT.md` (honest speed numbers; misses reported).
   Before-screenshots: `.redesign/before/` (+ `report.json`), tour script `.redesign/tour.py`.
3. **Phase F — write deploy + undo scripts** `.redesign/deploy-preview.sh` / `rollback-preview.sh`
   (review point 14 in `.redesign/codex-review.md`): back up the preview to
   `/opt/member-dashboard/preview-rollback-redesign-20261020/` with permissions; exact file manifest; KEEP
   preview-only files (`preview-api.py`, snapshot settings `MEMBER_PREVIEW_SNAPSHOT_AT`, `/etc/member-dashboard-preview/`,
   `/var/lib/member-dashboard-preview/`, ownership); a new DB migration `044_latest_saved_report.sql` must apply
   to the preview DB; restart ONLY `member-dashboard-preview-frontend` + `member-dashboard-preview-api`.
   Never use `deploy/member-dashboard/release.sh` (it targets the main site).
4. **Deploy (preview only) and verify on https://dash.groups.id** signed in as `test` / `test123` (owner's
   preview login): every page at 1440/768/390, dark + light, no console errors, no sideways scrolling, ticker
   page shows saved data with zero report requests until "Get full report", screener speed. Compare to before.
5. **Prove the main site was not restarted:** `member-dashboard-api` started Mon 2026-10-19 16:04:53 PDT,
   `member-dashboard-frontend` 16:12:15 PDT — `systemctl show -p ActiveEnterTimestamp` must still say that.
   Plus the [always] checks (consensus-engine + openclaw-gateway active; `/root/.openclaw` symlink).
6. **Bring the branch into the workspace repo** (as `openclaw`): fetch `todo121-redesign` from the build repo
   (may need `safe.directory`). The owner's Windows copy must pull this branch too.
7. Update this file, the #121 detail file's CURRENT STATUS line, and `TODO.md` (`scripts/todo_status_sync.py --fix`).

## Traps (learned the hard way)
- `codex exec` needs `< /dev/null` or it hangs forever. Codex's sandbox can't write `.git` (runner commits).
- Before any browser check, rebuild (`npm run build`): a stale build made 3 Phase E checks fail falsely.
- Playwright from your own scripts: `executable_path="/usr/bin/google-chrome"`, `args=["--no-sandbox"]`;
  the sign-in page never reaches "networkidle" — wait for the password box instead.
- Firecrawl is out of credits; don't use it.
- Server disk: keep >15% free (alert at 15%); the deploy backup needs ~0.8 GB.
- Known baseline failures (environment-only, not regressions) are listed in `.redesign/baseline.txt`;
  one auth timing test (`tests/member_dashboard/test_auth.py:1052`) was flagged in Phase A2.
- Home, Ideas and Smart Money browser checks must run through `npm run test:home|test:ideas|test:smart-money`
  (fresh test data per group). Running `playwright.<mode>.config.ts` for those three directly fails falsely.
- `.redesign/verify-phase-e-claude.sh` is a working full frontend check run (~2.5 h); reuse it for Phase F,
  then add backend pytest.
