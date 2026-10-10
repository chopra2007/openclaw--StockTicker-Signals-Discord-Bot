# TODO #121 — Proposal: network limits for the dashboard's background programs

I made no tool calls and wrote no files, as you asked. That includes skipping the plan-file and plan-approval steps that plan mode normally uses. Everything below comes only from the evidence you pasted. Secrets, contact strings, the site address and server IPs are left out on purpose.

## 1. What each dashboard background program can reach today

A "service" here means a long-running background program that the system manages.

| Service (runs as) | Network today | Needs the internet? |
|---|---|---|
| `member-dashboard-api` (md-api) | Already this machine only (`IPAddressDeny=any`, `IPAddressAllow=localhost`) | No. Leave it. |
| `member-dashboard-frontend` (md-frontend) | Already this machine only | No. The live site already works under this limit. |
| `member-dashboard-quota` | Local sockets only, all IP traffic denied | No. Leave it. |
| `member-dashboard-authority` | Local sockets only, all IP traffic denied | No. Leave it. |
| `member-dashboard-archive` | Local sockets only, all IP traffic denied | No. Leave it. |
| **`member-dashboard-worker`** (md-supervisor, plus the compute child) | **Fully open.** The unit file says: "Outbound internet stays open … (no egress proxy yet)" | **Yes, but only the compute child.** This is the gap. |
| `member-dashboard-schwab-sync` (root, no sandbox) | Fully open | Probably not. It copies a token file. Not yet checked: I haven't seen `deploy/schwab-token-sync.py`. |
| `member-dashboard-schwab-renew` (openclaw) | Fully open | Yes, the Schwab token address. This is the bot's own code and user. |
| `member-dashboard-size-check` (openclaw) | Fully open | Yes. It posts to the #errors channel through Discord. This is the bot's user. |

The worker is the real job. The supervisor part of the worker only uses Unix sockets (local-only connections) to talk to the quota, authority and exit-control programs. It reads the bot database from a file. I found no web call in `supervisor()`. The compute child lives in a sub-group of the worker's own process group (`…/member-dashboard-worker.service/compute/<id>`). That means a limit set on the worker unit should also reach the child. This must be checked, not assumed (see uncertainty 3).

## 2. Hosts the worker must reach

These are the real calls the compute child makes. Each one is written as a fixed constant in code that sends a request.

| # | Host (port 443 only) | Who calls it | Evidence |
|---|---|---|---|
| 1 | `openrouter.ai` | Assistant answers and the analysis write-up | `assistant_transport.ENDPOINT`; `CappedSynthesis` reuses `ENDPOINT` |
| 2 | `www.sec.gov` | Ticker map `/files/`, filings `/Archives/` (8-K, Form 4, Form 144 documents) | `provider_routes()` |
| 3 | `data.sec.gov` | Company filing lists `/submissions/` | `provider_routes()` |
| 4 | `api.schwabapi.com` | Quotes, price history, option chains, expirations (market data path only) | `provider_routes()`, `MD_BASE` |
| 5 | `www.bing.com` | News RSS | `news.BING` |
| 6 | `news.google.com` | News RSS | `news.FEED` |
| 7 | `api.nasdaq.com` | Wall Street targets, ratings, earnings date | `street.BASE` |

Two things keep this list tight:
- Every client turns redirects off (`allow_redirects=False`). So no call is quietly sent on to another host.
- SEC and Schwab requests also pass the quota broker's route check (`TransportBudget.admit`). That check rejects any address not in `provider_routes()`.

Schwab's token-refresh address (`/v1/oauth/token`) is on the same host, but the dashboard never uses it (`refresh_allowed=False`). Only the bot's renew service refreshes.

**Incidental URLs. These appear in code but are never fetched by the worker:**
- Test fakes and defaults: `example.org`, `sec.gov/synthetic-terms` (`synthetic.py`), `dashboard.test` (`settings.py`), `localhost:3443` (`launch.py`).
- Article links shown to members. The comment in `news.py` says Google links are never resolved on the server.
- `terms_url` and evidence URLs.
- Bot-only hosts in `consensus_engine/scanners/news.py`: Finnhub, Brave, and Google News again. The dashboard does not import that file in the code shown.

**This list is not proof of all traffic.** The pasted snapshot only shows three half-closed connections from one compute process to one cloud network range. It cannot show calls that happen rarely or only in certain conditions. The biggest unknown is the bot's own `!all` code (`compute_research`, `technical_filters`, `expected_move`, `_detect_unusual_activity`), which the compute child imports. If any of it calls something like yfinance or Finnhub, that call is missing from the table. Step 0 and the watch-only phase below are there to close this gap.

## 3. How to enforce it

**Recommendation:** add a small local "egress proxy". This is a relay program on the same server that forwards web requests only to the 7 hosts above. Then lock the worker so it can only talk to that relay. The worker unit's own comment already plans for this: "External provider traffic requires an explicitly reviewed local egress proxy."

**Why not list IP addresses in systemd instead:** systemd's `IPAddressAllow` works by IP address, not by host name. Six of the seven hosts sit behind big cloud networks, and the snapshot already shows one of them. Their addresses change, and they are shared with millions of other sites. An IP list would either break often or let in a large part of the internet.

