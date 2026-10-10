# TODO #121: Drive backups, 2028 calendar and normal limits

Verified live on 2026-10-10 Pacific. These three follow-ups are complete; the
worker network restrictions and browser-test follow-ups remain open.

## Drive backup login

The backup remote used rclone's shared Google app. Its actual listing failed
with `googleapi: Error 403: Quota exceeded`; rclone also warned that the shared
client is being retired during 2026.

The server already had an authorized, owner-managed Google app login. The
backup remote now uses that existing app and login in its separate private
configuration, preserving the original folder and Drive permission scope.
This reuses the existing owner app; it does not create a new app exclusively
for the dashboard. No new permissions or paid service were added.

Verified the original folder is accessible (1,333 top-level entries), uploaded
a small connection-check file, downloaded it and matched its SHA256 exactly.
The temporary remote file was moved to Drive trash. The existing owner login
also remains readable by its original service user and passes a real listing.
Both configurations are private (0600), with their respective owners retained.
The transfer service still reads the same configuration and remote name.

Original configuration and private verification evidence are preserved under
`/root/.config/rclone/todo121-owned-client-stage`. Credentials remain outside
the repository. The transfer service was inactive during replacement.

## 2028 market schedule

Added all nine weekday closures and both early closes from the official
[NYSE calendar](https://www.nyse.com/trade/hours-calendars). July 3 and November
24 close at 10:00 AM Pacific. New Year's Day falls on Saturday, so December
31, 2027 remains a regular trading day. December 22, 2028 also stays regular.

The shared calendar governs market quote polling and outcome trading-session
checks. New tests initially reproduced eleven missing-date failures; after the
date addition, all 33 market-board/outcome tests passed. The deployed module
was separately checked after API and worker restart. Coverage now ends in 2028.

## Normal usage limits

The dashboard was already live and invitation-only. The owner delegated the
choice between continuing testing mode and restoring normal limits. Normal
limits were restored to protect capacity while the other follow-ups continue.
This is not a claim that every production-launch check has passed.

The testing flag was moved aside, preserving a rollback copy. API and worker
were restarted. The two designated test members were suspended through the
existing administrative service, which records the audit event and persistent
denial before changing account access. They have no remaining sessions.

The existing limits are back: five sign-ins per member per 15 minutes,
50 sign-ins per address, failed-login backoff, two active research tickers,
60-second refresh cooldown, ten research computations per hour, 60 research
requests per minute and 20 assistant messages per hour. Money and global
capacity caps remain enforced.

Live HTTPS proof used a disposable member: five successful sign-ins, then the
sixth rejected with HTTP 401 as the existing authentication contract specifies.
That member could still read the feed (200) and could not access administration
(403). The verification member was then suspended and all its sessions removed;
the short-lived maintenance session was also removed. No paid research or
assistant job was started by the probe.

Authentication, research, assistant and administration tests: 249 passed, one
skipped. Five additional outcome checks passed under the private production
umask (077); their accounts-backup fixture correctly refuses less-private
files under the default shell umask. Combined with calendar checks: 287 passed,
one skipped. These are
focused checks, not a rerun of the entire bot or browser suite.

Calendar originals, flag rollback and deployment hashes are under
`/opt/member-dashboard/rollback-todo121-oct10-calendar-normal`. All seven bot
and dashboard services were active; the OpenClaw symlink, recent model-health
log and repository ownership checks passed. Other sessions' files were preserved.
