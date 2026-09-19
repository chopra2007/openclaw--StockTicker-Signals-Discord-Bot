# PREBUILD_REVIEW.md

## 1. Status, authority and boundaries

Review date: 2026-09-05 Pacific. Repository inspected: `/home/openclaw/.openclaw/workspace`, reached through `/root/.openclaw/workspace`. Starting saved revision: `69044b270be08b5628606c0cd8a6717724904589`.

**Historical review and permitted documentation corrections: complete. Full strategy build readiness: not yet.** At this review's completion, the next milestone was **M0.3 — Freeze deterministic definitions and evidence contracts**, starting with shared features and `CRVOL_ORB5` while retaining all eight playbooks. Current progress is governed by ROADMAP §31; M0.4, M1.1–M1.3 and M2.1 have since completed. Independent foundation work may proceed only for closed contracts; unresolved strategy branches and data modes remain blocked.

This is a review record, not a tenth canonical specification. PROJECT_INDEX retains authority routing; MASTER_SPEC and domain specifications retain their scopes. No reviewer proposal has been promoted to an approved product decision. All eight playbooks and required capabilities remain tracked. No numerical trading thresholds, trading windows, feature scope, purchase approvals or strategy promotions were changed. Clock labels were converted to Pacific while preserving the same market instants.

Only the original nine design documents and this review record were changed. No application, dependency, credential, deployment configuration or live database changes; no saved code changes, pushes, restarts, Discord messages or trades. Public documentation lookups and selected isolated offline tests were used. Provider access and live delivery were not tested.

Starting Git status contained only untracked `data/` and `trade_alerts_build_docs/`. These pre-existing files were preserved. All nine originals were backed up byte for byte, with SHA-256 hashes and original ownership/modes, in `/root/prebuild-review-backups/20260905-171858-PT`. The private backup also records starting Git status and revision. It is not a new specification or public artifact.

## 2. Evidence method and reconciliation

Three independent bounded reviewers examined architecture/reuse, strategy/data correctness, and reliability/testing. The coordinator read PROJECT_INDEX first, then all eight supporting documents, applicable repository rules, relevant source/test files, and official provider documentation. The coordinator owns all shared-document edits and checked the high-impact source paths and original collector proof summaries directly.

Evidence labels:

- **CODE**: inspected implementation and actual call path; this proves what the source does, not that it currently works live.
- **TEST SOURCE**: relevant existing tests inspected; no fresh execution claim unless listed in §8.
- **OFFLINE PASS**: tests freshly executed in this review, using local fixtures/fakes.
- **ARTIFACT**: a dated local proof report directly read; its checks and limitations are stated.
- **OFFICIAL**: provider documentation retrieved during this review; not account-specific entitlement.
- **INFERENCE / PROPOSAL / UNKNOWN**: explicitly distinguished from confirmed facts and approval.

Reviewers agreed that reuse is substantial and faithful strategy implementations are new work. Their broad stop recommendations were narrowed to the affected contracts and modes: a missing catalyst feed blocks faithful #7, not all foundation work. A claim that the repository lacks a useful calendar was corrected by `consensus_engine/utils/time_context.py:21–59`, which already handles holidays and early closes. The weaker research/main time checks must not become the new canonical clock. Existing date-specific data blockers were also corrected where source now provides partial borrow fields and forward option collection.

Source anchors below refer to the inspected revision, not necessarily current line positions after later build sessions. Repository paths are relative to the repository root unless an absolute local artifact path is shown. Test names are evidence references, not assertions that every listed test ran.

## 3. Existing implementation and reuse inventory