**The new relay service, `member-dashboard-egress.service`:**
- It runs as a new user, `md-egress`.
- It listens on `127.0.0.1:3446` (this machine only).
- It accepts only HTTPS tunnel requests (`CONNECT`) to port 443, and only for an exact match with one of the 7 names. Lookalikes such as `sec.gov.evil.com`, a trailing dot, or a raw IP address are refused. Matching ignores upper/lower case.
- After it looks up a name's address, it refuses private, loopback and link-local addresses. This stops a host name from being pointed back inside the server.
- It limits how many connections can be open at once and closes idle ones.
- It writes one log line per connection: host, allowed or denied, bytes sent, and duration. The connection is encrypted end to end, so it never sees paths, tokens or message content.
- It has a watch-only mode that allows every port-443 host but logs each one. This is used for the first phase.
- Its unit gets the same hardening as the other dashboard units. It may reach the internet, but it is blocked from private network ranges.

I recommend writing it as a small (~150-line) Python program in the repo, not installing tinyproxy or squid. Reasons:
- It can be tested with pytest like the rest of the repo.
- It has the watch-only mode built in.
- It can apply the private-address check.
- It adds no new package.

tinyproxy would be the simpler choice if you would rather not own this code. The cost is that you would need to confirm how its filter treats tunnel requests, and it has no private-address check.

**Locking the worker.** Edit `deploy/member-dashboard/member-dashboard-worker.service`:
- `IPAddressDeny=any`
- `IPAddressAllow=127.0.0.1/32`

This deliberately leaves out `127.0.0.53`, the server's local name lookup service. With the relay in place, the worker never needs to look up names itself. That also closes the "sneak data out through name lookups" path.

Also add `Wants=` and `After=member-dashboard-egress.service`, so the relay starts before the worker. Replace the "Outbound internet stays open" comment.

**Small extra:** give `schwab-sync` `IPAddressDeny=any` and `RestrictAddressFamilies=AF_UNIX`, but only after reading its script to confirm it makes no web call.

**Out of scope, report only:** `schwab-renew` and `size-check` run bot code as the bot user. Limiting them would mean changing how the bot itself connects out. Add that to the TODO list as a separate item.

## 4. Code changes needed in each client

Every client sets `trust_env=False`. That means each one ignores proxy settings from the environment, which is good: nothing silently switches over. It also means each client must be pointed at the relay explicitly.

- **New file `member_dashboard/egress.py`:**
  - holds `PROXY = 'http://127.0.0.1:3446'`
  - holds the allowlist (the one place the 7 names live)
  - has a `session(**kw)` helper that returns `aiohttp.ClientSession(trust_env=False, proxy=PROXY, **kw)`
- **aiohttp clients switch to that helper:**
  - `DirectTransport.complete` (assistant)
  - `CappedSynthesis.__call__` (analysis write-up)
  - `news.headlines`
  - `street.street`
  - the SEC session in `operations.research_registry`. Here a whole-session proxy setting is required, because `SecContext` calls `client.get(...)` without passing a proxy, and `BudgetSession` passes extra settings straight through.
- **Schwab (requests library):** in `research_registry`, after `SchwabClient(...)` is built, set `client._session.proxies = {'https': PROXY}`.
  - The existing safety check `_request` only looks at `trust_env` and the adapters, so this is still allowed.
  - Downside: it touches a private attribute.
  - Upside: it keeps `consensus_engine/scanners/schwab_client.py` unchanged. Changing that file would pull the bot's data-ingest checks into this task.
- **A relay outage fails safely.** News and Wall Street data return empty. The assistant returns "unavailable". Schwab and SEC sections finish as "unavailable".
- **One side effect of an outage:** the SEC and Schwab quota slots are reserved *before* each request is sent. So while the relay is down, failed calls still use up the dashboard's 15-per-minute Schwab share.

## 5. Tests

These run on Linux in the test environment.

- **Relay:**
  - allowed host goes through, using a fake target server
  - denied host gets 403
  - raw IP address gets 403
  - ports 80 and 22 get 403
  - plain (non-tunnel) requests get 405
  - lookalike names are refused
  - a name that resolves to a private address is refused
  - watch-only mode logs and allows
  - connection limit and idle timeout work
- **Clients:** each of the 6 call sites builds its session with `PROXY`. Test this by capturing what is passed to `ClientSession`, and by checking `_session.proxies` for Schwab.
- **Allowlist stays in sync:** the allowlist must equal the set of hosts in `provider_routes()`, `assistant_transport.ENDPOINT`, `news.FEED` and `news.BING`, and `street.BASE`. Adding a new source without updating the allowlist then fails before it ships.
- **No bypass:** a search test fails if `member_dashboard/` gains an `aiohttp.ClientSession(` or `requests.Session(` that does not go through `egress`.
- **Unit files:** the worker unit has the new deny/allow lines, and the relay unit settings are as designed.
  - Hidden dependent: search `tests/` for these unit files and for "Outbound internet stays open". `tests/member_dashboard/test_launch_linux.py` probably asserts on unit contents.
