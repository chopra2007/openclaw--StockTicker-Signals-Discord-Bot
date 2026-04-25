# Discovery 2026-04-24 — Multi-Agent Status Board

Discovery & build plan for **new, high-impact** capabilities on the `consensus_engine` trade-idea bot.
Refactoring existing code is out of scope except where strictly required to integrate a new capability.

Branch: `claude/multi-agent-tmux-setup-zWYEQ`
Workdir: `/root/.openclaw/workspace`
Status: **complete** ✅

## Worker Status

| Window | Phase | Status | Deliverable |
|---|---|---|---|
| disc-p0-audit | 0 | ✅ done | [`00-system-map.md`](00-system-map.md) — 423 lines, 27-row capability matrix, 10 pipelines, 28 capability gaps, 30 constraints |
| disc-p1-sentiment | 1 | ✅ done | [`10-research-sentiment.md`](10-research-sentiment.md) — 12 candidates |
| disc-p1-flow | 1 | ✅ done | [`11-research-flow.md`](11-research-flow.md) — 13 candidates |
| disc-p1-insider | 1 | ✅ done | [`12-research-insider-filings.md`](12-research-insider-filings.md) — 13 candidates |
| disc-p1-technical | 1 | ✅ done | [`13-research-technical-quant.md`](13-research-technical-quant.md) — 12 candidates |
| disc-p1-catalysts | 1 | ✅ done | [`14-research-catalysts-macro.md`](14-research-catalysts-macro.md) — 12 candidates |
| disc-p2-synthesis | 2 | ✅ done | [`20-candidate-features.md`](20-candidate-features.md) — 14 survivors of 62, 4 infra clusters |
| disc-p3-redteam-A | 3 | ✅ done | [`30-critique-signal-quality.md`](30-critique-signal-quality.md) — 4K/8S/2KILL (regime lens) |
| disc-p3-redteam-B | 3 | ✅ done | [`31-critique-feasibility.md`](31-critique-feasibility.md) — 5K/7S/2KILL (data/rate-limit lens) |
| disc-p3-redteam-C | 3 | ✅ done | [`32-critique-adversarial.md`](32-critique-adversarial.md) — 3K/8S/3KILL (manipulation lens) |
| disc-p3-converge | 3 | ✅ done | [`33-final-feature-set.md`](33-final-feature-set.md) — 9 survive, 5 dropped, 9 cross-cutting safeguards |
| disc-p4-architect | 4 | ✅ done | [`40-implementation-plan.md`](40-implementation-plan.md) — 2,173 lines, ~2,910 LOC est. across 18 items |

**Spec scaffold:** [`docs/superpowers/specs/discovery-2026-04-24-features.md`](../../docs/superpowers/specs/discovery-2026-04-24-features.md) — canonical IDs, names, hardened descriptions, kill criteria, module paths.

## Final Feature Set (9 survivors)

| ID | Name | Domain | P2 score | Verdicts (A/B/C) |
|---|---|---|---|---|
| F1 | Cluster Form 4 Open-Market Buys | insider | 5.00 | KEEP/KEEP/KEEP |
| F2 | SEC S-4/425 Real-Time M&A | insider | 4.50 | STRENGTHEN/STRENGTHEN/STRENGTHEN |
| F3 | Pre-FOMC Drift Trade | catalyst/macro | 4.20 | STRENGTHEN/KEEP/STRENGTHEN |
| F4 | FRED Credit-Equity Divergence | technical/macro | 4.00 | STRENGTHEN/STRENGTHEN/STRENGTHEN |
| F5 | Volume-Confirmed N-Day Breakout w/ ATR | technical | 4.00 | STRENGTHEN/KEEP/STRENGTHEN |
| F6 | Earnings-Window Risk Gate | catalyst | 4.00 | KEEP/KEEP/STRENGTHEN |
| F8 | New 13D Activist + 13G→13D Conversion | insider | 4.00 | KEEP/STRENGTHEN/STRENGTHEN |
| F10 | Wikipedia Pageview Spike | sentiment | 3.70 | STRENGTHEN/KEEP/STRENGTHEN |
| F11 | Reg SHO Threshold List Entry | flow | 3.50 | STRENGTHEN/STRENGTHEN/STRENGTHEN |

## Dropped (5)
- **F7 FinBERT Headline Sentiment** — KILL by C (PR-wire spoof + adversarial-token attacks asymmetric vs defender cost)
- **F9 SEC EDGAR Full-Text Mention Velocity** — KILL by A and B (SEC-flood noise pattern from audit; 10 req/s ceiling exhausted by Cluster A peers)
- **F12 VIX Term-Structure Flip** — KILL by C (signal-redundancy with F3+F4; <10 events/yr, ~30 bps mean return)
- **F13 Influencer Cluster-Convergence** — KILL by A and C (mechanically inverts in meme-era regimes; sock-puppet sybil attack at $15/spoofed alert)
- **F14 PDUFA / AdCom Proximity Tag** — KILL by B (FDA Akamai bot-block, three serial upstream failure modes)