| Ref | Evidence, symbols and source anchors | Reuse boundary and evidence level |
|---|---|---|
| E-01 | `consensus_engine/__main__.py`; `consensus_engine/main.py:1198–1377` (`run_live`), `consensus_engine/main.py:1305–1339` (`run_live` task list), `consensus_engine/main.py:1504–1521` (`run_all` host); README runtime/launch instructions | Existing Python asynchronous application lifecycle. Extend one supervised task/controller inside this host; no separate replacement bot or scheduler. CODE. |
| E-02 | `consensus_engine/config.py:53–100` (`get`, `reload`); `config/consensus.yaml`; `consensus_engine/utils/feature_flags.py:13–44`; `requirements.txt`, `requirements-dev.txt`, `pytest.ini` | Existing YAML/environment settings, flags and dependency conventions. Add validated versioned strategy settings and secret-free hashes; do not duplicate loaders. CODE; feature-flag OFFLINE PASS. |
| E-03 | `consensus_engine/utils/time_context.py:21–59` (`session_dates`, `session_bounds`, `nyse_open_now`) | Reuse holiday/early-close calendar and add strategy windows/Pacific display. Do not copy simplified `consensus_engine/main.py:114–127` or `consensus_engine/research/sessions.py:1–52` checks. CODE. |
| E-04 | `consensus_engine/scanners/schwab_client.py:80–119` (`_RateBucket`), `:199–280` authentication/request flow, `:477–531` (`_map_quote`, `get_quote`, `get_quotes`), `:576–629` (`get_price_history`) | Reuse requests/authentication and normalize canonical provenance/freshness. Existing quote mapper has separate quote/trade times, halt and borrow fields; legacy last-price semantics favor regular-session price. Numeric provider limits and live permissions are UNKNOWN. CODE; `tests/test_schwab_client.py` TEST SOURCE. |
| E-05 | `consensus_engine/utils/prices.py:28–64` (`fetch_history`) | Schwab-first when enabled, then yfinance fallback with the same frame shape. Extend to expose source, adjustment/session basis and fallback quality to the new consumer. The old return shape alone hides fidelity changes. CODE. |
| E-06 | `consensus_engine/scanners/schwab_client.py:312–376` (`_chain_map_to_df`), `:407–456` (`get_option_chain`) | Existing exact contract, expiry, bid/ask/sizes, quote time, Greeks, OI, IV, multiplier, deliverable and delayed-chain metadata. Extend recommendation policy; do not create another chain client. CODE; `tests/test_schwab_client.py` TEST SOURCE. |
| E-07 | `consensus_engine/analysis/indicators.py:75–120` (`vwap`, `atr`); `consensus_engine/analysis/technical.py:107–144` daily RVOL/VWAP call site | Reuse transparent arithmetic only after exact input/window contract tests. The existing daily filters are not session VWAP or same-time intraday RVOL. CODE; indicator/technical test sources. |
| E-08 | `consensus_engine/analysis/peer_comparison.py:145–270`; `consensus_engine/analysis/market_breadth.py:1–105` | Existing daily peer-relative comparisons and descriptive equal-weight/index breadth context. Extend primitives if suitable; neither implements RS15 or the four-component intraday BreadthScore. CODE. |
| E-09 | `consensus_engine/scanners/options.py:65–161`; `consensus_engine/scanners/expected_move.py:287–344`; `consensus_engine/models.py:383–402`; `consensus_engine/alerts/all_command/levels.py:1369–1555` | Reuse unusual-flow/expected-move context and presentation helpers. These are not OptionScore or the eight structural stop/target rules. Preserve existing `!all`/`!em`/options behavior. CODE. |
| E-10 | `consensus_engine/db.py:40–88` transaction wrapper, `:2217–2275` initialization/migrations; `consensus_engine/measurement.py:227–322` (`write_initial_trade_bundle`, `write_alert_delivery_bundle`) | Existing SQLite, atomic related facts, delivery/outcome separation. Extend versioned models and migration framework for strategy states/provenance; no parallel generic database pipeline. CODE; database OFFLINE PASS. |
| E-11 | `consensus_engine/trade_tracking.py:122–265` contract/quote validation, `:411–479` option return calculation, `:563–755` rule/plan/contract records, `:907–1168` atomic bundles/corrections; `consensus_engine/trade_collector.py:122–147` fee settings | Reuse immutable exact-contract tracking and named cost models. Existing primary quote-side measurement differs from other research midpoint models; keep attribution separate. CODE; `tests/test_batch2_trade_tracking.py`, `tests/integration/test_batch2_quote_collection.py` TEST SOURCE. |
| E-12 | `consensus_engine/alerts/discord.py:65–201` (`_safe_send_kwargs`, `_safe_send`), `:1133–1172` (`send_message`); `consensus_engine/main.py:1920–2027` save/send/confirm path; `consensus_engine/alerts/commands.py` command routing | Reuse current destination/credentials/payload safety and connection. Extend structured candidate rendering, delivery-intent recovery and failure classification. Current retry behavior is limited. CODE; sender OFFLINE PASS. |
| E-13 | `consensus_engine/db.py:1763–1775` outbox state; `consensus_engine/alerts/wolf_news.py:793–797` send then mark posted | Useful existing durable-intent pattern, but the send/confirmation crash gap remains. Adapt it to the current delivery system with an explicit uncertain result; do not claim exactly one remote delivery. CODE; `tests/test_alfred_outbox.py` OFFLINE PASS. |
| E-14 | `consensus_engine/health.py:309–535` feed health; `consensus_engine/main.py:2453–2484` and `consensus_engine/db.py:5729–5764` source health; `consensus_engine/utils/circuit_breaker.py:57` failure guard; corresponding health/operational-alert tests | Reuse source health/backoff/error reporting; extend per-strategy freshness, queues, latency, state/delivery faults and versioned research health. CODE; 60 focused OFFLINE PASS. |
| E-15 | `scripts/full_chain_collector.py:158–202`, `:244–270`, `:338–434`, `:461–514`; `config/full_chain_collector.yaml` | Reuse bounded stock/options capture and local files. Existing universe/cadence/chain bounds are not the new system's complete feed requirements. CODE + ARTIFACT; `tests/test_full_chain_collector.py` TEST SOURCE. |
| E-16 | `scripts/research/intraday_dislocation_common.py:20–30`; `scripts/research/intraday_dislocation_engine.py:29–80` | Existing fixed-universe historical source references and conservative chronological price-path research are useful engineering fixtures. Adapt a shared live/replay controller; no existing replay of the eight specified playbooks was established. CODE. |
| E-17 | `consensus_engine/scanners/news.py`, `earnings_calendar.py`, `nasdaq_calendar.py`, `trading_halts.py`; relevant scanner tests | Existing context/news/calendar/halt readers. Audit timestamps, revisions and coverage; their presence does not establish faithful low-latency catalyst classification or receive history. CODE / TEST SOURCE. |
| E-18 | `Makefile:20–22`, `scripts/pre-push:72–92`, `scripts/flag_flip_gate.py:63–73`, `tests/conftest.py:8–15,168–180` | Reuse exact failing-test-ID comparison and temporary-database fixture. Extend new-flag gating and explicit network/secret isolation. The review did not execute the deployment/push scripts. CODE; selected gate OFFLINE PASS. |
| E-19 | `infra/README.md:1–105`, `infra/systemd/consensus-engine.service`, `infra/systemd/openclaw-gateway.service`, `docker-compose.yaml`; installed unit definitions read only | Existing deployment conventions and system user. Installed/tracked unit drift is an open compatibility finding, not permission to overwrite either. CODE. |
| E-20 | `consensus_engine/alerts/all_command/levels.py:836` (`extract_volume_profile_levels`) | Existing candle-volume profile/value/HVN/LVN calculation. Reuse suitable pieces after contract tests; its binning and descriptive output do not implement #8 prior-session/stability/refill rules. CODE. |
| E-21 | `consensus_engine/analysis/wolf_scope.py:77,150` (`stock_sector_etf`) | Reuse current sector mapping; not point-in-time membership history. CODE. |
| E-22 | `consensus_engine/utils/http.py:29`, `consensus_engine/utils/rate_limiter.py:14`, `consensus_engine/utils/circuit_breaker.py:57`; `consensus_engine/utils/obs_log.py:10` | Reuse pooled HTTP, pacing and persisted failure guard. Diagnostic log drops write errors, so it cannot replace the authoritative database ledger. CODE; selected reliability OFFLINE PASS. |

### Proposed integration shape

Use one new supervised controller task within the existing engine. Give it the existing calendar, normalized provider adapters, validated configuration snapshot, shared calculation primitives, and existing database/delivery adapters. The controller's chronological event/state logic is also called by offline replay with injected time and a recording sink. Strategy-specific state and research records are additive. This is a feature-preserving engineering proposal; final file/class names remain M0.4 work. It approves neither a new process nor a replacement framework.

## 4. Requirements-to-implementation map

Map status means **REUSE** existing behavior is suitable within the stated boundary; **EXTEND** existing code needs compatible additions; **NEW** no matching implementation was established; **BLOCKED** a required definition/data gate prevents the faithful mode. No status implies profitability or live readiness. Supporting evidence is expanded in §3. Acceptance test IDs are owned by TESTING_AND_VALIDATION §48.

### All eight playbooks

