# Assessment of the reasoning failures in the 2026-06-13 session

**Status:** OPEN
**Created:** 2026-06-13

> Scope note: this is an **assessment only** — what the core problem is, the specific failures, the bottlenecks behind them, and why they matter. By the user's explicit instruction it contains **no solutions, fixes, or suggestions** on how to address any of it.

## The core problem

Across the 2026-06-13 `todo-sweep` session, one underlying fault produced multiple wrong or incomplete outputs: **I reliably possess the relevant rule or fact, but do not apply it at the moment I produce an answer.** The breakdown is in application/triggering, not in knowledge. It surfaces in two consistent shapes:
1. **Trusting a verdict or status string instead of the primary evidence** — accepting "Logged in", or a sub-agent's "it's down", as established fact rather than checking the underlying signal.
2. **Answering inside the immediate frame of the question** and not running the wider checks I am capable of — so known-relevant factors get omitted.

## The 6 failures (what went wrong, concretely)

**Substantive (a false or incomplete statement reached the user):**
1. **Codex availability.** Asserted Codex was "authenticated and available" based only on `codex login status` printing "Logged in." Never made a real API call. On first real use it returned 401 — the refresh token was revoked. The claim to the user was false.
2. **Apify #34.** Repeated a sub-agent's conclusion that the Seeking Alpha actor was "dead/down" without inspecting the response codes. Reality: HTTP 200, clean exit, $0 charged, 0 results across every ticker and both endpoints (news + dividends), with an upstream `credits_estimate` logged — an upstream credit/rate throttle on the actor author's backend, not an outage. It had returned data three days earlier with the identical request, and the earlier "500" was intermittent. Contributing factor: the sub-agents were given only a weak rate-limit hint, not the full "never conclude down; capture the code" standard.
3. **Downsides comparison.** Listed the downsides of both proposed approaches but omitted **context bloat** — the bottleneck most relevant to this project (the same session designed item #39 around it) and visible on the status line. It surfaced only after the user prompted twice.

**Minor (caught, little or no user impact):**
4. **#6 scope.** Presented the smart-levels stale-price bug as a "tiny fix to commit this session" before confirming its state; it was already fixed in committed code, so there was nothing to commit.
5. **Self-inflicted test kill.** A `pkill` pattern written to stop a hanging background test also matched the new foreground test just launched, killing it (exit 144). The pattern overlap was not anticipated.
6. **Tooling choice.** Began designing the work around the Workflow orchestration tool before checking the machine has only 2 usable cores (which would bottleneck it). Caught and pivoted to direct agents — but only after starting down the wrong path.

## The bottlenecks (the mechanisms underneath)

- **Passive rules do not gate action.** Rules held in CLAUDE.md / memory inform but do not interrupt at the instant an answer is produced; they depend on in-the-moment recall, which degrades under load.
- **Rules bind me, not my delegates.** A directive governing my own statements is not automatically carried into sub-agent instructions, so a sub-agent can produce a conclusion my own rules would forbid, and I then relay it.
- **Inherited conclusions bypass verification.** My "verify before claiming" reflex fires on claims I derive from scratch, not on verdicts or status that arrive pre-packaged (from a sub-agent or a status command); those are treated as findings, not as claims to check.
- **In-frame momentum.** When answering, I evaluate along the dimension the immediate question raises and do not reliably step out to adjacent dimensions (e.g. cost/context when asked about reliability), so I omit factors I know are relevant.
- **Knowledge ≠ application.** Holding a fact (context bloat is critical; "down" must be verified) does not make it an active criterion unless something forces it into the evaluation.
- **The existing corrective layer is not catching this class.** Calling something "down / flaky / transient" without checking the real cause has recurred repeatedly — roughly the sixth logged instance — despite multiple prior memory entries on exactly this pattern. The current corrective approach has not prevented recurrence.

## Why these failures matter

- They put **false statements in front of the user as fact** (Codex working; Apify dead). That is the specific thing the project's evidence standards forbid, and it erodes trust on each occurrence.
- The same application gap that produces a small omission (context bloat) is the **mechanism behind the highest-impact failure mode on real work**: on a long, complex feature, when context fills, older load-bearing facts (spec, decisions, test baseline, the always-on service/symlink/shared-file constraints) get summarized away or diluted, and decisions get made on a degraded picture — which can break a critical path without my noticing. So these are not isolated cosmetic slips; they share a root with the worst-case correctness risk.
- The **recurrence** (sixth time on the same provider-"down" pattern) shows the fault is persistent and self-reintroducing, not a one-off.

## Evidence / where this came from
- Session: discover run `todo-sweep-2026-06-13` (artifacts under `.claude/discover/todo-sweep-2026-06-13/`).
- Related prior instances (same class): memory entries `comm-check-fail-2026-06-13-section-3`, `comm-check-fail-2026-06-09-section-3`, `comm-check-fail-2026-06-02-section-3`, `comm-check-fail-2026-05-28-section-3`, `feedback_diagnose_before_blaming_providers`.
