# M0.2A offline shared-storage contract

## 1. Scope and status

This is the version 2 offline contract for the existing forward collector in
`scripts/full_chain_collector.py`. It chooses limits and the tests required
before any cleanup can be implemented or enabled. It does not delete or move
data, change the collector, prove production capacity, or close any market-data
gate. All switches remain off.

The figures in section 2 are observed facts. The limits in sections 3–5 are
proposed engineering rules selected under the owner's 2026-09-13 research
authorization. They are not measurements.

## 2. Observed facts — 2026-09-13 Pacific

The current `todo-109` folder has eight completed option dates and one partial
date. The latest M0.2 inventory recorded 1.8 GB in 3,186 files, including about
1.1 GB of minute option parts and 662 MB of compacted chains. It also recorded
6.8 GB free on the 80.3 GB filesystem. A later direct metadata read found 6.56
GB free. The reason for the change is unknown.

The eight minute-part date folders contain 3,119 files. Their observed daily
sizes range from 131,899,528 to 151,503,120 bytes. This is a short saved sample,
not an approved daily-growth estimate. The machine reports 7,933,256 kB total
memory and 3,948,188 kB available at the time of the read. No peak-memory or
compaction-time measurement exists.

The current code writes Parquet files through a temporary sibling and then
replaces the destination. Daily option compaction still reads every minute part
into one in-memory table. It does not compare source and compacted record
fingerprints, recover an interrupted compaction, reserve disk space, limit peak
memory, or remove verified duplicate parts.

## 3. Retained record classes

Age is counted from the Pacific market date. A legal hold means a file is named
by a frozen research split, tested-source manifest, published proof, unresolved
incident, or independent review. A held file is never removed because of age.

1. **Primary market records — minimum 750 calendar days:** compacted option
   chains, stock quotes, stock bars, halts and event observations. Keep beyond
   750 days while held. These are the research inputs.
2. **Supporting records — minimum 750 calendar days:** sessions, open-interest
   snapshots, daily run reports and daily proof reports. Keep beyond 750 days
   while held. These preserve source meaning and allow an old run to be checked.
3. **Minute option parts — minimum 7 calendar days after verified compaction:**
   keep every part until the complete chain/open-interest/proof set passes
   section 6 and is durably published under section 5.1. Start the seven-day
   clock only after that pass. Keep parts beyond seven days while held or while
   any matching set member is missing or invalid. A partial date never qualifies
   for removal; missing open interest cannot qualify through chain-only proof.
4. **Temporary compaction files — through recovery:** keep an interrupted
   temporary file until the next offline recovery check. Recovery may remove it
   only after confirming that the published set is either the prior valid set
   or the complete newly verified set. Unknown or conflicting files block
   cleanup. A temporary file is never research evidence.
5. **One-time notification markers — 30 calendar days:** these zero-byte local
   markers may be removed after 30 days when no unresolved incident refers to
   them. Notification log retention remains owned by its existing system.

Removal must be a separate, off-by-default action. It must write a dry-run list,
refuse paths outside the configured data root, and remove only class 3, 4 or 5
records that meet every rule above. Classes 1 and 2 are not cleanup targets in
the first implementation.

## 4. Disk reserve and admission rules

The shared filesystem reserve is the larger of **12,000,000,000 bytes** or
**15% of filesystem capacity**. Before a poll, compaction or cleanup writes, the
program must estimate its source, destination and temporary-file needs. It must
refuse a new write when estimated free space after the write would cross the
reserve. It must not delete data automatically to admit that write.

For compaction, use this version 2 admission allowance, in whole bytes:

`W = max(ceil(2.25 * S), 2 * (C + O + P + A)) + E + T`.

- `S`: total selected minute-part bytes, retained throughout the operation.
- `C`, `O`, `P`: enforced upper bounds for the new chain file, open-interest
  file and proof manifest, including encoding and file-format overhead.
- `A`: enforced upper bound for the publication pointer and any recovery/report
  metadata written by the operation. No output may be omitted.
- `E`: bytes in all existing retained output sets and publication metadata.
- `T`: bytes in existing incomplete/stale output sets and temporary files.