| Requirement owner | Status and implementation evidence | Required changes, dependencies and integration | Acceptance / milestone |
|---|---|---|---|
| PLAYBOOKS §3 `CRVOL_ORB5` | NEW; reuse E-03–E-07/E-10–E-12. No named strategy in application/tests. Current minute collection cannot prove 10-second acceptance. | Define OR/RVOL/sampling, A/B/C entry and swing selection; new state machine; labeled tape proxy; common risk/score/options/delivery. Faithful sub-minute history remains data-dependent. | Frozen 5-bar fixture, exact RVOL boundary, acceptance coverage/staleness, long/short and resistance veto; AT-02–AT-08; M0.3, M6.1–M6.4. |
| PLAYBOOKS §4 `HOD_COMP_RS` | NEW; E-07/E-08/E-21 provide partial arithmetic/current sector context, not RS15. | Define compression overlap/range and HOD freeze; RS window/benchmark/warm-up; acceptance, expiry and suppression. | Frozen HOD cannot change later; 0.60 compression boundary and exact RS threshold under approved windows; AT-03/AT-05/AT-07; M7.1–M7.5. |
| PLAYBOOKS §5 `OR_FAILURE_REV` | NEW; E-03/E-07/E-10 common dependencies. | Define meaningful excursion, 180-second timer, close/stronger-trigger precedence; new attempt/failure state and explicit #1 reversal link. | One-tick near miss, timer boundary, failure/rebreak and conservative outcome ordering; AT-05/AT-09; M8.1/M8.2/M8.5. |
| PLAYBOOKS §6 `FIRST_PULLBACK_VWAP` | NEW; existing VWAP research is a different strategy, not an implementation. E-07 primitives reusable after contract checks. | Freeze impulse/swing/pullback count, slope, volume denominator and first/second policy; new state machine. | Restart preserves first/second/third counts; 0.65/0.70 and 0.80 boundaries remain distinct; AT-05/AT-07; M8.3–M8.5. |
| PLAYBOOKS §7 `INDEX_OPEN_DRIVE_BREADTH` | NEW approved proxy; BLOCKED full breadth. E-08 descriptive breadth is not this score; E-15 lacks all 11 sectors. | Define sector/full/hybrid formulas, weights, coverage, membership and directional rules; drive denominator and 35–40% choice; extend reference capture. | Hand-computed score below/at 60, coverage failures, separate modes and SPY/QQQ dedup; AT-05/AT-09/AT-11; M10.1–M10.7. |
| PLAYBOOKS §8 `GAP_FADE_FAILED_OPEN` | NEW; E-04/E-15 partial premarket, L1 and current borrow. Catalyst mode remains explicit. | Define gap/extension windows, failed reclaim, stop precedence, UNKNOWN penalty and symmetric long case. | Gap threshold equality, extension/reclaim failures, gap-fill staleness, missing borrow and UNKNOWN news; AT-04/AT-05/AT-14; M11.1–M11.6. |
| PLAYBOOKS §9 `CAT_FIRST_CONSOL` | BLOCKED faithful catalyst; new price-state logic and E-17 context do not close it. | Verify source/receive/classification history; resolve C-class prior versus A/B-only trigger; define first consolidation. Retain explicit degraded shadow/disabled mode. | A/B/C/D cases, late/revised events, first versus later structure, no retrospective catalyst; AT-05/AT-12; M12.1–M12.6. |
| PLAYBOOKS §10 `VP_ACCEPT_LVN` | NEW approved BAR_APPROX_PROFILE strategy; EXTEND suitable E-20 approximation pieces; BLOCKED true profile. Existing descriptive levels are not this strategy. | Freeze allocation/bins/value area/smoothing/shelves/IoU/refill/stop rules; extend capture for true mode only when justified. | Hand profile with ties and zero-volume cases, stability boundary, labeled modes and matched no-LVN control; AT-05/AT-11/AT-14; M13.1–M13.7. |

Every row also requires PLAYBOOKS §12's config, eligibility, state, heads-up, actionable, invalidation, expiry, staleness, stops, targets, confidence, human checks, options hook, suppression, persistence, synthetic tests and replay. Missing exact definitions are tracked in PLAYBOOKS §13 and P-01/P-02; they are not quietly omitted from the build.

### All numbered system requirements

| MASTER_SPEC owner | Status / evidence | Required integration and dependencies | Acceptance / roadmap owner |
|---|---|---|---|
| FR-001 repository-first | REUSE; E-01–E-22 | Keep current host and adapt compatible modules. | Source map before new equivalent; AT-01; M0.1/M0.4. |
| FR-002 canonical models | EXTEND; E-04/E-06/E-10 | Add source/session/available-time and quality metadata without breaking old field meanings. | Round-trip exact contracts and missingness; AT-04; M1.3/M2.1. |
| FR-003 market clock | EXTEND; E-03 | Central calendar and strategy windows; Pacific display. | Holidays, early close, clock changes and OR finalization; AT-02; M1.1. |
| FR-004 shared features | EXTEND; E-07/E-08 | Freeze feature definitions before reusing arithmetic; add missing intraday features once. | Hand-worked units/window/warm-up and no look-ahead; AT-02/03/05; M0.3/M3.1–M3.6. |
| FR-005 state runtime | NEW; E-01/E-10 are host/storage only | Serialized per-instrument/session state, explicit transitions and stable references. | Continuous versus restart parity; AT-05/07; M4.1/M4.2/M5.5. |
| FR-006 heads-up | NEW; E-12 delivery reused | Per-playbook formation rule and expiry; immutable candidate. | Correct lead time, near misses and notification count; AT-05/09; M4.5/M4.6/M15.6 and each strategy. |
| FR-007 actionable | EXTEND; E-12 | Complete frozen trigger/risk/context/options/human-check renderer. | Exact payload and failure-path fixtures; AT-06/08; M4.6/M15.5. |
| FR-008 structural invalidation | NEW; E-09 legacy ladder is not equivalent | Shared risk object plus playbook-specific structural source. | Correct long/short invalidation and stop side; AT-05; M4.3 and each strategy. |
| FR-009 structural targets | NEW; E-07 primitives only | Point-in-time obstacle priority and target policy. | No arbitrary target invented beyond obstacle; AT-05; M4.3 and each strategy. |
| FR-010 minimum R:R | EXTEND; E-09 arithmetic patterns only | Enforce approved structural reward after valid positive risk. | Boundary, zero-risk and wrong-side rejection; AT-05; M4.3. |
| FR-011 quality score | NEW for playbooks; E-09 existing score is distinct | Defined factor scales and versioned score; no probability claim. | Exact factors and score bounds; AT-05/14; M0.3/M4.4/M16.4. |
| FR-012 score transparency | EXTEND; E-10 | Persist all components, weights, missing-factor rules and feature version. | Stored score reproducible without current config; AT-05/14; M4.4/M5.1. |
| FR-013 options separation | EXTEND; E-06/E-09/E-11 | Options adapter after underlying validity; shared budget and bounded enrichment. | Option failure leaves underlying facts unchanged; AT-08; M4.7/M14.1. |
| FR-014 poor options outcome | EXTEND; E-11 rejection reasons | Poor/unavailable status and reason in record/rendering. | Required stock-valid/options-poor result; AT-08; M4.7/M14.4. |
| FR-015 cross-strategy dedup | NEW; E-13 pattern only | Stable thesis/structure and component links, deterministic precedence. | One outward idea with all component candidates retained; AT-09; M4.7/M15.1–M15.3. |
| FR-016 suppression | EXTEND; existing delivery/cooldown patterns E-12/E-13 | Per-playbook cooldown, expiry, structure counts and restart persistence. | Reconnect/restart cannot resend expired structure; AT-06/07/09; M4.7/M5.5/M15.4. |
| FR-017 immutable facts | EXTEND; E-10/E-11 | Add strategy geometry/provenance to immutable records, corrections separately. | Late news/options/config cannot rewrite initial facts; AT-06/14; M5.1. |
| FR-018 event store | EXTEND; E-10/E-11 | Atomic evaluation/transition/suppression/option/intent records; migrations. | Failed transaction sends nothing; retry has stable identity; AT-06; M5.1/M5.5. |
| FR-019 outcomes | EXTEND; E-11/E-16 | Exact horizons/exits, MFE/MAE/targets/stops and unresolved records. | Hand-worked long/short paths, ambiguity and costs; AT-14; M0.3/M5.2. |
| FR-020 replay | NEW controller integration; E-16 research helpers | Same chronological state logic with fake clock/sinks and input manifest. | Repeat and crash/resume equality; no network; AT-07/10; M5.3. |
| FR-021 point-in-time | EXTEND; E-10/E-16 partial patterns | Available-time data, frozen references, universe/corporate-action evidence. | Future/revised input cannot alter earlier alerts; AT-02/11/12/14; M2/M5.3/M17.5. |
| FR-022 reaction delay | EXTEND; E-11/E-16; BLOCKED unsupported resolution | Separate trigger/delivery/human origins; retain all five requested delay horizons. | No intrabar invented fill; unavailable horizons explicit; AT-14; M5.4/M16.2. |
| FR-023 walk-forward | NEW integration; E-16 research context | Locked chronological folds, purge overlap and record variants. | Test data never fits parameters; AT-14; M17.5. |
| FR-024 ablation | NEW playbook research | Versioned research-only filter switches; retain suppressed inputs. | Base/filter results use same eligible data; AT-14; M16.3. |
| FR-025 human decisions | NEW linked input/analysis; E-12 commands reused | ACCEPTED/REJECTED/NO_DECISION and time/reason separate from mechanical fact. | No decision or delivery failure excluded silently; AT-14; M9.4/M16.5. |
| FR-026 lifecycle | NEW for playbooks; E-02 flags reused | Separate lifecycle/data/evidence states and approved promotions. | Shadow/rejected/blocked cannot auto-activate; AT-01/13; M17.3/M17.4/M19. |
| FR-027 data quality | EXTEND; E-04/E-06/E-14 | Field-specific stale/missing/delayed/invalid coverage and safe suppression. | Fresh cache cannot mask old provider time; AT-03/04/11; M2/M18.1. |
| FR-028 observability | EXTEND; E-14 | Structured state/rejection/delivery/latency/queue metrics with bounded logs. | Inject faults and prove visible classified results; AT-06/13; M4.2/M18.1–M18.4. |
| FR-029 explicit fallback | EXTEND; E-05 currently obscures it | Capture source and mode on every fallback; segregate research. | Provider switch changes provenance, not silent success; AT-04/11; M2.1/M2.2. |
| FR-030 versioning | EXTEND; E-10/E-11 | Strategy/config/feature/dataset/execution hashes, secret-free snapshots. | Replay old records after new config; AT-07/14; M1.2/M5.1/M16.1. |
| FR-031 no auto-retuning | EXTEND; E-02; NEW monitoring guard | Research challengers isolated; explicit decision before production changes. | Proposed challenger cannot change active configuration; AT-01/13/14; M19.5/M19.6. |