- **Full suites:** dashboard and bot, compared against `.test-baseline`, with a separate verifier agent.

## 6. Rollout

**Step 0 — Read-only check, before building:**
- Search everything the compute child imports for `aiohttp`, `requests`, `httpx`, `urllib.request`, `yfinance`, `socket.create_connection`, `smtplib` and `websocket`.
- Check the aiohttp version in `requirements-web.lock`. Whole-session `proxy=` needs version 3.10 or later.
- Read `schwab-token-sync.py` and `/etc/member-dashboard/compute.json`.

**Step 1 — Build, then deploy in watch-only mode:**
- Deploy the relay in watch-only mode and point all clients at it.
- Add one temporary nftables firewall log rule (log only, it drops nothing) for the md-supervisor and md-compute users. It logs any connection *not* going to 127.0.0.1. That catches calls that skip the relay, which is the gap the snapshot cannot cover.
- Update the scripts that start and stop dashboard services. These are hidden dependents:
  - `provision.sh`: create the user and install the unit
  - `release.sh`: restart the relay too
  - `scripts/dashboard_power.sh on|off`: include the new unit
- Then run every path once:
  - research on NVDA and MU, covering the SEC, options, daily and weekly expected-move, and analysis sections
  - one assistant ticker question
  - the screener
- Let the idle chores run: market strip, track record, setup levels every 3 minutes.

**Step 2 — Watch for one full market day:** 06:30–13:00 PDT, plus overnight.
- Schedule a check task with `/root/task_system/scripts/create_task.sh` for 13:30 PDT on the next market day. It reports which hosts appeared and any bypass lines to `notifications.log`.
- Holding enforcement for this is a legitimate deferral: the check needs traffic that can only be collected going forward.

**Step 3 — Enforce:**
- Switch the relay to the 7-host allowlist.
- Turn on the worker deny/allow lines.
- `daemon-reload`, then restart the relay and the worker.
- Remove the temporary firewall log rule.

**Step 4 — Prove it, after the restart:**
- Standard checks: `consensus-engine` and `openclaw-gateway` are active, `/root/.openclaw` still points to `/home/openclaw/.openclaw`, no drift or AI-health alert, all dashboard units active, `check_ownership.py` passes.
- `bpftool cgroup show <compute/<id> path> effective` shows the worker's IP filter on the compute child's group. This is a read-only check.
- `ss -tnp` for the compute process shows only connections to `127.0.0.1:3446`.
- A real HTTPS NVDA report matches the report taken just before the change. Every section is completed, or "unavailable" exactly as before.
- One real assistant answer comes back with sources.
- The market strip updates within 2 minutes.
- During one market session, the relay log shows all 7 hosts and zero refused connections.
- No new rise in "unavailable" in `journalctl --namespace=member-dashboard`.

## 7. Rollback

| Problem | Fix | Time |
|---|---|---|
| Lock is the problem | Restore the previous worker unit (remove the two IP lines), `daemon-reload`, restart the worker | ~1 min |
| Relay is the problem | Switch the relay back to watch-only mode (allow all, log) and restart it | ~1 min |
| Need to undo everything | `release.sh` the previous commit (clients go back to connecting directly), then `systemctl disable --now member-dashboard-egress` | ~2–3 min |

Keep the previous release folder until enforcement has run cleanly through one market session.

## 8. Uncertainties

1. **The full traffic list is unproven.** The bot's `!all` code imported by compute may call other hosts. The watch-only phase is what settles this.
2. **aiohttp version.** If it is older than 3.10, whole-session `proxy=` is unavailable. The SEC session then needs a small wrapper that adds `proxy=` to every request.
3. **Does the limit reach the compute child?** The worker's IP filter should carry into the delegated compute sub-group, but this is unverified; `bpftool … effective` checks it. Separately, the supervisor keeps the `CAP_SYS_ADMIN` permission, so if the supervisor itself were taken over it could remove the filter. The compute child gives up every permission, so the main risk, a compromised compute child, is covered.
4. **Schwab uses a private attribute** (`_session.proxies`). A future upgrade of the bot's Schwab client could break it silently. The client test catches that.
5. **`schwab-sync` network need** is unverified until its script is read.
6. **The relay is a new single point of failure.** If it is down, every external section becomes "unavailable" and Schwab quota slots are used up.
7. **Any future data source must be added to the allowlist.** This includes the planned broader free stock coverage. The allowlist-sync test makes a forgotten addition fail before release instead of in production.
8. **`schwab-renew` and `size-check` stay open.** This is reported as a separate TODO, not fixed here.

## 9. Size

**Medium**, about two sessions:
- **Session 1:** Step 0; build the relay (~150 lines), egress helper and client wiring (~40 lines), unit and script edits, ~25 tests; deploy in watch-only mode.
- **Session 2:** after one market day, review the logs, enforce, then run the live proof and the full test suites with a separate verifier.

**Checks this triggers:** background programs and timers (unit files, server paths), plus the dashboard's own tests. No bot code files are touched, so the bot's command, mention, gateway and data-ingest checks are not triggered beyond the standard ones.
