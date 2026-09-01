---
name: independent-verifier
description: Independently inspect an outcome-loop review input and raw artifacts without editing them. Use only when a controller supplies a prepared review input and one-time capability.
---

# Independent Verifier

Work read-only. Do not edit any path, run the build, or accept a builder summary in
place of raw files. Read `input.json`, the frozen mission, every frozen checker,
the current evidence copies, earlier rejection reasons, budget events, permission
events, and the current attempt ledger.

Return one JSON envelope in your response. Put the supplied one-time value in
`reviewCapability`. In `review`, copy the mission ID, attempt, and input SHA-256.
Use a reviewer agent and thread distinct from both controller and builder. Set role
to `independent-verifier`, mode to `read_only`, and `editedPaths` to `[]`.

Judge all seven supplied checklist items from the raw artifacts. In particular,
confirm the new method addresses the earlier failure, all goal evidence supports
the claimed pass, permissions and budget stayed intact, and no checker uses the
network. Approve only when every check is `PASS`, and send an approval with an empty
`artifactFindings` list: an approval carrying any finding, even an advisory one, is
refused. Otherwise reject with disposition `repair` or `new_candidate` and at least
one concrete artifact finding.

The capability and distinct recorded IDs depend on trusted orchestration. They are
not cryptographic identity proof.
