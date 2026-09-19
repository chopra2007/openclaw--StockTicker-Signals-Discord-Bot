# M7.1 point-in-time HOD/LOD and compression for `HOD_COMP_RS`

Date: 2026-09-11 Pacific. Status: **completed for independent review** for the
bounded offline supplied-input slice. The separate `[!]` definition gate and the
`[!]` source gate in ROADMAP section 31 stay open. PLAYBOOKS section 13 still
owns the unresolved `HOD_COMP_RS` questions, M0.3B is PROPOSED, and M3.3-M3.5
keep the compression and structure definitions.

`consensus_engine/hod_compression.py` measures two things from one supplied
canonical minute `HistoryBatch` at one evaluation instant: the HOD/LOD frozen at
a supplied freeze instant, and one compression window described by the caller's
own definition. `tests/trade_alerts_contracts/test_hod_compression.py` covers
both paths.

A measured window is not a setup, an arming decision, an approved rule, evidence
of provider coverage or permission to act.

## 1. Why nothing is hardcoded

PLAYBOOKS section 13 lists the open `HOD_COMP_RS` questions by name: whether the
last-3 and prior-7 windows overlap, how a 3-8 bar compression is seeded, which
HOD is frozen, the RS15 warm-up, acceptance duration and tape fallback. M7.1
answers none of them.

- The module adopts no compression ratio, bar count, distance cutoff, buffer,
  acceptance minimum or arming rule. It compares no measurement against any
  threshold; it reports the ratio and the distances and stops there.
- The overlap question is handed back to the caller. `CompressionPolicy` carries
  `recent_bars`, `prior_bars` and `prior_includes_recent`, plus the caller's own
  version and definition reference. Supplying them adopts no proposed rule and
  claims no approval. A test measures the same bars under both answers and gets
  two different prior ranges.
- Which HOD is frozen is also the caller's: `reference_frozen_at` is supplied,
  and the module only refuses instants it cannot honour.
- A test asserts the module source carries none of the playbook's numbers.

Every number in the tests is a synthetic fixture.

## 2. What the milestone adds

- **Point-in-time freeze.** The reference extreme reads only the regular-session
  minutes that had already ended at the supplied freeze instant, and requires
  unbroken coverage from the session open to that instant. A bar that ends after
  the freeze can never reach it, so a later or final-session high cannot leak
  backwards into an earlier evaluation. The freeze instant must be inside the
  regular session, aligned to a whole minute and not after the evaluation
  instant; each refusal has its own name.
- **Compression window.** The last `window_bars` completed regular-session
  minutes at or before the evaluation instant, where `window_bars` follows the
  supplied overlap answer. The module reports the window high and low, the recent
  range, the prior range, the bar count, the ratio of recent to prior, and
  whether the whole window began at or after the freeze instant. Ranges are
  exact decimal differences, never float arithmetic.
- **Distances.** The distance from the window high up to the frozen HOD and from
  the window low down to the frozen LOD, both in units of the supplied minute
  ATR. The ATR arrives from the caller's own M3.6 feature; a missing or
  nonpositive ATR keeps both distances unavailable with a named reason, and a
  non-finite one is refused outright.
- **Separate fates.** The reference and the window are measured independently, so
  a refused freeze instant still reports a complete window and the reverse. The
  distances need all three inputs and name the first one they lack.
- **Named refusals, never a substitute value.** A missing, provisional,
  conflicting, low-quality, untraded, non-contiguous or unexpectedly overlapping
  interval keeps its own feature `None` with a reason and its inspected record
  IDs. Nothing is defaulted, interpolated or carried over from another instant.
- **One immutable `FeatureSnapshot`** under `M71_HOD_COMPRESSION_V1` and data
  mode `SUPPLIED_BAR_HOD_COMPRESSION`, so an M4.1 consumer must bind these values
  by full identity exactly as the M6.1 path already does.

## 3. What the new cases cover

- The freeze: the reference holds at 102.00/99.00 while a later 103.00 prints in
  the same session, an earlier freeze reports the earlier extreme, and a freeze
  after the evaluation, off a minute boundary, at the open or before the session
  is refused by name while the window still measures.
