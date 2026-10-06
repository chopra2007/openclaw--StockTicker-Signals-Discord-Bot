# VPS disk offload to Google Drive (2026-10-05)

Old files were moved to Google Drive to free disk space. Each was copied, every file checksum-verified on Drive, and only then deleted locally.
None of them is used by the live bot, a service or a timer (checked by grep; all untouched for 8+ days).

- Remote: the Drive build folder (id `1PCzbp7Or4AmZf5T9Uj6T12rhSJHm24NH`), reachable as `builddrive:` (`/root/.config/rclone/trade-alerts.conf`) or as `gdrive:` + `--drive-root-folder-id` (openclaw user config; login renewed 2026-10-05).
- Destination: `builddrive:vps-offload-2026-10-05/`
- Exact list (local path → Drive path, file count, bytes): see the manifest table below.

| What | Was at | Drive folder |
|---|---|---|
| 6 old database backups (May–June) | `workspace/consensus.db.bak.*`, `consensus.db.pre-regime-bak` | `old-db-backups/` |
| Old research outputs | `workspace/.omc/research/{trading-edge-discovery,professional-day-trader-methods,immediate-profitable-share-feature}` | `omc-research/` |
| TODO #111 DoltHub data | `/home/openclaw/.openclaw/research-data/todo-111` | `research-data/todo-111` |
| Trade-alert builder history (only folders no state file points to) | `/root/trade-alerts-builder/{research-runs,repairs/codex-subscription}/*` | `trade-alerts-builder/` |
| Archived system logs (journal trimmed to 1 GB) | `/var/log/journal/<id>/*@*.journal` | `journal-archive/` |

