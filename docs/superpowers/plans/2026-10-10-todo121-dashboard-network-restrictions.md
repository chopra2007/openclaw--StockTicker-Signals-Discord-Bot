# TODO #121 dashboard background-service network restrictions — implementation plan

> Planning only, 2026-10-10 Pacific. No implementation, deployment, service restart, firewall change or production write was performed. Future execution requires a separate instruction. For future agentic execution, use the executing-plans skill task by task; this document does not authorize execution.

**Goal:** Let the dashboard compute process reach its supported providers through one restricted local relay, while blocking direct outside connections and access to other local network services.

**Architecture:** Explicit client routing through a dedicated local HTTPS CONNECT proxy, backed by worker systemd IP restrictions and a dedicated nftables table (the server's packet-filter rules). Keep existing local Unix sockets, databases, quota admission and permission checks. The bot stays outside the dashboard rules.

**Tech stack:** Existing Python/asyncio, aiohttp 3.14.3, requests, Linux cgroup v2, nftables, systemd 249; no paid service or new Python package proposed.

**Spec/evidence:** The user's planning-only request; `docs/agents/PROJECT_RULES.md`, `docs/agents/WORKFLOWS.md`; live `TODO.md` #121 and `todo/member-dashboard-phaseC-plan.md`; deployed sources and loaded units inspected on 2026-10-10 Pacific. Original proposals and reconciliation are linked below.

## Scope and current evidence

The live repository is `/home/openclaw/.openclaw/workspace`; the deployed dashboard release is `/opt/member-dashboard/current`, which has no `.git`. This planning worktree predates the dashboard files. Read the current live and merged source before future edits; do not copy this worktree over production or replace the other session's edits.

- Live API, frontend, worker, quota and authority were active during inspection. Worker MainPID 1132383; compute PID 1132421 ran as the separate compute user inside the worker's `compute/<id>` child cgroup. A socket snapshot showed outside TCP/443 connections owned by that compute process. This is evidence of external use, not a complete host or traffic inventory.
- Loaded worker unit has no IP deny/allow rules. It retains launcher capabilities and delegates its own cgroup. Compute explicitly drops effective, permitted, inheritable and ambient capabilities before importing application code.
- API and frontend already allow only localhost. Authority, quota and archive allow Unix sockets and deny IP. Preserve these limits.
- Deployed network clients set `trust_env=False`, so an environment proxy alone will not route them. Live aiohttp 3.14.3 exposes the session-level `proxy` argument. Budget wrappers disable redirects; news, Nasdaq and model calls disable redirects explicitly.
- Server resolver is `127.0.0.53`; nftables is installed. Kernel is 5.15 and systemd is 249. Effective cgroup-BPF enforcement has NOT been proved by this read-only inspection; prove it in isolated Linux tests before enforcing.
- The loaded Schwab sync script performs local file/lock/copy operations. Dashboard SchwabClient has `refresh_allowed=False`; the bot-owned renew service refreshes tokens. Neither token renewal nor arbitrary publisher links belong in the worker allowance.
- Current TODO #121 records the worker allowlist as open after the feed concurrency repair. Historical launch statements in the deployment README are not current production proof.
- Live checkout contained existing TODO, dashboard feed/test and unrelated options-flow edits plus evidence files. No live files were changed here. Local starting Git status was clean. During review, another session also changed the live market-board source and test; those were left untouched. Final hashes of the three unrelated options-flow files matched their earlier readings.

## Required connections

Only exact names over HTTPS, TCP port 443. No wildcards, IP literals, arbitrary ports or automatic additions.

| Host | Required use | Deployed evidence |
| --- | --- | --- |
| `api.schwabapi.com` | Quotes, price history, expirations and option chains; GET under `/marketdata/v1/` | `operations.provider_routes`, `research_registry`, isolated SchwabClient, market board and track record |
| `openrouter.ai` | Assistant and Custom Stock Analysis synthesis; POST `/api/v1/chat/completions` | `assistant_transport.ENDPOINT`, `analysis_collector.CappedSynthesis` |
| `www.sec.gov` | Company ticker map `/files/` and filing documents `/Archives/` | `operations.provider_routes`, SecContext, SEC event/notice collectors |
| `data.sec.gov` | Filing lists `/submissions/` | Same SEC context and route inventory |
| `api.nasdaq.com` | Company name, analyst targets/ratings and earnings date | `street.BASE` |
| `www.bing.com` | News RSS `/news/search` | `news.BING` |
| `news.google.com` | News RSS `/rss/search` | `news.FEED` |

Keep authority, quota, exit-control and launcher gate connections on their existing Unix sockets. Market-source reads remain file reads. Compute needs no direct DNS: the proxy resolves destination names.

Do not add Yahoo, Finnhub, Brave, Discord, Drive, arbitrary news publishers, OAuth refresh, public-site TLS handling or certificate renewal to the worker list. The reviewed research computation consumes supplied records; a yfinance mention in it is a comment, not a call. Complete the transitive source scan and traffic observation before treating the seven hosts as a final measured inventory. Links in news records are displayed for the member's browser, not fetched by compute.

Bot-owned renew and size-check services, root token sync, the public reverse proxy, certificate renewal and Drive maintenance are separate boundaries. Do not apply the compute UID rules to the bot's user. Any wider hardening needs a separately scoped review; do not expand this task into it.

## Security contract and limits

- Compute can initiate IP traffic only to the chosen IPv4 loopback proxy port. Supervisor initiates no IP traffic. Unix sockets remain usable.
- Proxy accepts CONNECT only to the seven exact names on port 443 and resolves them itself. Reject credentials in authorities, numeric addresses, suffix lookalikes, trailing dots, malformed encodings, alternate ports and ambiguous names. DNS results must all be public unicast; reject loopback, private, link-local, multicast, unspecified, reserved and IPv4-mapped private addresses. Connect to the vetted address without a second unchecked lookup; revalidate on each new connection. Reject mixed public/private answers.
- End-to-end TLS certificate checks stay enabled. Never decrypt TLS, log credentials, request bodies, URL queries, prompts or response text. Log only destination name, verdict/reason, connection counts, byte totals and duration.
- CONNECT checks the requested destination and its resolved address. It cannot enforce encrypted HTTP method/path, model quotas, or prevent an arbitrary malicious client using a different encrypted hostname on a shared CDN address. Existing application route/quota checks remain essential. Do not claim stronger domain isolation or general data-exfiltration prevention. A future requirement for that stronger boundary needs a separate reviewed design.
- The supervisor remains a trusted privileged launcher. Its retained SETUID/SYS_ADMIN permissions mean UID rules are not a hostile-supervisor containment guarantee. This task constrains normal supervisor behavior and an unprivileged compute child. Do not quietly rewrite the launcher or assert its compromise is contained.
- Proxy outage or a denied destination fails closed: no direct retry and no automatic unrestricted mode. Preserve cached dashboard reads and honest unavailable messages.

## Global constraints

Preserve all concurrent work. Keep quota and authority services running; the bot depends on independent quota admission. No host-wide firewall flush, provider permission change, new paid provider or higher testing budget, TLS interception, new credential, dependency upgrade or unrelated cleanup. Owner-visible dates and logs use Pacific time. The plan does not mark TODO #121's launch follow-ups complete.

## Review focus

1. Alternate loopback ports and IPv6 must not bypass the proxy-only rule.
2. A new compute child, restart or stale inherited socket must not escape enforcement.
3. DNS changes and mixed public/private answers must not reach internal services.
4. Missing news/Nasdaq/model data must be distinguished from a network-rule failure.
5. Rollback must preserve edits made after the saved deployment snapshot.

## Task 1 — Refresh evidence and freeze the proposed policy

**Files to read:** current `member_dashboard/operations.py`, `compute_launcher.py`, `news.py`, `street.py`, `assistant_transport.py`, `analysis_collector.py`, `market_board.py`, `track_record.py`; shared `consensus_engine/utils/provider_budget.py`, isolated SchwabClient and transitive research imports; deployment `provision.sh`, `release.sh`, `scripts/dashboard_power.sh`; loaded worker/proxy/filter configuration.

- [ ] Record current Git status, SHA256 hashes of every touched file and all pre-existing dirty files, resolved release path, users, unit/drop-ins, firewall tables, current routes and port listeners. Preserve exact originals privately; never archive secrets into public docs.
- [ ] Refresh the isolated implementation checkout from current merged source, while leaving both existing checkouts and live dirty work intact. The seven-provider list remains closed until reviewed evidence proves another required call.
- [ ] Search transitive imports for real HTTP/SDK/socket sends and distinguish pure calculations and comments. Exercise idle maintenance and all authorized report/assistant paths during observation; never infer requirements from every URL string.
- [ ] Select `127.0.0.1:3446` only after confirming the port is unused; keep one root-controlled endpoint shared by policy and clients. If occupied, select a documented unused port consistently and repeat port-specific tests.
- [ ] Freeze proxy bounds after comparing normal response sizes/timeouts: proposed 32 total tunnels, 8 per host, 8 KiB headers, 5-second handshake, 30-second idle, 120-second lifetime, 64 KiB relay buffers and 32 MiB per tunnel. Prove legitimate option/report responses fit; change bounds explicitly if evidence requires it.

**Deliverable:** sanitized seven-host policy and baseline; no production enforcement yet.

## Task 2 — Build explicit routing and a bounded relay in isolation

**Create:** `member_dashboard/egress.py` for the root-controlled client endpoint; `member_dashboard/egress_proxy.py` for CONNECT parsing/resolution/relay; `deploy/member-dashboard/egress-policy.json.template`; `deploy/member-dashboard/member-dashboard-egress.service`.

**Modify:** compute config schema/bootstrap in `member_dashboard/operations.py` and `deploy/member-dashboard/compute.json.template`; the five aiohttp paths (SEC, news, Nasdaq, assistant, synthesis); explicit dashboard opt-in proxy support in isolated SchwabContext/SchwabClient. Preserve direct bot defaults.

- [ ] Write behavioral tests first in new `tests/member_dashboard/test_egress_proxy.py` and `test_egress_clients.py`: a trusted fixture TLS server receives the actual requests through the relay, with the expected method/body and certificate checks. Test model completion/streaming as implemented, cancellations, quota reservations/completions, SEC bodies and threaded Schwab requests. No tests consisting only of source-string matches.
- [ ] Build a reviewed asyncio CONNECT relay using existing libraries, with strict parser, vetted DNS/address pinning, backpressure, connection limits, timeout and cancellation cleanup. No target line count and no broad production allow-all mode.
- [ ] Give the relay its own unprivileged user, no provider secrets, no bot database, no launch capabilities and a hardened unit inside the dashboard slice. Start with a 128 MiB ceiling and verify aggregate capacity; adjust only from measurements.
- [ ] Set aiohttp session proxy explicitly with `trust_env=False`. SEC still passes through BudgetSession; model requests keep budget/cost fences. Validate locked-library compatibility rather than relying on an assumed minimum aiohttp version.
- [ ] Add a validated optional proxy field to the dashboard-only Schwab context and set requests proxies through its public construction path. Default remains no proxy for bot callers. Preserve the existing no-redirect, no-implicit-retry, adapter and borrowed-token safety checks; avoid private `_session` mutation from dashboard bootstrap.
- [ ] Change the exact-field compute config validator and compute config together. Quiesce the worker during the paired code/config swap, validate the target config with the target code before restart, and restore that pair together on rollback. Keep cached API/frontend and independent control services available. Missing/invalid dashboard proxy configuration must fail closed in enforced operation. Test proxy disappearance mid-request; failed requests retain honest uncertain quota accounting and cached reads still work.

**Deliverable:** provider traffic routed through the strict proxy in isolated tests; application route checks still apply to original provider URLs.

## Task 3 — Block bypasses and prove the real OS boundary

**Create:** `deploy/member-dashboard/member-dashboard-egress.nft`, `deploy/member-dashboard/install-egress-rules.sh` and `deploy/member-dashboard/member-dashboard-egress-rules.service` for scoped persistence and ordering, and `tests/member_dashboard/test_egress_linux.py`.

**Modify:** worker unit plus provisioning/release/power scripts and deployment README. Keep other service rules intact.

- [ ] Use a dedicated `inet` table covering IPv4/IPv6. Match actual resolved dashboard UIDs. Compute output permits only TCP to the chosen `127.0.0.1` proxy port, then rejects everything else. Supervisor IP output is denied. Put these restrictions before broad established-connection accepts; do not alter unrelated tables or allow established sessions to bypass new rules.
- [ ] Deny other nonprivileged local users connections to the proxy port. Permit proxy replies on its listener connections, resolver traffic only to the current local resolver on UDP/TCP 53, and outside TCP/443 only to public addresses. Deny private-address provider connects independently of the proxy's DNS checks. Host root remains trusted.
- [ ] Worker systemd uses `IPAddressDeny=any` and `IPAddressAllow=127.0.0.1/32`, not a blanket localhost allowance. Compute inherits this ceiling. Firewall limits ports and UIDs; systemd alone is insufficient. Proxy is a separate service outside the denied worker cgroup.
- [ ] Use worker Requires/After on the rules service and Wants/After on the proxy, so a proxy outage returns unavailable rather than restarting independent control services. Order firewall policy before worker startup on boot and deployment; worker startup must fail if policy cannot install. Preserve policy across daemon-reload/reboot and avoid rule duplication. Proxy failure does not clear rules or open a direct path. Ensure dashboard on/off scripts cannot remove the guard while children remain.
- [ ] In isolated Linux services matching the real launch/cgroup structure, test all seven fixture providers allowed; direct outside IPv4/IPv6 TCP/443 and other ports, UDP/DNS, other loopback ports (including API/frontend), unknown CONNECT hosts, invalid certificates, non-CONNECT requests, DNS-to-private/mixed answers, redirects, proxy outage and unauthorized local clients denied.
- [ ] Repeat after compute recreation, worker restart and reboot-equivalent unit activation; test pre-existing connections close at enforcement and no external socket is inherited. Verify effective cgroup-BPF filters using available host tooling or a behavioral test plus filter inspection. Missing enforcement support blocks rollout; no warning-only acceptance.
- [ ] Check quota/authority Unix RPC, borrowed-token sync, database ownership, cached feed and account permissions still work. A custom malicious-client/CDN-host test records the documented CONNECT limitation, rather than claiming path or encrypted-host enforcement.

**Deliverable:** enforced proxy-only compute traffic with genuine Linux denial evidence; no bot or shared firewall disruption.

## Task 4 — Staged observation, production acceptance and rollback rehearsal

**Modify:** deployment README and the current TODO #121 detail notes, only at future execution after rereading them. Add the new service to relevant provision/release/on-off paths after inspecting their real behavior.

- [ ] Before live installation, run the dashboard suite and all shared-Schwab/provider-budget dependents, plus the project regression baseline using the authoritative Linux runtime. Run impacted bot ingest/quote/options checks because the shared scanner opts into routing. Record existing failure IDs; do not weaken checks.
- [ ] Rehearse exact rollback in isolation. Complete allowed/denied network tests and capacity checks before any production change.
- [ ] First live stage: install the strict seven-host relay and explicit client routing. Use a temporary scoped log-only rule to observe direct dashboard IP traffic before blocking it; the existing unrestricted worker condition is clearly recorded as still present. Bound/rate-limit the log to avoid load; convert kernel/firewall log times to Pacific before showing them to the owner. Do not widen the proxy allowlist.
- [ ] Exercise authorized ticker research, SEC details, options/expected moves, analysis and assistant, market strip/history/outcomes/setup maintenance, cached screener and a 20-member feed burst. Observe one full trading session and overnight chores. Schedule the future observation check with retries and cleanup only when execution is authorized; create no timer or automation during this planning task.
- [ ] Investigate each direct bypass/unknown needed host. A missing required call blocks enforcement until reviewed source/routing and tests are fixed. Distinguish remote 429/outage or permission denial from proxy/filter denial; do not require successful data from an unavailable provider or all seven hosts appearing naturally in one log.
- [ ] In a short dashboard-only maintenance window, install the scoped enforcement policy atomically, apply worker drop-in/unit, daemon-reload and restart the worker to kill old compute connections. Keep quota, authority, bot and frontend/API running unless a measured dependency requires a separately reviewed action.
- [ ] Re-run positive/negative tests and real HTTPS report/assistant paths after restart; confirm cached feed/auth/admin-denial behavior and market-update cadence. All denial tests pass, zero unreviewed direct bypasses, no critical data lost and no material latency/capacity regression. Compare to measured baseline; >10% sustained bot-latency rise blocks acceptance.
- [ ] Run standard bot/gateway/symlink/model-health checks and touched background-service ownership checks. Separate current observations from earlier recorded feed errors; existing `feed_projection_unavailable` log entries are not proof of an egress failure.
- [ ] Observe through another full trading session after enforcement. Report required-host successes or honest provider unavailability, denial reasons, resource usage and dashboard latency. Only then mark the worker-egress follow-up complete; the rest of #121 stays open.

### Rollback

Prefer cached dashboard mode while investigating. For urgent recovery, explicitly record that restoring the former unrestricted worker state temporarily removes this protection; never silently use an allow-all proxy.

1. Compare current hashes with the deployed manifest. If later edits exist, apply a reviewed reverse patch to this task's changes only; never overwrite them with an old full release.
2. Restore the previous client/config versions while keeping the proxy available for any remaining routed clients. Restore only this task's worker unit/drop-in and remove only its dedicated firewall table/service dependencies. Maintain the external guard until the intentional switch to the former state.
3. Daemon-reload and restart only the worker to replace every compute child. Verify routes/quotes/reports/permissions, token copying and independent quota/authority services. Confirm both bot services and their health remain intact.
4. Stop the proxy only after no client references or tunnels remain. Remove temporary observation rules by exact identity. Never flush the server firewall or restart bot/quota/authority as a shortcut.
5. Record cause, exact restored files/rules and residual security exposure. Re-enable enforcement only after the failure has a fixture test and all acceptance gates pass.

## Size and remaining evidence

Medium operational/security task: approximately 2–4 engineering days plus observation across full market sessions (some waiting time can overlap). Roughly 20–25 source/config/deployment/doc files including 3 focused new test modules; this is an estimate, not a promised line count. A stronger boundary against a compromised supervisor or arbitrary encrypted traffic on approved/CDN hosts would enlarge the task and needs another design.

Unproved implementation gates: complete transitive traffic inventory, effective cgroup-BPF/UID filtering with the real launcher, free proxy-port availability, response/resource bounds and real provider paths after routing. These are measured acceptance requirements, not permission to deploy now.

## Independent review record

Codex wrote its proposal before Claude saw it. The first successful local `claude -p` call used `claude-opus-5-5` with `--effort medium`, received the same raw evidence, had tools disabled and did not receive Codex's plan. Follow-up CLI calls compared the proposals and reviewed the agreed text. The original CLI was updated from 2.1.81 to 2.1.296 because the requested model required 2.1.280 or later; no project/runtime dependencies changed.

- [Codex original proposal](2026-10-10-todo121-network-codex-proposal.md)
- [Claude independent proposal](2026-10-10-todo121-network-claude-proposal.md)
- [Comparison and discussion](2026-10-10-todo121-network-review.md)

Claude accepted the concrete plan with no blocking corrections or unresolved disagreement. Its final advice to switch compute config/validator together and convert firewall log times to Pacific is incorporated above. The comparison document records the agreement. No runtime tests were run for this documentation-only task; document links, paths, private-data scan and preserved-work checks were performed.