### Additional required capability and non-functional coverage

These rows cover requirements beyond the numbered FR list. Optional enhancements remain optional as specified; this review does not remove them or make them mandatory.

| Capability owner | Status / evidence | Required work and acceptance | Milestone |
|---|---|---|---|
| CAP-01 MASTER §§5–6: equities/ETFs/options, long/short, human-only execution | EXTEND E-01/E-04/E-06 | Typed instrument/direction and manual-only boundary; no order method reachable from controller/replay. AT-05/10. | M1.3/M4.1/M0.4 |
| CAP-02 DATA §§6/17/23: daily, premarket, session universe and warm-up | EXTEND E-04/E-05/E-15 | Universe by date, premarket coverage/levels/volume, split basis, gap anchor; no survivor-only population claims. AT-02/11/14. | M2.2/M3.1/M3.2/M17.3 |
| CAP-03 DATA §§7–10/19: L1, tape/depth/order-flow/auction enhancements | EXTEND L1 E-04; BLOCKED unverified optional feeds | Prove L1 freshness/continuity; retain optional high-resolution enhancement gates and approved tape proxy. No invented access. AT-03/04. | M0.2/M2.3/M16.3 |
| CAP-04 DATA §§12–16: market, sector, VIX, macro, earnings, halt context | EXTEND E-03/E-08/E-17 | Complete reference-symbol coverage, source availability, macro due/halt suppression and context expiry. AT-04/05/11/12. | M2.4/M10/M11/M12 |
| CAP-05 MASTER §15 / PLAYBOOKS options: 0–7 DTE, strategy-specific DTE/delta, 0DTE, OptionScore | EXTEND E-06/E-09/E-11; NEW score | Versioned score factors and deterministic contract/expiry/strike ties; exact quotes, sizes, OI as-of, IV/Greeks and deliverables. AT-08. | M0.3/M4.7/M14.1–M14.6 |
| CAP-06 DATA §§11/27: historical option execution | BLOCKED complete faithful history; E-15 partial forward data | Exact contract and dated bid/ask/fees; separate stock results and modeled sensitivity; retain faithful-mode gate. AT-14. | M14.6/M17.3 |
| CAP-07 PLAYBOOKS §§2/12: human checklist and decision capture | EXTEND E-12; NEW linked decision model | Human checks displayed from frozen facts; inputs cannot mutate alert or trigger order placement. AT-08/14. | M4.6/M9.4/M16.5 |
| CAP-08 MASTER §§10/18: confluence, conflict, alert burden and health | EXTEND E-12/E-14; NEW portfolio semantics | Deterministic primary/confluence, reversal and equal-score tie rules; count heads-up conversion/expiry and frequency. AT-09/13. | M4.7/M15/M16.7/M19 |
| CAP-09 TESTING §§18–23/32: risk metrics, sample, regime, uncertainty | EXTEND E-11/E-16; NEW reports | Expectancy/PF/drawdown/MFE/MAE/target timing with explicit denominators, independent days and observable regime labels. AT-14. | M5.2/M16.1/M16.6 |
| CAP-10 TESTING §§25–28/34: walk-forward, stability, matched profile experiment | NEW playbook studies | Locked split, neighboring parameters, recorded variant count; matched accepted-value no-LVN control; no same-sample filter invention. AT-14. | M13.6/M16.3/M17.5/M17.6 |
| CAP-11 TESTING §§29–31: confidence/factor/human analysis | NEW reports; E-10/E-11 storage reused | Separate score quality from calibrated probability; train-only calibration, reason/time records, observational human comparison. AT-14. | M16.4/M16.5 |
| CAP-12 MASTER §18 / CODING §39: continuous health/champion-challenger | EXTEND E-14; NEW research lifecycle | Version-specific baselines, GREEN/YELLOW/ORANGE/RED diagnoses, queue/review and isolated challengers; no automatic promotion. AT-13/14. | M17.4/M19.1–M19.7 |
| CAP-13 MASTER §12 / CODING §§21/25/30/47: ordering, restart, concurrency | EXTEND E-01/E-10/E-13 | Single state owner, deterministic event order, bounded queues and verified warm-up/recovery. AT-03/07/13. | M2.3/M5.5/M18.4 |
| CAP-14 CODING §§20/37/40–41: immutable storage, migrations and delivery | EXTEND E-10/E-11/E-13 | Atomic fact/intent, additive tested migration, uncertain-send handling, disk/lock/restore tests. AT-06/07/10/13. | M5.1/M5.5/M15.7/M18.4 |
| CAP-15 CODING §§19/22/44: alert safety, secrets and AI text | EXTEND E-12 | Existing sender, mention prevention, payload bounds, redacted exceptions; no AI rewriting mechanical facts or blocking them. AT-08/13. | M4.6/M15.5–M15.7/M18.5 |
| CAP-16 CODING §§23/25/31 / DATA §26: provider budget/backoff/latency | EXTEND E-04/E-14 | Account-wide request coordination across processes, priority/expiry, provider-directed retries and measured peak limits. AT-03/04/13. | M0.2/M2.3/M18.1–M18.3 |
| CAP-17 DATA §§23–25 / CODING §38: retention/reconstruction | EXTEND E-10/E-15 | Content-addressed dataset and feature versions, immutable input/decision chain, per-symbol coverage and retention/storage budget. AT-07/14. | M5.1/M17.3 |
| CAP-18 CODING §§6/29 / MASTER FR-001: Python/dependency compatibility | REUSE existing conventions E-01/E-02/E-19; EXTEND compatibility proof | Preserve declared minimum until explicit decision; check deployed/test interpreter and dependency support without silent framework/language change. AT-01/13. | M0.4/M18.6 |
| CAP-19 MASTER §12 / TESTING §40: existing bot behavior | EXTEND E-18 tests/gates | Exact failing-test-ID comparison; enabled/off paths; protect `!all`, `!em`, command/mention/source paths affected by shared changes. AT-01. | M0.4/every code milestone/M18.4 |
| CAP-20 CODING §40 / MASTER §6: research/shadow/production isolation | EXTEND E-02/E-10/E-12 | Non-network replay, fake clocks/providers, temp DB, secret denial; live shadow sink recorded. AT-10. | M0.4/M5.3/M9.3/M17 |
| CAP-21 MASTER §5 / CODING §§37/47: deployment, rollback and runbooks | EXTEND E-19 | Reconcile installed/tracked units, preserve user/paths, backup/restore test, kill switch and rollback before ACTIVE. AT-07/13. | M0.4/M17.4/M18.6/M19.7 |
| CAP-22 PROJECT_INDEX / SESSION_PROTOCOL: authority, drift, durable handoff | REUSE nine-doc authority; EXTEND review traceability | All IDs/FRs/milestones/links match, proposals remain unapproved, one-line next-session trigger and documentation-only safety. | M0.1/every session |

