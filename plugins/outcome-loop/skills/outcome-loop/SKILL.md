---
name: outcome-loop
description: Run a frozen, evidence-backed mission through feasibility, building, independent review, and a deterministic final check. Use when work must continue after failed attempts until the measured goal passes or a declared stop condition is reached.
---

# Outcome Loop

Use `<plugin-root>/scripts/outcome_loop.py` as the only controller. From this
installed skill directory, that file is `../../scripts/outcome_loop.py`. Read
[references/mission-contract.md](references/mission-contract.md) before creating or
changing a mission.

Freeze the controller agent and thread at `init`. Record evidence before using it.
Authorize every side effect and cost before it happens, then record its real cost.
Do not begin building until all four mission-specific feasibility checks pass.

Use a builder whose agent and thread differ from the controller. After a passing
build, run `prepare-review`. Give its one-time clear capability and `input.json`
only to a newly created read-only reviewer. Pipe the returned envelope to
`review-result --from-stdin`; never save or display the clear capability.

Treat `COMPLETE` as true only when `final-gate` writes it. A failed goal starts a
new candidate attempt. A failed build stays on the same candidate for repair.
Stop only on a condition frozen in the mission. `STOPPED` is not success.

The recorded identities and one-time capability rely on trusted orchestration.
They separate roles and prevent casual replay, but are not cryptographic proof of
which person or process performed a role. The controller also cannot detect work
performed outside its ledger, so keep every authorized action on-ledger.