The doubled complete-output allowance covers both staged members and their
temporary siblings, including open interest, proof and publication metadata.
The source multiplier remains a floor, not a bound on output expansion. `E`
and `T` are intentionally additional safety allowances even though current
free space already excludes those files. Accept only when current free bytes
minus `W` is at least the reserve; equality is allowed. Unknown output bounds
or sizes block admission. Check bounds and remaining reserve before each write;
stop without deleting inputs or prior sets if any bound is exceeded. No fallback
to the old chain-only estimate is allowed. M0.2B must publish the bound method
and measured bytes for every output. These are chosen limits, not capacity
measurements. With only 6.56 GB last observed free, the filesystem is below the
chosen reserve; this contract therefore does not declare collection ready.

## 5. Memory and compaction budgets

- Peak resident memory for the compaction process: **1,500,000,000 bytes**.
- Maximum decoded source batch held at once: **256,000,000 bytes**.
- Maximum compaction wall time for one Pacific market date: **15 minutes**.
- Maximum temporary output lifetime after an interrupted run: **24 hours**;
  recovery must inspect it before removal.

The implementation must read bounded batches and merge them deterministically.
It must stop safely when either memory or time budget is crossed. A stop leaves
all minute parts and the last verified output set unchanged. The
current all-at-once `pandas.concat` path does not meet this contract.

These values are first-version safety limits. M0.2B must record actual daily
growth, peak resident memory, temporary space and wall time. Any later change is
versioned and independently reviewed; observed results cannot silently widen a
limit.

### 5.1 Complete-set publication and recovery

A verified output is one immutable set for one Pacific market date: an option
chain Parquet file, its derived open-interest Parquet file and a proof manifest.
The manifest binds a deterministic set id, date, contract version, every source
part's identity/hash, both output paths, byte hashes, ordered-record hashes,
column sets and row counts. The publication pointer binds the set id and
manifest hash; the manifest does not hash itself. Use fixed serialization and
ordering, with no run-time clock or random path in compared proof bytes.

Preserve the existing duplicate-key rule: read parts in sorted path order,
retain row order within each part, and keep the last row for
`captured_at_utc, ticker, contract_symbol`. Derive open interest from those
chain rows, using the latest nonmissing value per ticker/contract and the
existing selected columns. Make equal-time ordering deterministic. Verify
both outputs against these source-derived records. Empty open interest must
produce an explicit empty file and a missing-data result; it cannot pass
complete-day verification or start the minute-part removal clock.

Write into a separate versioned set directory on the same filesystem. Finish,
flush, rename and verify chain, then open interest, then proof inside that
unpublished directory; flush the directory. Never overwrite individual members
of a published set. Only then atomically replace one publication pointer and
flush its parent directory. Readers and retention checks resolve the pointer
once and validate all three members together; legacy daily paths are not proof
of a valid set. M0.2B must cover offline readers before any future integration.

Before the pointer change, only the prior set is visible. After it, only the
complete new set is visible. Preserve the prior set's bytes and every source
part through all failure paths, including failure after pointer replacement.
Such a failure must not report success; reopening may see the old or complete
new set, but never a mixed set. With no prior set, report unavailable until a
complete set is published. Recovery validates source identities, all members
and the pointer before reusing an interrupted set. Missing, partial, corrupt
or conflicting members block publication and removal. A retry of the same
sources/version must yield identical bytes for all members and the pointer;
changed sources require a different set and cannot reuse old proof.

## 6. Required protected test plan for M0.2B

The planned protected file is `tests/test_full_chain_storage.py`. It uses only
temporary synthetic Parquet files and blocks outside connections.

1. `test_compaction_source_and_compact_records_match` checks the exact column
   set, values, row count and deterministic ordered-record SHA-256 for both
   chain and derived open interest after the section 5.1 duplicate-key rule.
   Cover duplicate/tied records and absent open interest. Prove every source
   part is in the manifest and no part is removed before complete publication.
2. `test_compaction_retry_reopens_to_identical_output` runs in two fresh
   processes, reopens the same parts at every checkpoint below and requires
   identical chain/open-interest record hashes, all three member bytes and
   pointer bytes. Changed inputs cannot reuse the prior set or its proof.
3. `test_compaction_interruption_preserves_parts_and_previous_output` injects a
   stop at every checkpoint below. Each case retains every part and the prior
   verified set's bytes; readers see the prior or complete new set only.