## 5. Material findings, remedies and resolution status

Severity describes the consequence if the design were implemented unchanged. A failure scenario is not a claim that the current bot suffered that failure. **DOC RESOLVED** means the contract was corrected in documentation; implementation proof remains future work.

### F-01 — HIGH: duplicate infrastructure and inappropriate reuse

**Evidence:** E-01–E-13 show an existing host, provider clients, SQLite transactions, Discord and measurement. Original MASTER §7 called paths unknown and ROADMAP presented a greenfield foundation. E-07/E-08/E-09 show daily indicators/descriptive scores that differ from required intraday formulas. **Failure:** a second scheduler/client or reused daily “VWAP” silently changes all playbooks. A legacy ATR target ladder fabricates a structural target. Affected FR-001/004/008/009/011/013.

**Remedy:** one existing host, additive adapters, shared primitives only after input/behavior contracts; keep legacy scoring and rendering stable. **Tradeoff:** adapters and compatibility fixtures take initial work but avoid duplicate live ownership. **Proof:** AT-01/05/08; M0.4. **DOC RESOLVED:** MASTER §§7/21, CODING §§51–54, capability map. Source implementation is unchanged.

### F-02 — HIGH: deterministic strategy rules are incomplete

**Evidence:** original PLAYBOOKS common acceptance counts undefined observations; #1 offers A/B/C entries; #2 has unspecified range overlap; #4 mixes first-only with second priority; #5 allows 35–40% without choosing; #7 prior permits class C but trigger only A/B; #8 refill threshold is TBD. ATR/RVOL/swing/score definitions and outcome horizons are open in decisions. **Failure:** two builders produce different alerts while both claim compliance. All eight playbooks are affected.

**Remedy:** PLAYBOOKS §13 names each missing definition and M0.3 closes it with exact versioned examples. Existing numerical priors remain governing rules. **Tradeoff:** affected logic waits for scoped decisions; unrelated foundation work can proceed. **Proof:** AT-05, independently reproducible boundary output. **OPEN DECISION:** P-01/P-02/P-03. This review chooses no new threshold, weighting or trading variant.

### F-03 — HIGH: shadow and activation precede their safety dependencies

**Evidence:** original M9 shadow preceded M14 options and M15 renderers/delivery/dedup; M17 promotion preceded M18 hardening and M19 rollback/health. **Failure:** shadow omits option failure/confluence or ACTIVE starts without recovery, kill switch or usable health. Affected FR-007/013–016/026/028.

**Remedy:** early M4.6 delivery isolation, M4.7 minimum options/dedup, M5.5 recovery; M17.4 requires minimum tested rollback/health/latency controls. Full later phases remain. **Tradeoff:** move prerequisites earlier without removing refinement scope. **Proof:** AT-06–AT-10/13 before corresponding gates. **DOC RESOLVED:** ROADMAP and MASTER §21.

### F-04 — HIGH: timestamps, bar completion and acceptance are not equivalent

**Evidence:** E-04 returns historical candles and second-resolution quote/trade times; E-15 minute snapshots cannot recover a 10-second acceptance window. Official Databento bars are start-stamped (S-03). **Failure:** the 06:34 bar is treated as complete at 06:34, OR fires early, reconnect bursts count as sustained acceptance, or historical sub-minute fills are invented. Affected FR-003/004/020–022/027.

**Remedy:** separate start/end/final/available time; source-specific revisions/sequence, exact sampling and coverage; unsupported sub-minute horizons remain blocked. **Tradeoff:** fewer evidentially usable historical events without removing required studies. **Proof:** AT-02/03/07/14. **DOC RESOLVED:** DATA §32, TESTING §§48–49, PLAYBOOKS §13. Exact formulas remain P-01/P-02.

### F-05 — HIGH: fallback and stale-field semantics can falsely pass checks

**Evidence:** E-05 silently changes provider; E-04's `c` favors regular-session price even outside that session; quote/trade time differ; a false delayed flag alone is not an age check. **Failure:** a fresh retrieval carries an old last price, gap/RVOL mix adjusted and raw sources, or current data labels conceal stale contracts. Affected FR-002/021/027/029 and option recommendations.

**Remedy:** additive canonical source/session/adjustment/freshness metadata, per-field ages, explicit fallback and stock/option skew gates. Preserve old fields for old callers. **Tradeoff:** more provenance and explicit suppression; no lower-fidelity substitute is approved. **Proof:** AT-04/11. **DOC RESOLVED:** DATA §§31–33 and CODING §51.

### F-06 — HIGH: existing collector proof is narrower than its names suggest

