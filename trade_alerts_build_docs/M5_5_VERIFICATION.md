# M5.5 durable session and delivery recovery

Date: 2026-09-09 Pacific. Status: **completed for independent review**.

`consensus_engine/session_recovery.py` reads already stored mechanical facts and
delivery intent through the existing M5.1 store and the existing database
framework, restores the versioned state chain, and decides what a restarted
session may still do. It opens no database, reads no credentials, contacts no
network, starts no application and creates no strategy fact. The caller owns the
isolated connection, the existing migrations and the recording sink.

## 1. What this milestone adds

- **Atomic facts plus delivery intent.** Intent still travels through the M5.1
  single-transaction write, so a database failure before persistence stores
  nothing and sends nothing. The new test drives that path with a forced insert
  failure and a counted sink.
- **One mechanical event per intent.** Each stored intent ends in exactly one
  final `:result` delivery fact. A crash before any send may retry while the
  candidate is unexpired. A crash after the send started stays `UNKNOWN`; it is
  never blindly replayed and never invents a receipt.
- **Expiry-aware retry.** An intent whose candidate has expired at recovery time
  never reaches the sink; it is closed as `REJECTED_BEFORE_SEND` with reason
  `EXPIRED_ON_RECOVERY`.
- **Versioned state recovery.** `StateTransitionEngine.restore` positions an
  unused owner at the end of a complete stored chain. It writes nothing and fails
  closed on a gap, a broken predecessor chain, a foreign scope, a rule or state
  mismatch, backward time, or an already-used owner. `RestoredState.as_dict`
  records the recovery, engine and store versions with the stream position.
- **Separate acknowledgment and outcome records.** A `HumanDecisionRecord` is
  stored under the new `ACKNOWLEDGMENT` kind beside, never inside, the delivery
  and outcome facts. It requires its stored candidate and a stored final delivery
  fact, cannot precede its candidate, and cannot rewrite a stored decision.
- **Recovered rendering must match the stored intent.** Recovery rebuilds the
  alert from canonical stored records and refuses to send when the text or the
  option facts differ from the saved intent.

Changed files: `consensus_engine/session_recovery.py` (new),
`consensus_engine/state_transitions.py` (`restore`),
`consensus_engine/event_store.py` (`ACKNOWLEDGMENT` kind and its candidate link),
`tests/trade_alerts_contracts/test_session_recovery.py` (new).

## 2. Acceptance slices proved offline

- **AT-06.** Database failure before persistence sends nothing; the crash-before
  and crash-after cases keep one mechanical event per intent; an uncertain send
  stays `UNKNOWN` without a blind resend; an expired intent never sends on
  recovery.
- **AT-07.** A continuous four-context replay and a crash/resume replay of the
  same supplied manifest store identical research rows, identical transition
  entries and the same replay fingerprint. Recovery reports the interrupted
  position (2) and state (`SETUP_FORMING`) before the resumed run replays from
  the start into the idempotent store and reaches position 4.
- **AT-10 (recovery slice).** Recovery reads one isolated temporary database
  only. A second connection on a different database, a database outside `TMPDIR`,
  a foreign store type and a missing transition store all stop the path. The
  recorded modes accept only the recording sink; there is no live mode.

These are offline contracts over supplied synthetic records. They do not prove
actual provider coverage, live delivery, human receipt, strategy edge or profit.

## 3. Protected proof — 2026-09-09 Pacific

All runs used the unchanged protected launcher
`scripts/testing/run_trade_alerts_contracts.py`, with zero failures, errors and
skips, no unexpected isolation denials and passing cleanup.

The controller-published stages below are the review copy. Their mechanical
figures are recorded in `M5_5_SUPERVISOR_TESTS.json` and `M5_5_LOCAL_CHECKS.json`,
with the controller's own evidence copied into `M5_5_CONTROLLER_EVIDENCE.json`.
The builder's earlier local timings for a single test file are superseded by
these figures.

- **Focused stage (23:37:09 Pacific):** `tests/trade_alerts_contracts` — 1,254
  tests passed in 323.19 seconds of controller wall time (319.923 seconds
  reported by pytest), inside the 420-second limit. Proof:
  `.../20260909-163637-638505-build/published-artifacts-7ea0158b0c9f`,
  35 listed files, 981,089 bytes.
- **Broad acceptance stage (23:42 Pacific, recorded at 23:45:38):**
  `tests/trade_alerts_contracts` — 1,254 tests passed in 313.07 seconds of
  controller wall time (309.878 seconds reported by pytest). Proof:
  `.../20260909-163637-638505-build/published-artifacts-573eaf0533d1`,
  35 listed files, 981,086 bytes.
