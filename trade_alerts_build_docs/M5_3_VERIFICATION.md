# M5.3 historical replay

Date: 2026-09-09 Pacific. Status: **completed for independent review**.

The replay runner now stops before writing when the research records and state
changes do not use the same isolated temporary database. A two-connection test
covers a temporary research database paired with a different state-change
database. This repair changed code and tests, so earlier proof is historical.

`consensus_engine/historical_replay.py` replays supplied `StrategyContext`
records in time order through the existing strategy and state-change path. It
checks the fixed feature version, accepts only the recording output, and limits
storage to an isolated temporary database. Records with the same time keep their
supplied order. Missing or mismatched fixed facts stop that path.

## Historical proof before the storage-isolation repair

The historical protected broad acceptance run passed **1,234 tests** in
**297.666 seconds**, with zero failures, errors or skips. It ran
`tests/trade_alerts_contracts`, including the required historical replay cases.
Isolation had no unexpected denials and cleanup passed. The tested source hash is
`4b04f66f6a456ad3260f2b614d8ebd752fb77965192d25f0169bdc76aa59b9da`.
The 34-file published proof is at
`/root/trade-alerts-builder/runs/20260909-020640-796238-build/published-artifacts-c6c62c816cf4`;
its publication lists 964,602 bytes. It predates this repair.

The historical fresh-process comparison also completed. Both protected 26-test
runs passed in 192.93 seconds total. Their replay artifacts both have SHA-256
`2356f8e1ef8413154336ec881ce576963469040d3f4b283c14d3ebcd938459e0`,
so the four-item replay output matches across processes. The comparison proof is
at `/root/trade-alerts-builder/runs/20260909-020640-796238-build/published-artifacts-aa00678d16fb`.
All recorded selectors begin with `tests/`. For that dated proof only, the
complete 844-entry tested-source record had SHA-256
`8e905dffbc6803c63ea3b4ba713d44262e601691fba738261b137d4b5d8b99ac`.
That historical file is no longer available at the shared
`verified-manifest.json` path, which now holds the final manifest cited below.
The older `af00da6ada4d` acceptance and `f508173e9357` repeatability proof remain
dated history. They are not the current cited proof.

During the repair session, the protected launcher could not collect the new focused test in this sandbox.
It stopped at its first `os.chown` with `OSError: [Errno 22] Invalid argument`.
That launcher limit was later cleared by the final controller proof below.

- [~] **Historical M5.3 state:** the storage-isolation repair was built and fresh
  protected proof was still required at that time.
- [!] Actual source coverage and every earlier source, definition, options and
  executable-profit gate remain open. Supplied offline records do not prove
  strategy edge, profit, live delivery or recovery.
- [ ] Independent review remains the acceptance gate. After acceptance, M5.5 is
  the next dependency-ready milestone. M5.4 remains data-blocked.

No proposed rule was approved. All switches remain off. No provider, broker,
Discord, application, deployment, restart, order, purchase or Git write occurred.

## Final protected proof — 2026-09-09 Pacific

The current protected broad run passed 1,235 tests in 300.299 seconds, with zero
failures, errors or skips. Its proof is
`/root/trade-alerts-builder/runs/20260909-020640-796238-build/published-artifacts-01ea50453c2c`.
The focused protected stage also passed 1,235 tests in 307.077 seconds. The
separate fresh-process check passed 26 tests in 195.65 seconds and both replay
files have SHA-256
`2356f8e1ef8413154336ec881ce576963469040d3f4b283c14d3ebcd938459e0`.
Its proof is
`/root/trade-alerts-builder/runs/20260909-020640-796238-build/published-artifacts-8ace6b793dc0`.

The tested source hash is
`707c9e7071b02c02dbe87e10360fe9c32bc641e3703544330af87f2ddf7fb18b`.
The complete 844-entry tested-source record is
`/root/trade-alerts-builder/runs/20260909-020640-796238-build/verified-manifest.json`
with SHA-256
`455170ff5c69f0033e76839b24c317e60f233931336da1915dd05a9278e9e59e`.
The older `af00da6ada4d`/`f508173e9357` and
`c6c62c816cf4`/`aa00678d16fb` proof remains dated history.

- [x] **M5.3 offline historical replay:** repair, protected proof and records-only
  finalization are complete for independent review.
- [!] Actual source coverage and earlier source, definition, options and profit
  gates remain open.
- [ ] **M5.5 durable session and delivery recovery:** saved next milestone after
  independent M5.3 acceptance. M5.4 remains data-blocked.

All switches remain off.