**Evidence:** dated artifacts in §6 show one passing report and three failed reports. E-15 checks 300 unique minutes across the whole file, `isDelayed=false` rather than quote age, and non-null underlying last rather than stock/option time equality. Config covers 20 trade names plus limited context, four nearest expirations and 15% strike band. **Failure:** millions of rows are mistaken for full fresh coverage, 0–7-day contracts or all-sector breadth. Affected FR-021/027 and CAP-02/05/06/17.

**Remedy:** reuse collection but qualify proof by per-symbol/session/contract age, coverage, spread, timestamp skew and required expiry availability. Investigate failed checks on source records before claiming bad feed versus an overly strict check. **Tradeoff:** stronger reports may reject previously passing days; existing samples remain useful for bounded engineering. **Proof:** AT-04/11/14; M0.2/M17.3. **DOC RESOLVED, DATA VALIDATION OPEN.**

### F-07 — HIGH: catalyst, breadth and profile modes lack faithful data or complete formulas

**Evidence:** DATA §§14–18 already block full modes; E-08 is daily descriptive breadth; E-15 lacks 11-sector coverage; E-17 provides no complete receive-time catalyst evidence. PLAYBOOKS #8 lacks a volume-allocation algorithm. **Failure:** price-only #7 is called catalyst validation, sector returns are called full constituent breadth, or bar volume is called true volume-at-price. Affected #5/#7/#8, FR-021/029.

**Remedy:** preserve approved proxy labels, close exact proxy definitions, retain explicit full-mode milestones M10.7/M13.7 and faithful M12. **Tradeoff:** free proxies have lower fidelity; paid sources need exact evidence and price before approval. **Proof:** AT-11/12 and separate mode reports. **BLOCKED / OPEN DECISION:** P-02/P-04; no fallback equivalence invented.

### F-08 — HIGH: structural alerts do not yet define executable profit

**Evidence:** TESTING §15 requires an explicit strategy horizon but provides none; exits/target fractions and reaction origins are unspecified. E-11 uses quote sides and $0.45 each transaction; other existing research uses midpoint. One-minute bars cannot establish sub-minute order. **Failure:** MFE becomes “profit,” post-delivery delay is measured from an earlier trigger, favorable midpoint fills or unobserved entry-bar paths inflate returns. Affected FR-019/022/023 and options evaluation.

**Remedy:** frozen named entry/exit/cost/censoring policy; mechanical, delivery, human and option results separate; exact-quote execution evidence and separately attributed primary/sensitivity models chosen under P-03; all unresolved outcomes visible. **Tradeoff:** stronger execution proof may require forward quotes and scoped decisions. **Proof:** AT-14, reconstruct exact cash flow with one-contract $0.90 round trip. **DOC RESOLVED evidence standard; P-03 outcome choices remain OPEN.**

### F-09 — HIGH: survivorship, selection and repeated research can overstate edge

**Evidence:** E-16 is a selected 60-symbol source reference; original TESTING permitted delistings “where possible” and sample labels could be mistaken for promotion strength. **Failure:** today's survivors and correlated same-day alerts are treated as a broad independent sample; filters are chosen on the same data reported as evidence. Affected FR-021/023/024/026 and CAP-09–11.

**Remedy:** dated universe/corporate-action manifest or restrict every claim to the observed sample; no broad-universe promotion on disclosure alone. Lock chronological folds, purge overlapping outcomes, preserve attempted variants, use dependence-aware uncertainty and train-only calibration. **Tradeoff:** narrower claims and possibly INSUFFICIENT_DATA. **Proof:** AT-11/14. **DOC RESOLVED:** TESTING §49; missing population data remains explicit.

### F-10 — HIGH: uncertain remote delivery and incomplete retries

**Evidence:** E-12 returns on generic HTTP failures/exceptions; existing tests expect one attempt for server/network failure. E-13 sends before marking posted, leaving a crash gap. S-01/S-02 define remote confirmation and rate handling. **Failure:** transient delivery disappears, or a crash causes a duplicate while the database claims a single event. Affected FR-007/016–019/028.

**Remedy:** atomic mechanical fact/intent, separate attempts/acknowledgments, expiry-aware classified retry, UNKNOWN on ambiguous send and evidence-based reconciliation. Adapt the existing sender/outbox pattern. **Tradeoff:** cannot promise exactly one remote message where the remote interface cannot prove it; explicit unknowns require reconciliation. **Proof:** AT-06/07 crash matrix. **DOC RESOLVED:** CODING §52 and early roadmap gates; implementation still EXTEND.

### F-11 — HIGH: offline and rollout tests can pass without exercising the real risk

**Evidence:** `tests/conftest.py:8–15` blocks one sender, `:168–180` isolates SQLite; `pytest.ini` excludes marked live/smoke tests but does not deny all outbound network. Autouse flags can disable paths. `flag_flip_gate.py:70` detects only existing false-to-true flags; its tests intentionally ignore a new true flag. **Failure:** an unmarked test reaches a service, or a new enabled strategy bypasses release proof. Affected FR-001/026 and CAP-19/20.

**Remedy:** explicit network/secret denial in new offline contracts, injected temporary storage and tests for both enabled/off paths and absent-to-enabled flags. Preserve exact failing-test-ID gate. **Tradeoff:** more explicit fixtures and release checks. **Proof:** AT-01/10/13, deliberate forbidden-call failure. **DOC RESOLVED:** CODING §§53–54, TESTING §§47/50, M0.4.

### F-12 — HIGH: resource contention and task exits can damage the existing bot

**Evidence:** E-04 limiter and refresh locks are within a process; E-15 has parallel option workers and another scheduled collector; E-01 adds tasks to the same event loop. Normal task completion is not necessarily a visible failure. **Failure:** new scanning consumes provider budget, blocks commands, misses freshness deadlines, or silently stops processing. Affected FR-001/027/028 and CAP-13/16.

**Remedy:** shared account/process request coordination, fixed ownership, bounded queues/timeouts, priorities and explicit task supervision/completion status. Measure candidate load and retention growth before shadow. **Tradeoff:** backpressure may suppress stale candidates rather than serve them late; required capacity failures stay blocked. **Proof:** AT-03/04/13. **DOC RESOLVED:** DATA §33/CODING §§51–53; measured budgets pending M0.2.

### F-13 — HIGH: deployment/rollback source and runtime support drift

**Evidence:** E-19 checked-in versus installed units differ in startup checks, failure reporting and resource protections. README declares Python 3.10+; offline test output reports Python 3.10.12 and a Google dependency support warning. **Failure:** copying the checked-in unit removes protections, or a later dependency update fails on the deployed interpreter. Affected FR-001 and CAP-18/21.

**Remedy:** compare definitions and declare the approved deployment source before deployment work; retain protections and verify supported interpreter/dependencies. Require minimum rollback rehearsal before ACTIVE. **Tradeoff:** compatibility work precedes deployment; no automatic interpreter or configuration change. **Proof:** AT-01/07/13, approved unit comparison and chosen-runtime suite. **DOC RESOLVED contract; implementation/deployment gap OPEN.**

