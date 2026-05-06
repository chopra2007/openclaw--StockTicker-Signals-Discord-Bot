# OpenClaw Windows Routines — Opus Replan Handoff

**Date:** 2026-05-02
**Purpose:** Input document for Opus replan session. Read this before the existing plan files.
**Status:** Plan needs full rewrite. No code has been written yet.

---

## What Is OpenClaw?

OpenClaw is a Discord bot running on a Linux VPS that monitors financial signals (tweets, Reddit, news, SEC filings, YouTube) and posts actionable trade alerts to Discord. All signals flow through `db.insert_signal(TickerSignal)` at `consensus_engine/db.py:700`. The engine scores signals, cross-references sources, and fires alerts when confidence is high enough.

**Operator philosophy:** No manual review. System should be self-checking, self-healing, and highly reliable. Goal is actionable trade alerts surfaced automatically.

---

## What the Operator Wants to Build

Use **Claude Desktop routines** — specifically Windows Desktop Scheduled Tasks — to make OpenClaw better by giving it access to signal sources only available on the operator's Windows PC:

- Authenticated web content (Reddit logged in, Seeking Alpha, Benzinga)
- Gmail inbox (financial alerts, analyst emails)
- Discord channels that the OpenClaw bot cannot be invited to

These are high-value signal sources that the VPS cannot access without the Windows machine.

---

## Claude Desktop Routines — What They Actually Are

Source: `https://code.claude.com/docs/en/routines`
Also read: `https://code.claude.com/docs/en/desktop-scheduled-tasks`

**Remote routines:** Autonomous Claude Code sessions running on Anthropic's cloud. Good for GitHub/repo work. NOT useful here — they can't access the operator's Windows apps.

**Desktop Scheduled Tasks (the relevant type):** Autonomous Claude Code sessions that run locally on the operator's Windows machine on a schedule. Created in Claude Desktop by choosing "Local" when creating a routine. They have access to:
- Local files and apps on Windows
- The operator's browser sessions
- Windows system (clipboard, COM objects, etc.)
- MCP connectors configured on the machine

**Key capabilities:**
- Full Claude Code session — can run shell commands, use tools, call MCP connectors
- No permission prompts during run (fully autonomous)
- Schedule triggers (minimum 1h interval), API triggers, GitHub event triggers
- Can use MCP connectors to write to external services (including the VPS)

**This is the correct runtime for Windows signal gathering.** The previous plan built custom Python daemons instead of leveraging this.

---

## The Previous Plan's Fatal Flaw

The v2 plan (`.omc/plans/local-windows-routines-plan.md`) built a custom Python relay architecture:
- Windows Python scripts gather signals
- Scripts POST signals to a Discord channel (`#desktop-feed`)
- VPS runs a `DesktopFeedListener` that reads from `#desktop-feed` and calls `db.insert_signal()`

This is unnecessary complexity. **Claude Desktop routines on Windows can use MCP connectors to write directly to the VPS** — no Discord relay channel, no custom listener, no ACK/NACK protocol, no outbox buffering needed.

The replan must determine the correct transport and simplify accordingly.

---

## Confirmed Phase Decisions (do not revisit)

| Phase | Decision | Notes |
|---|---|---|
| Phase 1 (R3 Gap Detection) | **DEFERRED** | Build after Windows routines run for 2+ weeks and produce real data. When built, must auto-feed back into bot scoring — NOT a manual review dashboard. |
| Phase 3 (Discord bot-relay) | **REMOVED** | Operator cannot invite bot to all target channels. |
| Phase 4 (Clipboard sentinel) | **REMOVED** | Operator does not want this. |
| Phase 5 (Bookmark sentinel) | **REMOVED** | Operator does not want this. |

**In-scope phases (need proper design):**

**Phase 0 — VPS infrastructure**
May need significant redesign depending on transport choice. The original relay architecture (DesktopFeedListener, seen_relay_nonces, outbox) may be entirely replaced by MCP. At minimum, 2 new SourceType values (`DESKTOP_AUTH`, `DESKTOP_LOCAL`) and DB schema additions are still needed.

