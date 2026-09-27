# M0.2CD cleanup activation assessment

## Decision

A later bounded owner-data cleanup may be proposed, but cleanup must not be
enabled now. M0.2CC proves the removal action on temporary synthetic files. It
does not identify which current owner files are eligible, bind the current legal
holds, or prove that a real dry-run plan still matches the current files and
complete-set records.

Checked-in `cleanup_enabled` remains `false`. This assessment removes no file,
runs no cleanup command and changes no product setting.

## Required next evidence

M0.2CE may run only the existing dry-run path against the configured owner-data
root. It must record:

1. the exact configured root identity and the checked-in off switch;
2. every proposed class 3, 4 or 5 target, its reason and file identity;
3. the complete legal-hold input used for the plan;
4. each affected date's current publication pointer, complete-set proof and
   source identities;
5. the age rule and current disk-reserve result; and
6. an explicit zero-removal result.

Unknown, missing, changed, incomplete or held state leaves the target out. Class
1 primary records and class 2 supporting records remain ineligible. The dry-run
record needs fresh independent review before any separate removal proposal.

## Activation boundary

M0.2CE is evidence collection only. It may not flip the cleanup switch, remove
or move owner data, change retention ages or reserve limits, widen eligible
classes, or use a dry run as permission to delete. Any later removal needs a
separate exact target set, fresh pre-removal checks, an owner-authorized
destructive step and independent review. The checked-in switch stays off after
that bounded run as well.

The server storage manager is separate. Its verified archive process covers old
test working copies under its own 175 GB hard and 165 GB operating limits. It
does not authorize removal of market-data records by the collector cleanup.

Source qualification, D-104 gaps, historical completeness, validation,
promotion, Strategies #5 through #8, alerts and live use remain unchanged and
blocked by their own gates.

## Protected verification record

The controller's protected focused phase passed once at 2026-09-24 16:34:45
Pacific. It ran these two selectors:

1. `tests/test_full_chain_collector.py::test_storage_cleanup_is_checked_in_off_and_dry_run_is_default`
2. `tests/test_full_chain_storage.py::test_cleanup_defaults_to_dry_run_and_removes_nothing`

The selection reason was `builder named directly affected checks`. The phase
reported `test_count: 2`, `runs: 1`, and controller wall time `4.678` seconds.
Its published artifacts are in
`/root/trade-alerts-builder/runs/20260924-163021-849172-build/published-artifacts-88f8bc03d0ac`.
The verification handoff keeps the original tested-source hash
`87701a044367faafd10ed6798b6c26c1a2cdbcb2ffd6e60225a65a4fe75afe25`.

This records the focused offline contract only. It does not enable cleanup,
prove a current owner-data target set, or authorize removal. Cleanup remains
off and no owner file was removed. Independent review still decides acceptance
of this assessment.