Kept locally: the live `consensus.db`, the newest backup `consensus.db.bak.pre-ticker-fix-2026-10-04`, `research-data/todo-109`
(the #109 collector still writes there), and the builder runs that state files reference.

**Restore** (e.g. before re-running a `scripts/research/todo_111_*` script, which reads the Dolt data):
`rclone --config /root/.config/rclone/trade-alerts.conf copy builddrive:vps-offload-2026-10-05/research-data/todo-111 /home/openclaw/.openclaw/research-data/todo-111`
then `chown -R openclaw:openclaw` the restored path.

`scripts/purge_fake_youtube_runs.sh` (a one-off from June) names `consensus.db.bak.pre-purge`; restore that file from `old-db-backups/` before running it.

## Manifest

Free space went from 5.0 GB to 29 GB (61% used). 45 items moved, 0 failed. The npm download cache was also cleared (it rebuilds itself).
The last runs used the user's own Google app (`gdrive:` with `--drive-root-folder-id 1PCzbp7Or4AmZf5T9Uj6T12rhSJHm24NH`, the same Drive folder as `builddrive:`). The shared rclone app was rate-limited.

| Local path | Drive path | Files | Bytes |
|---|---|---|---|
| `/home/openclaw/.openclaw/research-data/todo-111` | `gdrive:vps-offload-2026-10-05/research-data/todo-111` | 962 | 5905983231 |
| `/home/openclaw/.openclaw/workspace/consensus.db.bak.pre-backfill-manual` | `builddrive:vps-offload-2026-10-05/old-db-backups/consensus.db.bak.pre-backfill-manual` | 1 | 405245952 |
| `/home/openclaw/.openclaw/workspace/consensus.db.bak.pre-phantom-cleanup-2026-05-28` | `builddrive:vps-offload-2026-10-05/old-db-backups/consensus.db.bak.pre-phantom-cleanup-2026-05-28` | 1 | 333180928 |
| `/home/openclaw/.openclaw/workspace/consensus.db.bak.pre-purge` | `builddrive:vps-offload-2026-10-05/old-db-backups/consensus.db.bak.pre-purge` | 1 | 412930048 |
| `/home/openclaw/.openclaw/workspace/consensus.db.bak.pre-wolf-rebuild-20260608T161849Z` | `builddrive:vps-offload-2026-10-05/old-db-backups/consensus.db.bak.pre-wolf-rebuild-20260608T161849Z` | 1 | 405245952 |
| `/home/openclaw/.openclaw/workspace/consensus.db.bak.pre-wolf-rebuild-20260608T162351Z` | `builddrive:vps-offload-2026-10-05/old-db-backups/consensus.db.bak.pre-wolf-rebuild-20260608T162351Z` | 1 | 405245952 |
| `/home/openclaw/.openclaw/workspace/consensus.db.pre-regime-bak` | `builddrive:vps-offload-2026-10-05/old-db-backups/consensus.db.pre-regime-bak` | 1 | 480198656 |
| `/home/openclaw/.openclaw/workspace/.omc/research/immediate-profitable-share-feature` | `gdrive:vps-offload-2026-10-05/omc-research/immediate-profitable-share-feature` | 42 | 541625685 |
| `/home/openclaw/.openclaw/workspace/.omc/research/professional-day-trader-methods` | `gdrive:vps-offload-2026-10-05/omc-research/professional-day-trader-methods` | 50 | 2240482072 |
| `/home/openclaw/.openclaw/workspace/.omc/research/trading-edge-discovery` | `gdrive:vps-offload-2026-10-05/omc-research/trading-edge-discovery` | 78 | 2552207225 |
| `journal archived files` | `gdrive:vps-offload-2026-10-05/journal-archive` |  |  |
| `/root/trade-alerts-builder/repairs/codex-subscription/isolated-capacity-measurement` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/isolated-capacity-measurement` | 11 | 22918 |
| `/root/trade-alerts-builder/repairs/codex-subscription/isolated-capacity-measurement-v2` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/isolated-capacity-measurement-v2` | 14 | 38682 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-batching-proof-20260924` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-batching-proof-20260924` | 3 | 460677 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-compact-row-proof-20260924` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-compact-row-proof-20260924` | 5 | 917102 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-fast-row-proof-20260924` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-fast-row-proof-20260924` | 5 | 917102 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-final-storage-repair-proof-20260924` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-final-storage-repair-proof-20260924` | 5 | 917102 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-30min` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-30min` | 4 | 61061 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-batched` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-batched` | 4 | 61063 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-batched-retry` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-batched-retry` | 4 | 61074 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-compact-row` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-compact-row` | 3 | 60591 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-final2` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-final2` | 4 | 61108 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-final3` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-final3` | 4 | 61093 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-final4` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-final4` | 399 | 2994879014 |
| `/root/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-final` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/m02c-measured-capacity-20260924-final` | 395 | 560898781 |
| `/root/trade-alerts-builder/repairs/codex-subscription/ordinary-trace` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/ordinary-trace` | 3 | 10341 |
| `/root/trade-alerts-builder/repairs/codex-subscription/strict-trace-anchored` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/strict-trace-anchored` | 4 | 14116 |
| `/root/trade-alerts-builder/repairs/codex-subscription/strict-trace` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/strict-trace` | 2 | 6550 |
| `/root/trade-alerts-builder/repairs/codex-subscription/strict-trace-no-boundary` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/strict-trace-no-boundary` | 4 | 12054 |
| `/root/trade-alerts-builder/repairs/codex-subscription/strict-trace-no-pattern` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/repairs/codex-subscription/strict-trace-no-pattern` | 4 | 14280 |
| `/root/trade-alerts-builder/research-runs/20260926-110525-TE1_FULL_REGISTER_VALIDATE-a1` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260926-110525-TE1_FULL_REGISTER_VALIDATE-a1` | 2 | 6718 |
| `/root/trade-alerts-builder/research-runs/20260926-110526-TE1_FULL_TESTS-a1` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260926-110526-TE1_FULL_TESTS-a1` | 2 | 6700 |
| `/root/trade-alerts-builder/research-runs/20260926-110531-TE1_FULL_RUN-a1` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260926-110531-TE1_FULL_RUN-a1` | 2 | 11001 |
| `/root/trade-alerts-builder/research-runs/20260926-110823-TE1_FULL_RUN-a2` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260926-110823-TE1_FULL_RUN-a2` | 2 | 11001 |
| `/root/trade-alerts-builder/research-runs/20260926-152454-TE1_FULL_RUN-a3` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260926-152454-TE1_FULL_RUN-a3` | 1 | 4321 |
| `/root/trade-alerts-builder/research-runs/20260926-153404-TE1_FULL_RUN-a4` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260926-153404-TE1_FULL_RUN-a4` | 6 | 69748489 |
| `/root/trade-alerts-builder/research-runs/20260927-002027-TE1_FULL_TESTS-a2` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260927-002027-TE1_FULL_TESTS-a2` | 2 | 6700 |
| `/root/trade-alerts-builder/research-runs/20260927-002031-TE1_FULL_RUN-a5` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260927-002031-TE1_FULL_RUN-a5` | 8 | 1311331014 |
| `/root/trade-alerts-builder/research-runs/20260927-005549-TE1_FULL_TESTS-a3` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260927-005549-TE1_FULL_TESTS-a3` | 2 | 6700 |
| `/root/trade-alerts-builder/research-runs/20260927-005554-TE1_FULL_RUN-a6` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260927-005554-TE1_FULL_RUN-a6` | 8 | 1311330750 |
| `/root/trade-alerts-builder/research-runs/20260927-010217-TE1_FULL_RUN-a7` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260927-010217-TE1_FULL_RUN-a7` | 8 | 25197821 |
| `/root/trade-alerts-builder/research-runs/20260927-030755-TE2_TESTS-a1` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260927-030755-TE2_TESTS-a1` | 2 | 6925 |
| `/root/trade-alerts-builder/research-runs/20260927-030807-TE2_RUN-a1` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260927-030807-TE2_RUN-a1` | 6 | 71798 |
| `/root/trade-alerts-builder/research-runs/20260927-032922-TE2_VERIFY_TESTS-a1` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260927-032922-TE2_VERIFY_TESTS-a1` | 2 | 27798 |
| `/root/trade-alerts-builder/research-runs/20260927-032925-TE2_VERIFY_TESTS-a2` | `gdrive:vps-offload-2026-10-05/trade-alerts-builder/research-runs/20260927-032925-TE2_VERIFY_TESTS-a2` | 2 | 27798 |