### F-14 — MEDIUM: score/lifecycle/approval labels can be confused

**Evidence:** documents use CONFIRMED, PROVISIONAL, SHADOW, data modes and evidence stages in overlapping senses; initial ranking numbers and sample-count labels exist without performance proof. **Failure:** “confirmed code” becomes approved product change, a quality score becomes win probability, or monitoring automatically promotes a strategy. Affected FR-011/026/030/031.

**Remedy:** separate evidence/data/lifecycle/setup/delivery fields; explicit approver/date/scope/version record for changes and D-083 promotion. **Tradeoff:** extra structured metadata, clearer reports. **Proof:** AT-01/14 and document drift checks. **DOC RESOLVED:** MASTER §21, DECISIONS §28, TESTING §49. No new approval granted.

### F-15 — MEDIUM: borrow is wrongly declared wholly unavailable

**Evidence:** `schwab_client.py:477–510` maps shortable/hard-to-borrow/rate fields; E-15 stores them. Original DATA blocker table said omit borrow data. **Failure:** existing evidence is discarded or missing historical borrow is ignored when reporting executable short-stock profit. Affected #6 and FR-019/021.

**Remedy:** distinguish partial current mapped fields from validated historical borrow coverage; use the fields without claiming current entitlement, and separate directional stock evidence from executable shorts. **Tradeoff:** short-stock proof can remain blocked while stock-direction or puts research proceeds. **Proof:** AT-04/14; missing/false/unknown fixtures. **DOC RESOLVED:** DATA §29/31 and TESTING §49.

### F-16 — MEDIUM: renderer failure or AI enrichment can lose required facts

**Evidence:** E-12's malformed-embed fallback takes limited title/description text; original architecture does not define a complete deterministic fallback. **Failure:** a stock setup loses stop/targets when rich rendering fails, or waits for AI/options until stale. Affected FR-007/008/009/013/017.

**Remedy:** canonical complete candidate, deterministic compact fallback, optional linked enrichment, no AI changes to mechanical fields, no uncontrolled mentions. **Tradeoff:** more rendering fixtures; late enrichment is separately attributed. **Proof:** AT-08 plus forced payload rejection preserving mandatory fields. **DOC RESOLVED:** CODING §52, MASTER §21, M4.6.

## 6. Dated data evidence and remaining blockers

The following proof files were directly read under `/home/openclaw/.openclaw/research-data/todo-109/proof/`. Only aggregate report fields are reproduced; raw provider data remains local.

| File | Report result | Stock quote rows | Stock bar rows | Option rows | False checks |
|---|---|---:|---:|---:|---|
| `2026-08-31.json` | passed | 19,500 | 12,915 | 3,721,860 | none in that report |
| `2026-09-01.json` | failed | 19,500 | 13,212 | 3,715,136 | expiration count, option spreads, stock spreads |
| `2026-09-02.json` | failed | 19,500 | 13,046 | 3,734,932 | stock spreads |
| `2026-09-03.json` | failed | 19,500 | 13,060 | 3,552,586 | stock spreads |

These reports prove collection and its own check outcomes, not high-resolution strategy readiness. F-06 explains the proof-check limitations. Row-level failure causes and other dates were not established by this review. `scripts/research/intraday_dislocation_common.py:20–30` references selected-60-symbol Databento files; that source configuration is not a new audit of all file contents or full-market historical coverage.

| Blocker | Affected capability | Evidence / available route | Alternative, fidelity and cost | Reopening test / owner |
|---|---|---|---|---|
| B-01 deterministic definitions | All eight at their missing branches, common scoring/outcomes | PLAYBOOKS §13/P-01–P-03 | Finish exact definitions; no purchase required. Behavior-changing choices need scoped decision. | Independent hand-computed boundary outputs; M0.3. |
| B-02 provider fields, access, history depth, sub-minute cadence and shared capacity | Live actionable path and faithful delay/acceptance studies | Existing adapters/partial collection; public Schwab page lacked field detail; no broker probe permitted | Inspect existing official/account evidence and local files first, then an authorized bounded probe in a future task. Numeric limits UNKNOWN. No assumption that minute sampling equals ten-second data. | Per-field fresh/complete payload and per-symbol cadence/coverage/limit report; M0.2/M2.3. |
| B-03 catalyst original receive/classification history | Faithful #7; catalyst increments for #1/#6 | Existing context readers lack demonstrated complete low-latency evidence | Existing/free sources may supply context; #7 price-only is degraded shadow, not faithful. Paid low-latency source is an option only after named-field/fidelity review; price UNKNOWN. | Timestamped event/receive/revision/classification corpus and latency/completeness report; M12.1–M12.6. |
| B-04 full breadth and historical membership | Full #5 | Current context/collector lacks required full universe and all sector inputs | Approved 11-sector proxy with exact formula, coverage and separate results; point-in-time full feed may need access/purchase, price UNKNOWN. | Member-by-date coverage, hand-score fixture and full/proxy report; M10.1–M10.7. |
| B-05 true volume-at-price history | True-profile #8 | No complete project-ready true profile dataset established | Approved deterministic bar approximation after formula closure; tick/trade feed increases storage/cost, price UNKNOWN. | Reproducible true profile and matched comparison with labeled approximation; M13.1–M13.7. |
| B-06 executable historical option quotes and short borrow | Option returns and executable short-stock claims | E-11/E-15 provide current/forward pieces; faithful history not established | Continue bounded forward capture and underlying-only studies; paid exact history only for defined gaps, price UNKNOWN. Midpoint/model or unavailable borrow cannot substitute for executable proof. | Exact contract/times/sides/fees and point-in-time borrow where needed; M14.6/M17.3. |
| B-07 universe/corporate actions/delistings | Broad-universe and population performance claims | Selected historical universe; no complete population integrity proof here | Restrict every claim to frozen observed sample while tracking full universe needs. Broader master/action data may require purchase; price UNKNOWN. | Point-in-time manifest, action treatment, delisting outcomes and selection audit; M2.2/M17.5. |
| B-08 compatibility/release/recovery proof | Existing-bot protection and activation | F-10–F-13; tested helpers only | Extend existing infrastructure with offline contracts, then staged authorized proof. No replacement language/bot approved. | AT-01/06/07/10/13 and exact failing-test gate; M0.4/M5.5/M17.4/M18. |

Blocked required modes stay in the roadmap with completion criteria. No indefinite deferral or silent scope reduction is accepted. Historical price screening may proceed within disclosed limits; engineering readiness, historical edge and executable options profit remain separate verdicts.

## 7. Corrections applied and unapproved proposals