## Cross-Cutting Safeguards (9 — preconditions for all features)

| ID | Safeguard | Module |
|---|---|---|
| S1 | Shared SEC EDGAR semaphore | `consensus_engine/utils/rate_limiter.py` |
| S2 | Correlation-decay penalty | `consensus_engine/analysis/correlation_decay.py` (NEW) hooked at `cross_reference.py:333` |
| S3 | M3 per-analyst cooldown generalization | `consensus_engine/db.py:672` |
| S4 | Calendar resolver extension | `consensus_engine/analysis/catalyst_resolver.py` |
| S5 | Data freshness gate | `consensus_engine/utils/freshness_gate.py` (NEW) |
| S6 | HEAD-vs-GET health-check convention | `consensus_engine/utils/http.py` |
| S7 | Schema migration consolidation | `consensus_engine/db.py` |
| S8 | Shared yfinance rate-limit | `consensus_engine/utils/rate_limiter.py` |
| S9 | Macro-context consumption pattern | `consensus_engine/cross_reference.py` |

**Milestone-1 preconditions (must ship before any feature):** S1, S3, S7.

## Realistic Edge Statement (from converge)

- **Precision delta:** +3 to +5pp on actionable alerts vs current 2-source baseline (normal regimes); compresses to **+1 to +3pp** in sustained low-vol regimes.
- **Lead-time delta:** +10 to +20 min median (driven by F1/F6/F8).
- **Coverage delta:** +15 to +20% net new actionable alerts.
- **High-Impact Bar conditions met:** all 4 (precision, lead-time, coverage, instant-trigger blind-spot closure via F1/F2/F8/F11).
- **Hard preconditions:** the audit's M3 cooldown fix and the new correlation-decay penalty (S2) MUST ship as Milestone-0 before any feature flag flips on.

## High-Impact Bar (cutoff used in P2/P3)

A feature passes only if it plausibly delivers AT LEAST ONE of:
- +5pp precision on actionable alerts vs current 2-source baseline
- ≥30 min median lead-time vs current chain
- ≥20% net new alert coverage w/o inflating false-positive rate
- Reduces a known instant-trigger blind spot named in P0 gaps

## Ground Rules (per orchestration spec)

- Free + public data only. No paid APIs. No fragile scraping.
- No execution logic. No redundant capabilities.
- Alert philosophy fixed (from `CLAUDE.md`): quality > quantity, 2+ sources (with instant-trigger exceptions: large options flow, insider, unusual flow, confirmed technical breakout w/ levels, quant/factor), 8-K never standalone, Form 4 stored & +15 xref only, SEC → LLM thesis only.
- P1 workers honored anchoring prevention — none read `plans/AUDIT_RESEARCH_2026-04-24.md` or other `plans/*.md`.

## Notes & Adaptations from Spec

- **Working directory:** the spec named `/home/user/openclaw--StockTicker-Signals-Discord-Bot`; the actual repo lives at `/root/.openclaw/workspace`. Workers operated from the actual path.
- **Tmux topology:** the spec described tmux windows; Claude Code background subagents were used instead — same independence/isolation properties, with completion notifications handled by the harness.
- **Phase 4 split:** the original P4 architect agent stalled on a 1500-line single Write. P4 was respawned as two parallel architects (`disc-p4a-architect` for §1–5 mechanics, `disc-p4b-architect` for §6–10 operations) sharing a canonical module-path manifest, then merged into the canonical `40-implementation-plan.md`. Original split files preserved in git history under commits `f5a043b` and `c9b3e26`.

## Commit Log (branch `claude/multi-agent-tmux-setup-zWYEQ`)

- `f81186a` Consolidate Phase-4 split (40a+40b) into 40-implementation-plan.md
- `c9b3e26` Add discovery-2026-04-24/40b-implementation-operations.md
- `f5a043b` Add discovery-2026-04-24/40a-implementation-mechanics.md
- `4b6a39f` Add discovery-2026-04-24/33-final-feature-set.md
- `c51431c` Add discovery-2026-04-24/30-critique-signal-quality.md
- `e9c3a53` Add discovery-2026-04-24/31-critique-feasibility.md
- `1bc6bb5` Add discovery-2026-04-24/32-critique-adversarial.md
- `abbe409` Add discovery-2026-04-24/20-candidate-features.md
- `703ec47` Add discovery-2026-04-24/13-research-technical-quant.md
- `07f14b8` Add discovery-2026-04-24/14-research-catalysts-macro.md
- `4b93baf` Expand discovery-2026-04-24/10-research-sentiment.md
- `0a15a79` Add discovery-2026-04-24/00-system-map.md
- `9abb24d` Add discovery-2026-04-24/12-research-insider-filings.md
- `e9f9308` Add discovery-2026-04-24/11-research-flow.md
- `5fb4ce4` Add discovery-2026-04-24/10-research-sentiment.md

Last updated: 2026-04-24 (orchestrator — final all-green)
