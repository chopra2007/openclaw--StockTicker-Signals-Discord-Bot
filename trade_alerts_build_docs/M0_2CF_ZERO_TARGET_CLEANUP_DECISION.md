# M0.2CF zero-target cleanup decision

## Decision

Close the current owner-data cleanup branch without proposing removal.
M0.2CE found no eligible target: its dry-run plan and removal lists were empty.
Cleanup remains off, and no owner file was removed.

This is a no-removal decision. It does not turn an empty plan into permission to
delete, and it does not reserve permission for a later changed plan.

## Evidence reviewed

`M0_2CE_CLEANUP_DRY_RUN_RECORD.json` binds the configured root, checked-in off
switch, supplied empty legal-hold list, per-date minute-part counts and ages,
notification-marker identities, and disk-reserve result. It records:

- 5,225 class 3 minute parts across 14 dates, with zero eligible candidates
  because every date lacked a current published complete-set pointer and proof;
- zero class 4 temporary-file candidates;
- four class 5 notification markers, all younger than the 30-day minimum;
- an empty dry-run plan and empty removal result; and
- zero owner files removed.

The passing reserve check changes none of those exclusions. The empty supplied
legal-hold list also does not make any file eligible.

## Reopening boundary

This cleanup branch may reopen only from a fresh eligible target set. A later
proposal must bind the then-current root, complete legal-hold input, exact class
3, 4 or 5 target identities, complete-set and source proof, age checks, file
identity, and disk reserve. Unknown, missing, changed, incomplete or held state
still excludes a target. Classes 1 and 2 remain ineligible.

Actual owner-data removal remains a separate destructive step. It needs exact
targets, fresh pre-removal checks, independent review and separate owner
authority. M0.2CE supplies none of those permissions because it found no target.

## Unchanged gates

Collector cleanup and every live switch remain off. No source is qualified and
no D-104, historical-data, validation, promotion, alert or live-use gate is
closed. The server storage manager remains a separate process and gives no
authority to remove collector market data.

## Historical blocked handoff — 2026-09-24 Pacific

The following assessment is superseded by the existing-data reopening below.
It preserves the earlier failure and does not describe the current next step.

The prior completed result confused completion of this no-removal decision with
permission to finish the whole build. Review rejected its empty next milestone
while M9.4 remained blocked. No failing product test was reported. The different
approach is to retain the sound cleanup decision and record the actual blocked
build transition, rather than invent another cleanup paperwork milestone.

ROADMAP's last M9.4 row still requires qualifying real held-out source evidence
and a promotable #1–#4 result. M9.1EN's synthetic `ENGINEERING_PILOT_ONLY` pass
does not supply that evidence. Under ROADMAP §14, Strategy #5–#8 implementation
cannot proceed through this gate. D-104 missing-field rules remain OFF and
untested; this correction does not turn those gaps into new blanket source
requirements or approximate missing fields.

The current progress list has no open dependency-ready next row. The shared
capacity and cleanup sequence through M0.2CE is already accepted. No further
eligible shared/data task is established by the current assignment. Therefore
the handoff is **blocked**, `next_milestone` is empty, and the roadmap is **not
all complete**. The no-removal decision remains finished; zero targets are not
a request for deletion authority. Reopening the build needs the real validation
evidence above, or an explicit change to the build order that preserves source,
promotion and live gates. Any new cleanup task still needs the fresh target
proof described above.

## Current handoff correction — 2026-09-25 Pacific

The cause of the rejected transition was an empty next milestone despite an
unfinished roadmap. The earlier blocked correction also missed ROADMAP's later
"Existing-data validation reopening" section, which opens **M9.1EP**. The
different approach is to use that existing concrete data-qualification task,
not create another cleanup assessment or repeat a product test for prose.

M0.2CF's assigned no-removal decision is complete. Proposed next milestone:
**M9.1EP**, subject to independent review of its eligibility. That task checks
the saved data and connects only supported first-four inputs before any allowed
frozen evaluation. It does not presume that saved files qualify, expose
previously untouched final dates without the governing safeguards, or close
M9.4. Missing-field-dependent rules remain OFF and untested under D-104.
Strategy #5–#8, promotion, alerts, spending and live operation remain gated.
The cleanup branch stays closed with no removals; the overall roadmap remains
unfinished. No new deletion authority is needed for this no-action decision.

## Preserved controller proof

The existing controller proof remains at
`/root/trade-alerts-builder/runs/20260924-164512-211676-build/controller-evidence.json`.
Its original `source_hash` is
`4c43771bcfe071352185321a579812aa7342868ef16ffe95671f0dd5ea4636df`.
Published artifacts remain at
`/root/trade-alerts-builder/runs/20260924-164512-211676-build/published-artifacts-3a8071644da0`,
including `publication.json`, `summary.json`, `run-1/pytest.log`,
`run-1/results.xml` and `run-1/isolation.json`.

The supplied controller record reports `tests.runs: 1`,
`tests.test_count: 4555`, `tests.wall_seconds: 1028.712`,
`tests.selection_reason: "records-only change reuses focused proof"`, and
`tests.selectors: ["tests/trade_alerts_contracts"]`.
The supplied `tests.focused` reports `phase: "focused"`, `runs: 1`,
`test_count: 4555`, `wall_seconds: 1028.712`,
`selection_reason: "builder named directly affected checks"`,
`selectors: ["tests/trade_alerts_contracts"]`, `exit_code: 0`,
`protected: true`, `stable: true`, and the same artifact directory.
No separate repeatability or broad-run figures were supplied; no such run is
claimed here. The time above is the controller wall time, not the pytest or
JUnit time.

This correction changes only this record and ROADMAP prose. The full milestone
delta remains DATA_REQUIREMENTS.md, DECISIONS_AND_OPEN_QUESTIONS.md, this record
and ROADMAP.md. Code, tests, configuration and protected inputs were not changed
by this correction. Prior attempts and published proof are preserved. No product
tests were rerun for the prose correction; the controller decides proof reuse
and independent review still decides acceptance and the M9.1EP handoff.

Final record check: the last ROADMAP rows are M0.2CF `[x]`, M9.1EP `[ ]`
and M9.4 `[!]`. The returned next milestone is M9.1EP; it does not close
M9.4. The published artifact fingerprints match `publication.json`, and the
documentation whitespace check passed. These are record checks, not a new
protected test run. The controller's full starting manifest remains at
`/root/trade-alerts-builder/runs/20260924-164512-211676-build/start-manifest.json`;
it is a starting snapshot, not a separately supplied tested-source manifest.