- Reference coverage: history that starts after the open is refused, one
  provisional minute names `REFERENCE_PROVISIONAL` and still reports the three
  inspected record IDs, and an all-quiet open names
  `NO_TRADED_REFERENCE_INTERVAL`.
- The window: the seven measured bars, their high, low, recent range, prior
  range, bar count, ratio and record IDs; the same bars under the overlapping and
  the split definition; a flat prior range reporting `ZERO_PRIOR_RANGE` instead
  of dividing; and a short, missing, untraded, foreign-instrument or unexpectedly
  overlapping window refused by name.
- A window that begins before the freeze is reported as such, not refused,
  because the seeding rule is not this milestone's to decide.
- Distances in supplied ATR units, and the missing, zero, negative and non-finite
  ATR answers.
- Incompatible or absent history: absent, foreign symbol, unknown venue basis,
  wrong price unit, wrong volume unit, daily interval and a closed day, each
  named on every feature with no input record IDs claimed.
- Supplied contracts: the policy must be explicit and coherent and is immutable,
  public scope is checked before any measurement, and the snapshot is deeply
  immutable and round-trips through JSON.
- One deterministic recording, `m7_1_hod_compression_proof.json`, holding the
  hash, byte count and every feature of seven snapshots across the minute
  boundary, both window definitions, the missing-ATR answer and a later freeze.

## 4. Boundaries kept open

- [x] **M7.1 offline measurement:** implemented and proved offline for
  independent review.
- [!] **M7.1 definition gate:** the `HOD_COMP_RS` compression ratio, bar counts,
  distance cutoffs, overlap answer, seeding rule, RS15 warm-up, buffer and
  acceptance duration stay unresolved under PLAYBOOKS section 13 and M0.3, M0.3B
  is still PROPOSED, and M3.3-M3.5 keep the compression and structure
  definitions. A supplied window adopts none of them.
- [!] **M7.1 source and historical-data gate:** every bar here is a synthetic
  supplied record. Actual point-in-time minute coverage, finality, corrections
  and adjustment history remain blocked under M0.2, M2.3, M3.1, M3.2 and M3.6.
  Nothing here measures profit or edge.
- [ ] RS and trend eligibility, the heads-up and actionable path, risk,
  confidence and suppression, and the replay and synthetic scenarios for this
  strategy keep their M7.2-M7.5 owners. Candidate assembly and delivery keep
  their M4.5/M4.6/M4.7 owners.

## 5. Protected proof

The controller's published protected stage supplies every count, timing, hash and
byte figure for this milestone; those numbers are not written here from any
builder-local run. The required selection is the whole
`tests/trade_alerts_contracts` directory, because the new module imports the
shared M2.2 history, M1.x record and M0.4 time-context code that most of the
directory also exercises, and because the launcher installs its isolation for the
whole collection.

This milestone states a repeatability need: `m7_1_hod_compression_proof.json` is
a recorded artifact, so the recording selection must be compared between two
fresh processes in addition to the acceptance run. Every earlier milestone
recording in the same runs must stay unchanged, including the M3.6 opening-range
recording and the M6.4 scenario artifact.

Tested milestone files: `consensus_engine/hod_compression.py`
`23b93c991d1896cc39a8175307691a71a6805fce05cc1c1215d7b71a6f8bae00` and
`tests/trade_alerts_contracts/test_hod_compression.py`
`5580e1a29fd25742632a4984f16c3124e9cf26bb97281740a91cfa9b03240422`.
`M7_1_LOCAL_CHECKS.json` records the inspected hashes and the local checks that
are not proof.

## 6. Exact next milestone

**M7.2 — RS and trend eligibility for `HOD_COMP_RS`**, now an open row in
ROADMAP section 31. M7.1's measured reference and compression window are its
direct inputs, so it is the next dependency-ready work. Its rule-bearing branch
stays gated for the same reasons recorded above.

No proposed rule was approved and no strategy rule was added. All switches remain
off. No provider, broker, Discord, application, deployment, restart, order,
purchase, paid fallback or Git write occurred. D-091 remains $25 authorized,
$0 used and $0 reserved.
