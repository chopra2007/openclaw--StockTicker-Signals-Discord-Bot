# M0.2C saved-data capacity assessment

Current status: **measured capacity pass; protected verification and independent
review remain required before any activation**.

## Reopened measurement — 2026-09-24 Pacific

The source-copy admission check was rerun after verified storage recovery. The
full admission calculation passed, including the 12,046,114,407-byte local
reserve and 5,704,004,096 bytes for the isolated source copy, scratch work, and
bounded final files.

The isolated copy contained the same 390 source files and 3,721,860 option
rows. The bounded compactor published a complete day with 9,976 open-interest
rows. Its final chain used 199,211,477 bytes, open interest used 77,145 bytes,
the proof used 56,219 bytes, and the publication pointer used 227 bytes. Peak
memory was 428,077,056 bytes. Scratch space peaked at 2,647,519,232 bytes. The
compaction took 888.3310328269145 seconds and the complete measurement took 891.6052063190145
seconds, below the authorized 1,800-second limit.

The frozen writer and reopen check verified source-to-compact record equality.
All original source identities were unchanged. The run ended with
21,185,400,832 local bytes free. The published set ID is
`bc18a69e0c847e0dff79ce17631dcfc0a697c071b72fd030ead1748655b97061`.

The supervisor result is
`/root/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-final4/RESULT.json`
with SHA-256
`414b4d030a3924e51e4871e8a2a49f2b3fb1598c0f32e837a8c7752864acab0a`.
The matching source-identity record is `SOURCE_IDENTITIES.json` in the same
directory with SHA-256
`14b1b23bc037485004fcfdf86dbae5629d3a34ec5eef242a98d89e13d491b0ab`.

This pass opens M0.2CA, the lettered repair of the historically blocked M0.2C
step, for protected verification and independent review. It does not rewrite
the old blocked result, qualify the market source, enable cleanup, enable a live
switch, or prove a trading result.

The preregistration in that supervisor directory records an owner-authorized
1,800-second limit for this measurement and a separate scratch bound. The
current complete delta also includes batched compaction and scratch-space
accounting changes. The reserve is preserved; describing all implementation
and limits as unchanged would be incorrect. M0.2CA must reconcile those changes
with the governing storage contract and complete protected checks and review.

## Historical blocked result — 2026-09-14 Pacific

The approved candidate is the saved 2026-08-31 option-parts date. The bounded
inventory records 390 part files using 147,903,541 logical bytes and 148,725,760
allocated bytes. Its existing compact chain uses 89,846,238 logical bytes. These
are file-presence and size facts only. They do not qualify the market source.

The storage manager recorded 9,200,222,208 local free bytes at 01:39 Pacific on
2026-09-14. `M0_2A_STORAGE_CONTRACT` requires a local reserve of at least
12,000,000,000 bytes. Free space was already below that reserve before making an
isolated copy or adding any working files. The frozen admission rule therefore
rejects the run.

No copy was made and the compactor was not started. No owner file was changed,
moved or removed. Source/compact record equality, output bytes, peak memory and
wall time remain unmeasured. A blocked admission is not performance or parity
proof.

Cleanup remains off. Every live switch remains off. The 175,000,000,000-byte
Google Drive build allowance and its 165,000,000,000-byte operating limit do not
replace the local reserve needed while the compactor works.

## Evidence

- Saved-file inventory: `/root/trade-alerts-builder/repairs/codex-subscription/m02c-file-size-inventory.json`
- Local storage status: `/root/trade-alerts-builder/archives/storage-manager/status.json`
- Server transfer proof: `/root/trade-alerts-builder/archives/storage-manager/rclone-live-verification.json`
- Frozen limits and admission rule: `M0_2A_STORAGE_CONTRACT.md`
- Mechanical record: `M0_2C_CAPACITY_ASSESSMENT.json`

## Historical reopening condition

After the existing storage manager finishes eligible recovery, re-read current
local free space. Create an isolated copy only if the full admission calculation
passes with the unchanged reserve and all existing and temporary bytes counted.
Then run the bounded compactor on that copy and record source/compact record
equality, actual output bytes, peak memory and wall time. A separate review must
approve any later cleanup activation.

The dated measurement above supplies the previously missing capacity evidence.
M0.2CA owns its protected verification and independent review. The old M0.2D
handoff is historical; M0.2D was subsequently accepted and is not a new next
task. No later milestone is selected by this capacity record.
