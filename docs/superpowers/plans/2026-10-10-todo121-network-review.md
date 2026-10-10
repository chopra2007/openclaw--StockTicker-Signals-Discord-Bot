# TODO #121 network plan — independent review and reconciliation

Date: 2026-10-10 Pacific. This is a planning record, not authorization to execute.

## Independence and method

1. Codex inspected project rules, current live #121 notes, loaded service units, process/cgroup/socket state, and deployed source. Codex saved its own proposal before Claude received any recommendation.
2. The locally installed Claude Code CLI was authenticated. Its original version 2.1.81 returned the literal error: "Claude Code 2.1.81 does not support this model; version 2.1.280 or newer is required." The supported `claude update` command updated this local installation to 2.1.296. No repository or server runtime package was upgraded.
3. The independent call used `claude -p --model claude-opus-5-5 --effort medium`, with tools disabled and explicit read-only instructions. It received project rules, current TODO notes, loaded units, relevant deployed source and observed live state, but NOT Codex's proposal. Successful result metadata named `claude-opus-5-5` and recorded no tool permission requests.
4. Only after Claude returned its own proposal did a follow-up CLI call receive Codex's original and the comparison. New read-only source evidence was shared to settle library support, token-copy needs and research-import questions.
5. A further CLI call reviewed the concrete final plan. The result is appended below. All successful calls used the requested model and medium effort. Raw evidence, which contains private project context, remains outside the public repository.

The original proposals are retained for traceability, not treated as automatically verified facts. The final plan states what was actually inspected and labels unproved rollout gates.

## Comparison

| Issue | Codex original | Claude original | Agreed resolution |
| --- | --- | --- | --- |
| Required sources | Seven exact HTTPS hosts | Same seven | Closed seven-host policy; verify transitive calls and representative traffic before enforcement |
| Local-port bypass | UID/port-specific firewall plus systemd ceiling | Loopback-address ceiling alone | Dedicated IPv4/IPv6 nftables table; compute reaches proxy port only; supervisor no IP; other local users cannot use proxy |
| Initial observation | Strict relay; measured needed paths | Broad watch-only relay | Relay strict from first deployment; temporary direct-egress log only while old worker restriction gap remains explicitly open |
| Success criteria | Real paths, negative tests, honest outages | Every host appears successfully in logs | Exercise authorized paths; separate provider outage/permission/quota from rule denial; unproved paths remain unproved |
| Schwab routing | Explicit opt-in, bot defaults preserved | Mutate private client session in dashboard | Public opt-in context field; validate session proxy invariant; shared-scanner checks triggered |
| CONNECT boundary | Host/port only; privileged supervisor trusted | Boundary less explicit | No TLS interception; encrypted-host/path and compromised-supervisor protections explicitly outside scope |
| Rollback | Exact scoped restore, cached mode first | Broader release revert or allow-all mode | Reverse only task-owned matching changes; preserve subsequent edits; emergency unrestricted state explicit; keep proxy until clients restored |
| Size | 2–4 engineering days plus market observation | About two sessions/150-line proxy | Medium, 2–4 engineering days plus full market-session observation; no proxy line-count target |

Claude's reconciliation explicitly said: "I agree with Codex on all six points." It accepted the local-port guard, strict relay, larger estimate, written security limits, explicit Schwab opt-in and scoped rollback. Codex accepted Claude's concrete public proxy field, invariant check and persistent rules service. Worker requires the rules service and wants the proxy; outage fails closed without tying independent quota/authority services to it.

## Unresolved disagreements

No blocking design disagreement remains. The final check below explicitly accepted the concrete plan. Both reviewers agree that optional TLS-handshake inspection and redesign of the trusted privileged launcher are separate future work. No new implementation or broader TODO was opened here.

Unresolved facts are implementation gates, not reviewer disagreement: complete observed traffic, real cgroup-BPF and UID/port enforcement, an unused proxy port, resource/response limits, and successful authorized provider calls through the proxy. Unknowns never count as passed tests.

## Artifacts

- [Agreed plan](2026-10-10-todo121-dashboard-network-restrictions.md)
- [Codex original](2026-10-10-todo121-network-codex-proposal.md)
- [Claude independent original](2026-10-10-todo121-network-claude-proposal.md)

## Final Claude CLI check

## ACCEPT

The plan matches what we agreed. I see no blocking corrections and no unresolved disagreements.

**The three choices you asked me to check are right:**

1. **Requires the firewall rules, Wants the proxy.** A missing firewall means the worker must not start. A missing proxy only makes sections show "unavailable." That is the correct split.
2. **Proving the systemd limit by behavior, not by bpftool.** A disposable test child started by the same launcher, whose blocked connections fail as expected, is enough proof. Making "can't prove it" a rollout blocker is stricter than my proposal, which counted on the firewall's user rules as a backup. I accept the stricter version.
3. **No new TODO items added during planning.** That fits a planning-only task. The final report should still mention the optional hardening ideas in one sentence each, so they are written down and not lost. Those are: checking the website name inside the encrypted handshake, dropping the supervisor's extra permissions, and limiting the bot-owned services.

**Two notes for the person who carries this out. Neither blocks the plan:**

1. **Change the compute config and its checker together.** `validate_config` rejects any compute config whose fields don't exactly match `FIELDS['compute']`. If the new proxy field reaches `/etc/member-dashboard/compute.json` before the matching code, or the code before the file, every new compute child fails at startup. Every report section and the assistant would go down. Task 2 or Task 4 should state this ordering, and the rollback should undo both together.
2. **Firewall log times.** The temporary log-only rule writes kernel timestamps, which are not in Pacific time. Convert them to Pacific before showing any of them to the owner.

**What I checked against our earlier agreement:**
- The seven hosts and how each one is used.
- The firewall split:
  - compute may reach only the proxy port;
  - supervisor gets no IP traffic;
  - other non-root users can't reach the proxy;
  - the proxy itself may make outside connections only to public addresses.
- The worker limit is `127.0.0.1/32`, which leaves out the local name-lookup service at `127.0.0.53`.
- If a lookup returns any private address, the whole connection is refused.
- The proxy uses the address it checked, with no second lookup.
- The proxy is strict from the first live deployment.
- The pass rule allows an honest "unavailable" when a provider is down or a cap is hit.
- Schwab gets an opt-in proxy setting, the bot's default stays unchanged, and the bot's checks on that shared file are triggered.
- The limits are written down candidly: CONNECT does not stop traffic hidden behind a shared CDN, and the supervisor stays a trusted program.
- Rollback touches only this task's changes and never runs a full release over other work.
- The size estimate is 2–4 engineering days plus market-session observation.

Codex incorporated both nonblocking notes: paired config/validator activation and rollback, and Pacific display of firewall logs. Optional wider limits for bot-owned helpers are outside this plan, alongside TLS handshake checks and launcher privilege redesign. No new task was added and no implementation was performed.