**Phase 2 — Gmail (VPS-side)**
Replace the Outlook COM design with Gmail API running directly on the VPS. Official Google API, OAuth2 one-time setup, polls every 60s. Sender allowlist + subject filter + server-side `extract_tickers`. Marks emails read after confirmed `db.insert_signal`. No Windows dependency.

**Phase 6 — R1 Authenticated Web (Windows)**
The one true Windows scheduled routine. 15 runs/week operator-defined quota (not a platform limit). Targets: Reddit (authenticated), Seeking Alpha, Benzinga. Question for Opus: should this be a Claude Desktop scheduled task using Claude's browser tools, or a custom Playwright script? Evaluate both.

**Phase 7 — Discord UI monitoring (Windows)**
Reading Discord channels the bot can't access. Must be Windows-side (user has Discord desktop app running). Currently designed as a pywinauto UIA daemon (persistent, polls every 300s). Question for Opus: can this be a Claude Desktop scheduled task instead of a persistent Python daemon? Evaluate. ToS risk is operator-acknowledged.

---

## Key Design Questions for Opus to Answer

**Q1 — Transport:** What is the correct way for Windows routines to write signals to the VPS?
- Option A: MCP connector (Claude routine uses an MCP server that wraps `db.insert_signal`)
- Option B: Discord relay (existing design — complex but proven)
- Option C: Direct SSH/API call to VPS
- Option D: Something else

**Q2 — Phase 6 runtime:** Claude Desktop scheduled task (Claude uses browser tools) vs. custom Playwright Python script. Which is more reliable for 15 authenticated web scraping sessions per week?

**Q3 — Phase 7 runtime:** Persistent Python daemon vs. Claude Desktop scheduled task (polling every 300s). Which fits better with the Desktop Scheduled Tasks model?

**Q4 — Phase 0 scope:** Given the transport answer from Q1, what VPS infrastructure is actually needed? Can the relay architecture be eliminated entirely?

**Q5 — Gmail (Phase 2):** Is Gmail API the right call, or is there a better VPS-native approach? (Himalaya CLI skill exists on ClawHub but requires IMAP setup.)

---

## Constraints (hard, do not violate)

1. No changes to `consensus_engine/alerts/`, `engine.py`, `cross_reference.py`, or any sentiment-scoring code.
2. No changes to `consensus_engine/scanners/volume_scanner.py` or `consensus_engine/briefing/alfred.py`.
3. All signals must ultimately reach `db.insert_signal(TickerSignal)` on the VPS.
4. Operator must not need to manually review anything for the system to produce actionable alerts.
5. Reliability is the top priority. Missing a signal is worse than processing it slowly.
6. All new routines use `Sentiment.NEUTRAL`. Publisher labels go in `source_detail` only.
7. `extract_tickers()` stays engine-side only. Windows side sends `raw_text`; server fans out per ticker.

---

## Files to Read Before Planning

1. **This document** (you are reading it)
2. `.omc/plans/local-windows-routines-plan.md` — full v2 plan + v3 session notes at the bottom
3. `.omc/plans/local-win-routines-discovery.md` — schema and codebase source-of-truth
4. `.omc/plans/local-win-routines-designs.md` — design rationale
5. `CLAUDE.md` — project conventions
6. Claude Desktop routines docs: `https://code.claude.com/docs/en/routines`
7. Desktop scheduled tasks docs: `https://code.claude.com/docs/en/desktop-scheduled-tasks`

---

## What the New Plan Must Produce

A revised, implementation-ready execution plan that:
- Correctly leverages Claude Desktop routines as the Windows runtime
- Answers Q1–Q5 above with codebase-grounded decisions
- Has a clear phase order with TDD discipline (failing test → implementation → green)
- Produces zero new manual review surfaces
- Passes adversarial review before handing off to an executor
