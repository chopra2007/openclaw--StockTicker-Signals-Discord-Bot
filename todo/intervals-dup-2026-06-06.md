# Duplicate `intervals:` block in config/consensus.yaml — silently drops 4 keys

**Status:** OPEN — needs a one-line user decision (merge vs delete). Do NOT fix without sign-off (a merge is behavior-changing).
**Created:** 2026-06-06 (Wave 8 / NF-1)
**Pre-existing:** yes — this is in HEAD, not introduced by the audit run.

## What's wrong (plain)

`config/consensus.yaml` has the same top-level heading **`intervals:` written twice** — once at line 108 and again at line 733. When a YAML file repeats a top-level heading, the reader keeps only the **last** one and silently throws the first away. So the FIRST `intervals:` block (lines 109-112) is dead — the engine never sees those values and falls back to whatever the code uses by default.

### The 4 keys that are silently dropped (the dead first block, lines 109-112)
- `social_scan: 300`
- `reddit_trend: 14400`
- `cross_reference_timeout: 120`
- `state_prune: 900`

### The block that actually wins (lines 733+) keeps only
- `form4_cluster_loop`, `feature_volume_monitor`, `options_flow_loop`, `options_flow_cooldown`

**Verified read-only** (`python3 -c "import yaml; d=yaml.safe_load(open('config/consensus.yaml')); print(sorted(d['intervals']))"`): the loaded `intervals` dict contains ONLY the 4 second-block keys; `intervals.social_scan` is `False`/absent. Confirmed the footgun is live.

## CORRECTION to the original NF-1 write-up

The first draft of NF-1 listed **`sec_background_watchers_enabled: true`** as the "most consequential" dropped key. **That is wrong.** That key is NOT under `intervals:` — it lives under the **`scanners:`** block (line 118), which is **not** duplicated. Verified: `scanners.sec_background_watchers_enabled` resolves to `True` correctly in the loaded config. SEC background watchers are NOT affected by this duplicate. The real impact is limited to the 4 cadence/timeout keys listed above.

## Why not silently fixed
Merging the two blocks would RESTORE the 4 dead values, which changes scan cadences and prune/timeout behavior = a behavior change, which is held for the user per the go-live boundary.

## Decision for the user (pick one)
1. **Merge** the two `intervals:` blocks into one (all 8 keys) → restores the author's intended `social_scan` / `reddit_trend` / `cross_reference_timeout` / `state_prune` values. Behavior-changing (cadences shift).
2. **Delete** the dead first block (lines 109-112) → behavior-preserving, just removes the footgun. Pick this if the current code defaults are what you actually want.

(Either way, after the edit re-run the dup-key gate: no top-level YAML key should appear twice.)