| Document changed | Targeted correction |
|---|---|
| PROJECT_INDEX | Repository identity, reference to this non-authoritative record, expanded drift/coverage checks and review-only boundary. |
| MASTER_SPEC | Existing Python host and reuse constraints; honest access evidence; complete strategy checklist rather than ID-only completion; persist-before-send and early release dependencies. |
| PLAYBOOKS | Pacific display conversion and precise missing-definition register for all eight. Original numeric trading rules retained. |
| DATA_REQUIREMENTS | Implementation capability register, partial borrow correction, timestamp/fallback/coverage/capacity contracts and official-source limits. |
| CODING_STANDARDS | Existing interfaces/runtime, additive compatibility, atomic facts/delivery recovery, isolation, ownership, regression/flag/deployment controls. |
| TESTING_AND_VALIDATION | Fourteen adversarial acceptance cases, offline guards, execution/statistical integrity and release prerequisites. |
| ROADMAP | M0.1 actual progress; M0.2 evidence still open; M0.3/M0.4 exact next work; early M4.6/M4.7/M5.5; explicit full modes; minimum ACTIVE controls. |
| SESSION_PROTOCOL | Review-only safety, relevant existing rules, offline/documentation checks, one-line kickoff and user no-commit precedence. |
| DECISIONS_AND_OPEN_QUESTIONS | Evidence versus approval, scoped repository resolutions and P-01–P-04 decision register. |

**No scope or fidelity change was approved.** P-01 asks for exact choices where trading behavior is ambiguous. P-02 closes already-approved proxy formulas without asserting equivalence to full data. P-03 freezes outcome/release choices before returns. P-04 tracks access/purchase/technology decisions only if later evidence establishes a need. No new language, replacement bot/framework, major rewrite or data purchase is selected. Full functionality remains tracked through phases and blockers.

## 8. Verification performed

The reliability reviewer inspected the selected tests and their isolation, then ran these three offline commands from the repository. The coordinator read the reported results and independently checked high-impact implementation/fixture evidence; the full application suite was intentionally not run for documentation-only work.

| Command | Fresh result | Scope |
|---|---|---|
| `python3 -m pytest -q tests/test_gateway_reconnect_backoff.py tests/test_gateway_replay.py tests/test_rate_limiter_jitter.py tests/test_feature_flags.py tests/test_db.py` | 40 passed | Existing recovery, limiter, flags and temporary database behavior. |
| `python3 -m pytest -q tests/test_flag_flip_gate.py tests/test_pass5_steps_6_7_8.py tests/test_alfred_outbox.py` | 24 passed | Existing gate behavior, Discord handling and outbox pattern, including current limitations. |
| `python3 -m pytest -q tests/test_source_health.py tests/test_feed_freshness.py tests/test_circuit_breaker.py tests/test_ops_alert.py` | 60 passed | Existing health/freshness/circuit/error reporting helpers. |

Total: **124 focused checks passed**. These results establish only the tested existing behaviors. They do not verify the eight playbooks, new contracts, current broker access, current Discord output, production readiness or profitability. Test output warned about future support for the installed Python 3.10.12 in a Google dependency; runtime compatibility remains M0.4 work, not an automatic upgrade.

Final document checks: see §10, completed after edits and independent review. No unrequested cleanup round or implementation follows this review.

## 9. Official external evidence

Only public documentation was accessed; no broker/Discord account was contacted. Retrieval date: 2026-09-05 Pacific.

- **S-01 — Discord delivery confirmation.** Webhook execution with `wait=true` returns the created message after confirmation; without it, an unsaved message can lack an error. This applies to webhook paths and is not a guarantee for every existing sender. [Official webhook reference](https://docs.discord.com/developers/resources/webhook).
- **S-02 — Discord retry limits.** Use response bucket/rate headers and retry timing; do not assume fixed route limits. This supports the adapter's rate handling, not guaranteed end-to-end delivery. [Official rate-limit reference](https://docs.discord.com/developers/topics/rate-limits).
- **S-03 — Databento bars.** Bar timestamps identify interval start, no-trade intervals can be absent, and daily aggregation need not match the required regular-session definition. Bar-construction conventions differ across sources. [Official OHLCV documentation](https://databento.com/docs/schemas-and-data-formats/ohlcv).
- **S-04 — Schwab access limits unresolved.** The official public page rendered navigation only. Field requirements, numeric request/subscription limits, entitlement, latency and historical depth could not be verified there. Existing repository mappings remain code evidence; no account-wide capability is inferred. [Official developer documentation](https://developer.schwab.com/products/trader-api--individual/details/documentation/Market%20Data).

## 10. Final consistency record

Completed after the independent final passes and their corrections:

- All nine canonical documents plus this single review record are present. Local Markdown links and 45 cited source paths / 46 line anchors passed existence/range checks.
- All eight playbooks, FR-001–FR-031, 22 additional capability rows, and 22 evidence rows are present without duplicate map IDs.
- All 190 original numeric-rule lines checked remain present after display conversion. The entire original PLAYBOOKS body is unchanged except correct Pacific clock conversion; the definition-gate section was appended.
- Final review conflicts were corrected: no unapproved primary fill model, first-four validation still gates later strategy implementation, OQ-001/OQ-002 statuses agree, minimum option ranking and capacity precede early shadow, and ACTIVE prerequisites have exact milestone owners.
- Code fences, local links, visible time labels, whitespace and secret-shaped text checks passed. Backup hashes and all nine original owner/group/mode settings match.
- Starting Git revision, index and status remain unchanged; no tracked application/configuration file changed. These documents remain untracked, as they were when supplied. No commit or push was made.
- The recoverable backup directory contains `documentation-changes.diff` and `final-checks.json`. Application tests remain the 124 focused existing-helper checks in §8; no claim is made that the new design is implemented or live-tested.

The review completed with M0.3 as its next milestone. Implementation and activation were not started by that review. Use ROADMAP §31 for subsequent progress.


## M0.3 follow-through — 2026-09-05 Pacific

The dated review above remains the prebuild evidence record. The subsequent docs-only continuation is recorded in [M0_3_DEFINITION_PACKET.md](./M0_3_DEFINITION_PACKET.md), DECISIONS §29 and ROADMAP §31. It supplies concrete shared-calculation/B-entry/outcome proposals and worked examples; it approves no new rules and does not complete M0.3, Strategy #1 or any data/implementation/profitability gate. The original capability map and all eight playbook obligations remain intact.


## Later owner approvals — 2026-09-05 Pacific

The historical review and drafting records above remain unchanged. The owner subsequently approved `M03A_ORB5_V1` as written research rules under D-090 and separately allowed up to $25 TOTAL Databento testing-credit usage under D-091. The six specified packet rows are incorporated by exact version into their canonical documents; open definitions/data gates remain open. The spending ledger begins at $0 used by this authorization. See DECISIONS §§30–31 and ROADMAP §31. No application implementation, provider request, Discord/broker call, order or deployment occurred in this approval-recording update.


## M2.1 later execution note — 2026-09-06 Pacific

[M2_1_VERIFICATION.md](./M2_1_VERIFICATION.md) records three pure Schwab-to-record
mappings and 41 new cases. The independent combined selection passed 420 tests
twice with identical record output and clean isolation reports. FR-002/FR-027
normalization evidence advances; only the mapping portion of AT-04 is covered.
Full freshness/skew, fallback, source coverage, streaming, storage and strategy
acceptance retain their existing owners. All 31 functional and 22 additional
capability rows remain tracked. No provider capability, product rule, spending or
live approval changed. ROADMAP §31 now selects M2.2.