4. `test_compaction_recovers_or_rejects_stale_temporary_file` covers reopen with
   every checkpoint below with complete, partial, missing, corrupt and
   conflicting members, stale siblings and mismatched source/proof identities.
   Publish only a fully verified set or retain the prior set and block recovery.
5. `test_compaction_disk_full_never_deletes_or_replaces_verified_data` injects
   `ENOSPC` at every checkpoint below, including flushes and pointer publication.
   No case may remove parts, alter prior set bytes, expose a mixed set or report
   success. Check reopening both with and without a prior valid set.
6. `test_storage_reserve_refuses_write_before_crossing_limit` checks the larger
   of the fixed and percentage reserve, compaction working-space estimate and
   exact-boundary behavior. Cover each of `C/O/P/A/E/T` separately, unknown
   bounds, output expansion beyond `2.25 * S`, and each output exceeding its
   bound during writing; no omitted open-interest or proof bytes may admit work.
7. `test_retention_dry_run_respects_age_hold_and_partial_date` checks every
   record class, 7/30/750-day boundaries, legal holds, missing proof, partial
   dates and path escape refusal. It performs no real deletion.
8. `test_compaction_stays_inside_memory_batch_and_time_budgets` uses a bounded
   synthetic multi-part date, records process peak memory and elapsed time, and
   proves the batch, peak and wall-time limits. A forced limit breach must stop
   without changing verified data.

For each of cases 2–5, parameterize these checkpoints separately: bounded
reading; chain temporary write/flush/rename; after chain publication into the
unpublished set but before open interest; open-interest temporary write/flush/
rename; after open interest but before proof; proof temporary write/flush/
rename; after all members but before pointer replacement; set-directory flush;
pointer temporary write/flush/replace; and pointer-parent directory flush.
Exercise each member boundary with and without a prior set. A complete chain
beside old or absent open interest must never count as success. Publish the
collected case ids, reader-visible set ids and retained source/prior-set hashes.

The M0.2B focused protected selection is the eight cases above plus the existing
`tests/test_full_chain_collector.py`. The broader acceptance selection is the
controller-derived set for `scripts/full_chain_collector.py`, its configuration
and all storage callers. Cases 2–5 require fresh-process repetition and artifact
comparison because they cover deterministic recording, reopen and recovery.
Acceptance requires zero failures, errors or skips, clean isolation and cleanup,
and published source/compact manifests and limit measurements. Synthetic proof
establishes only the offline contract. A later measured saved-data run is still
required before M0.2 capacity can close.

## 7. M0.2B implementation boundary

M0.2B may add the off-by-default bounded compactor, proof manifest, admission
check and dry-run retention planner with the tests above. It may not activate
cleanup, remove or offload owner data, contact a provider, edit private ledgers,
change a trading rule, or claim production capacity. Activation and any real
deletion require separate measured proof and review.

## 8. Historical protected proof — 2026-09-13 Pacific

The controller tested the earlier version 1 documents with source hash
`61ab0121dd42b682e2412cc444b8ebe4e3b303a0a062dd19ad06b4de1a03583b`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/verified-manifest.json`;
its SHA-256 is
`eb54068e2e3dc21c7be936120013e5e700fe761d26db39820749b563c0453162`.
The controller evidence is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/controller-evidence.json`;
its SHA-256 is
`d688e77feabea30fdf83a6dbdd36c3d2fdb913fb435c5bd92f0e6b130d78349c`.

The focused phase selected `tests/trade_alerts_contracts` because
`builder named directly affected checks`. It ran once, passed 2994 tests, and
took 556.222 controller wall seconds. Pytest reported
`2994 passed in 552.22s (0:09:12)` and JUnit recorded 552.095 seconds. Its
artifact directory is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/published-artifacts-932cc0351036`;
the publication record SHA-256 is
`a2b84da630eeb74575c26f20c765f9cb3ca381569969d67514aedf411c45dc49`.

The acceptance phase selected `tests/trade_alerts_contracts` because
`unknown dependency impact; safe broad fallback`. It ran once, passed 2994
tests, and took 546.696 controller wall seconds. Pytest reported
`2994 passed in 542.71s (0:09:02)` and JUnit recorded 542.592 seconds. Its
artifact directory is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/published-artifacts-426b00afa107`;
the publication record SHA-256 is
`b9bf723ec97a6c35c760e2cf2de3bbe04bb571da1a8165f9042f914ede073160`.

