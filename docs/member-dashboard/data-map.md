# Dashboard market storage boundary

Reviewed October 5, 2026, Pacific time, against the isolated checkout. This is
source-code mapping and synthetic verification; it is not a live coverage probe
or permission to activate a source. No bot database was initialized or changed.

`MarketReader` accepts a host-configured absolute path, a fixed `SourceName`, a
typed checkpoint and a 1–100 row limit. SQL tables and column lists come from
the internal enum mapping. Values use bound parameters. Connections use URI
`mode=ro`, `query_only=ON`, a 100 ms connection timeout and a 250 ms query deadline
with a SQLite progress handler. They close after each batch. Active WAL readers
never use `immutable=1` or change journal settings. A real temporary WAL test
holds an uncommitted writer while the reader sees the last committed version.
Missing tables, columns, files or interrupted queries yield an unavailable
batch and leave the checkpoint unchanged. Callers retain saved permitted
publications with stale/source-unavailable labels instead of inventing fresh data.

| Enum / table | Selected columns | Identity and timestamp semantics | Publication result |
| --- | --- | --- | --- |
| `ANALYST` / `analyst_post_views` | `id, source_post_key, source_url, ticker, detected_at, raw_text, raw_text_sha256, display_direction, reason_text, reason_start, reason_end, reason_kind, decision_code, parser_version, image_evidence_json, created_at` | `(source_post_key,ticker)` card identity; latest `(created_at,id)` is authoritative before safety filtering. Detection and storage times do not prove post publication. | Exact validated quote or separate image provenance. Stored `long/short` becomes public `bullish/bearish`. No product or contributor grant is inferred. |
| `SIGNAL` / `signal_events` | `id, source_type, ticker, direction, quality_score, recorded_at, source_link, analyst_post_view_id` | Namespaced integer identity; recording time is telemetry/detection. | Research observation; signal existence is not delivery. Exact analyst row ID remains internal. |
| `ALERT` / `alert_history` | `id, ticker, confidence_score, catalyst_type, consensus_breakdown, technical_data, alerted_at, price_at_alert` | Namespaced integer identity; `alerted_at` is a pre-send write. JSON can mutate without a new ID/time. | Research-only; missing contributor/product manifests block member use. A zero/nonpositive price is unavailable. |
| `SNAPSHOT` / `decision_snapshots` | `id, ticker, decision, final_score, contradiction_index, sources_json, recorded_at, outcome_price_at_alert, alert_id` | Namespaced integer identity, exact legacy `alert_id`; recording time is computation/storage. | Research-only. No stored immutable rendered content or trade levels are reconstructed. |
| `OPTIONS` / `options_flow` | `id, ticker, side, strike, expiry, volume, open_interest, vol_oi_ratio, premium_usd, last_trade_ts, spot, contract_symbol, alerted, detected_at, flow_side, bid, ask` | Namespaced integer observation; detection is scan time; last trade is separate and may be unavailable. | Never publishable from this storage. `alerted=1` can follow failed/skipped sends; served Schwab/Yahoo fallback product is absent. |
| `TICKER` / `ticker_signals` | `id, ticker, source_type, sentiment, detected_at, expires_at` | Namespaced integer occurrence; detection time and operational expiry are not source/licensing timestamps. | `desktop_auth` and `desktop_local` are blocked. Generic source categories do not supply product/contributor rights. |
| `RESEARCH` / `research_sections` | `ticker, source, content, last_good_content, fetched_at, last_good_at, status` | Composite `(ticker,source)`, cyclic reconciliation. Latest fetch is attempt time; failed latest attempts use original last-good time with stale status. | Stored analyst/SEC/news prose is withheld because contributors/model rights are unknown. Underlying observation time stays null. |
| `SOURCE_HEALTH` / `source_health` | `source_id, last_heartbeat, error_rate, freshness_seconds, updated_at` | Cyclic source key; heartbeat is provider-call success, not quote age. | Operational input only; no market record/publication. A later admin mapper must use safe fixed labels. |
| `ROUTINE_HEALTH` / `routine_health` | `routine_id, last_cycle_started, last_success_at, errors_in_cycle, paused_until` | Cyclic routine key; no dependable modification time. `last_success_at` can reflect routine-start heartbeat. | Operational input only; it cannot claim completed work. |

`raw_text`, quote positions/hash, parser classifications and optional image JSON
are private validation inputs. The adapter does not select analyst identifiers,
unrestricted summaries, operational paths, credentials, Discord identifiers,
routine metadata, outcome-after-alert fields, weighting/feature vectors or
arbitrary model output. Safe projections contain bounded escaped text, finite
selected metrics, null missing values and an allowlisted HTTP(S) source link.
Query strings, redirect wrappers, credentials, nonstandard ports, private/IP
hosts, backslashes and file/data/javascript links are unavailable. Links are
never fetched. Image direction remains separate from exact source quotes.

The SHA-256 version covers normalized projected content, authoritative analyst
row/parser/classification/image evidence, safe link, times and source/product
classification. Score/technical changes generate versions even on old IDs.
Missing actual product classification remains explicit, rather than becoming a
claim that current configuration describes a historical response. The permission
policy version is an additional cache/delivery identity component.

ID sources reserve bounded lanes for new IDs, a recent 30-second overlap and a
rotating older-ID reconciliation cursor. Analyst authority is chosen before
these lanes return a row, so an invalid latest parser cannot revive an obsolete
row. Composite and operational sources use bounded cyclic key scans. Task 7
owns the five-second scheduler, saved-key synchronization and feed endpoints;
Task 3 supplies batch/checkpoint/blocked-key hooks. Invalid authoritative keys
need withdrawal/re-evaluation by that synchronizer. Ordinary pruning or absence
is not a retraction; saved authorized evidence survives with a stale label.

Exact delivery proof uses `measurement_alert_events_v1.legacy_alert_id` to one
consistent decision, that decision's exact candidate with matching ticker, and
delivery events reduced by `(delivery_id,attempt_id)` and `(created_at,event_id)`.
Each chain has a 100-event cap; incomplete/conflicting/overlarge chains fail
closed. Confirmed events need a positive decimal external message ID and valid
confirmation time. Dry-run sentinels are rejected. A failed separate follow-up
does not erase a confirmed instant attempt. Any linked correction whose
semantics have not been explicitly implemented makes proof unverified. No fuzzy
ticker/time join to `alert_messages` is allowed. Proof returns only confirmation
time, never operational message IDs, and explicitly does not verify rendered
content. It is a separate diagnostic hook; mutable row payloads remain
research-only and do not carry fabricated published-at, entry, target or
invalidation values.

`publishable` requires complete typed `ContentLineage`; adapter observations
start without it. A later host-verified contributor manifest must attach every
source/product/content/policy version, required feature/dependencies and earliest
retention deadline. `Publisher.save/load` recheck current permissions inside the
web transaction. Saved content contains bounded payload, evidence and permitted
attribution; grant/account references remain exclusively in the private policy
registry. Save is idempotent, content versions are immutable, and explicit
trusted `retract` emits a content-free removal event. No feed/API endpoints,
source ingestion or real provider calls were added in Task 3.
