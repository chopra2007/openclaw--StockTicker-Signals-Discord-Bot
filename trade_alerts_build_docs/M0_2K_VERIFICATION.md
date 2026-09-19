# M0.2K — D-104 gap register and selected-mode budget/continuity proof

Status: records and measurement only. Uses only data already held (the D-102
core17 EQUS.MINI one-year files, the 13-ETF inventories and existing collector
dates). No new provider request, spending, Strategy 5-8 work, replay result,
alert, order or activation.

## 1. D-104 gap register

The complete field-by-field register is `M0_2K_GAP_REGISTER.json`. Ten gaps are
recorded (original availability, corrections/finality, point-in-time index
membership, historical borrow, complete real option chain, option intrabar tick
path, the free DoltHub reference source's coverage/timestamp limits, pre-2023-03-28
OPRA pricing, catalyst history, and two dataset-specific coverage holes: collector
date 2026-09-11 and the 13-ETF provider-degraded/partial-window dates). Each gap
row names its dependent rules, which stay switched off and labelled untested; none
is approximated, proxied or filled. Two fields obtained without a gap are also
listed (the D-102 one-year core17 history and the dated bounded Schwab read-only
check), with their own stated limits.

## 2. Selected mode

M9.3's requirement text says to "record data modes and use the recording sink by
default." The selected mode for this pilot is the **offline recording-sink shadow
mode**: it reads the already-held D-102 core17 one-year history and the accepted
first-four playbooks plus M4.7A options/portfolio, and writes through the
recording sink (`consensus_engine/alert_delivery.py` requires the recording sink
for replay/shadow). It makes no live provider call. The measurements below are
for this mode, not for a live-delivery mode.

## 3. Provider budget

Databento is the only paid provider used by the selected mode's data. Live
ledger `/root/trade-alerts-builder/databento-spend-ledger.json`:

- Authority: USD 60.00, a fresh total (D-101).
- Spent: USD 22.4702 across three jobs (trades USD 20.6736, bbo-1m USD 0.676,
  ohlcv-1m USD 1.1206), all `downloaded: true`, all under
  `/home/openclaw/.openclaw/research-data/databento/core17-1y_2025-09_to_2026-09/`.
- Remaining: USD 37.53.
- The selected recording-sink shadow mode itself issues no live Databento call;
  this budget only bounds any later targeted, signal-selected option purchase
  (D-103 band, 0-7 DTE), which is a separate, not-yet-made request.

## 4. Queue budget

`consensus_engine/request_queue.py` (`M02D_REQUEST_QUEUE_V1`, frozen): account
ceiling 110 requests per 60 seconds, maximum queue length 256, `enabled=False` by
default. The selected mode makes no live request, so this ceiling is not
exercised; it is recorded here as the frozen limit that would apply if any
provider call were enabled later.

## 5. Storage and disk budget

`config/full_chain_collector.yaml` storage policy (also
`consensus_engine/full_chain_storage.py` `StoragePolicy` defaults):
`fixed_reserve_bytes=12,000,000,000`, `reserve_fraction=0.15`,
`peak_memory_bytes=1,500,000,000`, `batch_bytes=256,000,000`,
`wall_seconds=900`, output bounds chain=1,000,000,000 / open_interest=200,000,000
/ proof=4,000,000 / publication=4,096 bytes.

Measured at 2026-09-16T02:27:05-07:00 Pacific
(`/root/trade-alerts-builder/archives/storage-manager/status.json`, cross-checked
with `df -B1 /` in this session): filesystem capacity 80,307,429,376 bytes, free
13,149,548,544 bytes (13,149,544,448 in the storage-manager status snapshot taken
seconds earlier). `reserve_bytes = max(12,000,000,000, ceil(0.15 * capacity)) =
12,046,114,407`. Free exceeds this reserve by about 1.10 GB, so the disk-full
condition that blocked the storage-manager admission check on 2026-09-14
(`M0_2C_CAPACITY_ASSESSMENT.json`, free 9,200,222,208 bytes, below the 12 GB
fixed reserve) is cured for plain reads and for the protected test run in
section 7. The bounded compactor's own admission check
(`check_admission` in `full_chain_storage.py`) additionally reserves working
space for its output bounds; using the M0.2C source inventory (option parts
147,903,541 bytes, existing chain 89,846,238 bytes, existing open-interest
80,271 bytes) the working-space requirement is 2,497,934,701 bytes, leaving
10,651,613,843 bytes free after it — still below the 12,046,114,407 reserve. The
bounded compactor therefore remains **not admitted** on current free space; this
is a distinct, narrower budget gap from the disk-full failure verified fixed
below, and is recorded here rather than claimed closed.

Memory: the system has 7.6 GiB total, about 4.9 GiB available at measurement
time, against the 1.5 GB `peak_memory_bytes` ceiling enforced by
`full_chain_storage._peak_bytes()` for any compaction run. No compaction ran in
this milestone, so no peak was measured; the ceiling and current headroom are
recorded as the applicable budget.

## 6. Input continuity

`/home/openclaw/.openclaw/research-data/databento/core17-1y_2025-09_to_2026-09/manifest.json`
records 13 monthly files per schema (trades, bbo-1m, ohlcv-1m) for the D-102
17-name universe: `20250915-20250930`, then one calendar-month file per month
through `20260801-20260831`, then `20260901-20260914`. The file list is
contiguous with no missing month over the full 2025-09-15 to 2026-09-15 window
for all three schemas. This establishes date-range continuity of the held
history; it does not establish per-record original availability, correction or
point-in-time membership (see the gap register).

## 7. Verification run of the storage repair

The 2026-09-15 M9.3 blocked assessment recorded a controller acceptance failure
caused by a full disk: `sqlite3.OperationalError: database or disk is full` in
`test_orb5_replay.py::test_each_supplied_scenario_replays_its_own_recorded_states`,
followed by `OSError: could not create numbered dir ... in /tmp/pytest` in
`test_rs_trend_eligibility.py`. This milestone reran exactly those two test files
through the protected launcher, one fresh process:

```
scripts/testing/run_trade_alerts_contracts.py \
  tests/trade_alerts_contracts/test_orb5_replay.py \
  tests/trade_alerts_contracts/test_rs_trend_eligibility.py --runs 1
```

Result: `225 passed in 41.55s`, exit code 0, artifacts at
`/tmp/trade-alerts-m04-ve9o341n/run-1`. No disk-full error and no temporary-folder
creation error occurred. The M0.4 isolation summary printed by the launcher
recorded its normal sandbox denial counts (`network: 2`, `credential_read: 1`,
`child_process: 1`, `database_path: 1`, `outside_write: 1`) with
`unexpected_denials: {}`, matching the isolation contract used by every other
protected run in this project. This is one verification run confirming the
specific storage repair cures the specific failure named above; it is not a
repeatability or broad-acceptance run and makes no new pass claim beyond these
225 tests.

## 8. What this does and does not close

Closes: the D-104 gap register for the fields named above; the selected mode's
provider, queue, storage/disk and memory budget measurements; input date-range
continuity for the held D-102 history; and the storage-repair verification run
that M9.3 named as missing.

Does not close: the bounded compactor's own admission (still not admitted on
current free space, section 5); any of the ten recorded gaps and their disabled
dependent rules; source qualification, historical option execution, calibration,
early strategy validation, profitability, or any live/shadow activation. All
switches remain off.
