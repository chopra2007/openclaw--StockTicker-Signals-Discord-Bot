# M0.2C saved-data capacity assessment

Current status: **blocked by local capacity; no activation is safe**.

## Result

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

## Reopening condition

After the existing storage manager finishes eligible recovery, re-read current
local free space. Create an isolated copy only if the full admission calculation
passes with the unchanged reserve and all existing and temporary bytes counted.
Then run the bounded compactor on that copy and record source/compact record
equality, actual output bytes, peak memory and wall time. A separate review must
approve any later cleanup activation.

The independent shared next candidate is M0.2D: one offline request queue and
recorded-load AT-13 proof. It does not require starting this blocked compaction
or implementing Strategies 5-8. Independent review must confirm that order.