The separate repeatability phase used the 38 selectors in its `summary.json`
because `recording output requires fresh-process comparison`. It ran twice,
passed 62 tests in each run, and took 307.424 controller wall seconds. Run 1
reported `62 passed in 151.69s (0:02:31)` with JUnit time 151.689 seconds. Run 2
reported `62 passed in 151.83s (0:02:31)` with JUnit time 151.828 seconds. Its
artifact directory is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/published-artifacts-2bd46053e801`;
the publication record SHA-256 is
`1c12970ddcb95b75447276d4c77540c94ba812595cd8f3ef16fbc9b33df09d75`.
The controller marked the recording comparison stable.

Every published run has zero failures, errors and skips, protected isolation
and clean cleanup. Review rejected this as sufficient contract acceptance:
the selection omitted `tests/test_full_chain_collector.py`. It does not
implement compaction or cleanup, measure saved-data capacity, qualify a market
source, or authorize live use. The complete milestone delta is
`trade_alerts_build_docs/DATA_REQUIREMENTS.md`,
`trade_alerts_build_docs/M0_2A_STORAGE_CONTRACT.md` and
`trade_alerts_build_docs/ROADMAP.md`. Records-only finalization changed only
these documents; the original tested manifest and controller proof remain the
tested-source evidence.

## 9. Attempt 2 repair and pending protected verification

The review found three connected omissions: the existing collector caller was
absent from the protected selection, publication treated a multi-file result as
one destination, and the space formula omitted open interest and proof. Source
inspection confirms `compact_option_day` writes chain and open interest
separately; `test_daily_compaction_creates_chain_and_open_interest_files` is the
existing direct test. That review reported no actual failing test id; the later
collection failure is recorded in section 10. Earlier passing
counts cannot cover this omitted caller or the future M0.2B failure cases.

This repair changes the contract to complete-set publication, explicit space
bounds for every output and a per-member failure/retry matrix. It preserves
the prior proof, full milestone delta and attempt history. No collector or test
code changes are assigned to M0.2A; section 6 is the required M0.2B test plan,
not a claim those future cases exist or passed.

For M0.2A, the controller must first run `tests/test_full_chain_collector.py`.
A focused failure stops the broader stage. After a pass, the required broader
selection retains `tests/trade_alerts_contracts` and includes the collector
test plus any additional controller-derived dependencies; this request cannot
reduce required coverage. The controller supplies the new phase names, run
counts, selectors, selection reasons, test counts, separate timings, hashes
and artifacts. No new execution figures exist yet. Section 8 preserves the
earlier acceptance and separate repeatability evidence for their original
selections; neither is new repair proof.

Status is ready for protected verification and independent review. The supplied
Codex launcher limitation is `OSError: [Errno 22] Invalid argument` during its
temporary-directory ownership change under workspace-write. It was not retried,
and no application tests ran outside protection. M0.2B remains the proposed
shared next step after acceptance; M0.2 capacity and market-source gates stay
open. All switches stay off.

## 10. Owner-approved collector test setup recovery — 2026-09-13 Pacific

The subsequent focused stage failed before running the collector cases:
`E   ModuleNotFoundError: No module named 'scripts.full_chain_collector'`.
The failing collection path was `tests/test_full_chain_collector.py`, whose
line 14 imports that module. The original failure remains in
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/verification.log`;
the previous repair result remains in that run's
`attempt-history/build-3-build-result.json`. This was a test-environment setup
failure: the protected launcher did not expose the collector file. It was not
evidence that the storage contract or collector cases passed or failed.

The owner approved a separately reviewed launcher repair. Its installed status
and review are recorded in
`/root/trade-alerts-builder/repairs/codex-subscription/collector-launcher-proposal/proposal.json`
and the adjacent `independent-review.md`. The installed launcher conditionally
exposes the collector read-only when the exact collector test path is selected,
including an optional individual case selector. It also exposes sanitized
settings with `/tmp/test-full-chain-collector` as the output root. Live settings,
market data and credentials remain unavailable; outside connections and writes
remain blocked. This session inspected those installed files without changing
the launcher, fixture, collector, strategies or guards.

The different recovery approach uses that owner-approved test setup and retains
the missing collector selection. It does not omit the caller or retry the old
setup unchanged. Preserve repair count 2, all rejected attempts and section 8's
historical proof. This specific owner approval does not reset retry policy.