- **Repeatability stage (23:45:38 Pacific, two fresh processes):** 19 recording
  selectors, 28 tests per process, 194.683 seconds for both runs (94.901 and
  96.201 seconds reported by pytest). Proof:
  `.../20260909-163637-638505-build/published-artifacts-ae450c7a169a`,
  67 listed files, 1,534,645 bytes.

The tested source hash is
`ce6313a72c90285a49a3e1e09e3d777b12bf949efc44056dd29823939c5c9b2b`. The complete
851-entry tested-source record is
`trade_alerts_build_docs/M5_5_TESTED_SOURCE_MANIFEST.json`; its canonical form
(sorted keys, compact separators) reproduces that hash exactly, so the published
stages cover the current code, tests, configuration and protected inputs. That
record is a snapshot of the tree as the stages found it at 23:45:38, so its own
entry and the entries for the M5.5 record files hold the bytes they had at that
moment; those record files were finalized afterwards and are documentation, not
tested inputs. The four milestone source and test files are unchanged from the
tested state: `consensus_engine/event_store.py` `9237a580…`,
`consensus_engine/session_recovery.py` `566bcc2e…`,
`consensus_engine/state_transitions.py` `eb29559e…` and
`tests/trade_alerts_contracts/test_session_recovery.py` `bc25f9b3…`.
Earlier same-day stages (`2e13ceb96538`, `afa56bb782b6`, `d2529a516de8`,
`41d7751caa66`, `67fb9aace7de`, `96ce217c6589`, `49df8eef259a`) remain dated
history.

These runs replace the earlier same-day stages. Two of those were interrupted by
the environment rather than by the code: a broad run stopped when the host disk
filled while writing its report, and the following builder process was refused on
a usage window. The 23:13–23:21 stages ran cleanly and were republished only
because the M5.5 record files were written after them, which changed the tree
hash without touching any source, test, configuration or protected input. Every
recorded artifact hash below is unchanged across all of those runs.

Every recorded artifact is byte-identical between the two processes:

| Artifact | SHA-256 |
|---|---|
| `m55-session-recovery-long-proof.json` | `cff15f68fd5396d7ea0cdaf42549817d9fa75988384b59ab6eac2ff9a3c34a97` |
| `m55-session-recovery-short-proof.json` | `ce2071380dd9264e0b73972afb3f098285c0703001eb08194ed9d25f7d78c1f7` |
| `m5_3_replay_artifact.json` | `2356f8e1ef8413154336ec881ce576963469040d3f4b283c14d3ebcd938459e0` |
| `m42-state-transitions-long-proof.json` | `095254267472dfde371184fa449465ba1d9cde8631710f9dbcf7e56a4d39990c` |
| `m42-state-transitions-short-proof.json` | `a839fa776c4e9559067589a0bd8530f0d892ee7e09ee292130f6b31ee2c00ab0` |
| `m51-research-event-store-long-proof.json` | `5a34168849a516af60ad437bc2aad5edc713c0bf7890b5f8f7470d57ab142a79` |
| `m51-research-event-store-short-proof.json` | `63f41036a98086befc5f6fe46e9ff0fe2a63ed2eb57cec52e88290cdae498139` |

Across the two repeatability processes 31 published files match byte for byte;
only `output.txt` and `results.xml` differ, and only in their timing text.
The replay fingerprint is unchanged from the accepted M5.3 record, so the
transition-engine addition did not alter replay output. The M5.5 recording proofs
are 4,386 and 4,387 bytes in both processes. Per-run test counts, zero
failures/errors/skips, empty unexpected-denial sets, passing cleanup, per-stage
artifact counts, byte totals and summary/publication hashes are recorded in
`M5_5_SUPERVISOR_TESTS.json`.

## 4. Boundaries kept open

- [x] **M5.5 offline durable session and delivery recovery:** implemented and
  proved offline for independent review.
- [!] Actual source coverage and every earlier source, definition, options and
  executable-profit gate remain open. Supplied offline records do not establish
  live delivery, receipt, recovery under real load or profit.
- [ ] M18 retains full load and failure hardening, operational runbooks and the
  rehearsed restart/rollback controls. M15.7 retains delivery refinement. M5.4
  remains data-blocked.

Named next milestone: **M6.1**, the `CRVOL_ORB5` eligibility/state machine. It is
now an open row in ROADMAP section 31 with its own `[!]` gate: the exact ARMED
thresholds need the still-PROPOSED M03B_ORB5_V1 definition, so only the offline
supplied-input state-machine slice is dependency-ready.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred.