Protected execution remains pending. The controller must run the focused
selection `tests/test_full_chain_collector.py` and
`tests/trade_alerts_contracts`, as retained in the failed stage's supplied
selection. A focused failure stops the broader stage. After a pass, run the
controller-required broader selection, retaining both paths and any additional
derived dependencies. The controller stage will supply `tests.phase`,
`tests.runs`, `tests.test_count`, `tests.wall_seconds`,
`tests.selection_reason`, `tests.selectors`, `tests.focused`, separate pytest
and JUnit timings, artifacts and tested-source evidence. No fresh pass is
claimed; the omitted-collector proof remains historical.

The known local protected-launcher limitation remains
`OSError: [Errno 22] Invalid argument` during temporary-directory ownership
change under workspace-write. It was not retried, and no application tests ran
outside protection. M0.2A remains ready for controller verification and review;
M0.2B remains open as the proposed next shared prerequisite after acceptance,
subject to reviewer confirmation. The complete milestone delta remains the
three documents listed in section 8. No source, capacity or live gate closes.

## 11. Final protected proof — 2026-09-13 Pacific

The owner-approved test setup recovery passed. The focused phase selected
`tests/test_full_chain_collector.py` and `tests/trade_alerts_contracts` because
`builder named directly affected checks`. It ran once, passed 3001 tests, and
took 533.642 controller wall seconds. Pytest reported
`3001 passed in 529.90s (0:08:49)` and JUnit recorded 529.783 seconds. Its
artifact directory is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/published-artifacts-8d7835840919`;
the publication record SHA-256 is
`b51dd3a7cf1c3e87eea06864ed15dd3d3117163d6064106fd2ee3fdcc171c8d8`.

The acceptance phase selected `tests/trade_alerts_contracts` and
`tests/test_full_chain_collector.py` because
`unknown dependency impact; safe broad fallback`. It ran once, passed 3001
tests, and took 543.965 controller wall seconds. Pytest reported
`3001 passed in 539.83s (0:08:59)` and JUnit recorded 539.702 seconds. Its
artifact directory is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/published-artifacts-f727965d2a6d`;
the publication record SHA-256 is
`e0a4ac16cfe146f7ecda2f328c000f61497fc5b7d8f96d41baa6c5e8aecc17a5`.

The separate repeatability phase used the 38 selectors in its `summary.json`
because `recording output requires fresh-process comparison`. It ran twice,
passed 62 tests in each run, and took 314.067 controller wall seconds. Run 1
reported `62 passed in 159.22s (0:02:39)` with JUnit time 159.225 seconds. Run 2
reported `62 passed in 150.88s (0:02:30)` with JUnit time 150.876 seconds. Its
artifact directory is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/published-artifacts-fed75f9d444a`;
the publication record SHA-256 is
`8d4155abb9438d4fa15b22cb896db069912062e5d480e2006b0a955005c49850`.
The controller marked the recording comparison stable.

Every final run has zero failures, errors and skips, protected isolation and
clean cleanup. The tested source hash is
`247e486f66424d3abff891d5f07e2ff65c6af2af842c4bc22740ed6fc0bc78d8`.
The complete tested-source manifest is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/verified-manifest.json`;
its SHA-256 is
`ebd2575af89c699f291590271f635db27e969fee45b97daa151e10f760b06e1f`.
The controller evidence is
`/root/trade-alerts-builder/runs/20260913-213504-809524-build/controller-evidence.json`;
its SHA-256 is
`f492b99d440191fdda7cfca1495cf26b144d1c73bb5d9722154ba3603a054399`.

This proof accepts the M0.2A version 2 offline contract. The complete milestone
delta is `scripts/testing/run_trade_alerts_contracts.py`,
`tests/trade_alerts_contracts/fixtures/full_chain_collector.yaml`,
`trade_alerts_build_docs/DATA_REQUIREMENTS.md`,
`trade_alerts_build_docs/M0_2A_STORAGE_CONTRACT.md` and
`trade_alerts_build_docs/ROADMAP.md`. These final prose edits are records only;
the tested manifest and controller proof above remain the source evidence.
M0.2B still owns implementation and measured capacity proof. No cleanup was
activated, no owner data was removed or moved, and no source, capacity or live
gate closes.
