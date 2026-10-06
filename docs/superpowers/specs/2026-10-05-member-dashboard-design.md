# Member dashboard build brief

Date: October 5, 2026 (Pacific time)

Status: Proposed design for owner review. Application implementation has not started.

## Purpose and agreed scope

Give 10-20 invited users a professional web interface to the existing stock-research pipeline. The homepage combines a curated intelligence feed with trade-setup cards. Entering a ticker opens one complete research page; users do not have to run five separate commands.

Accounts use a username and password created through a single-use invitation. Discord membership and Discord sign-in are not required. Members retain their own chat and report history and can delete it. Feed updates should normally appear within 15-30 seconds of becoming available to the web data service.

The admin panel covers system monitoring, member access, and dashboard feature visibility. Feature switches must not change bot collection, analysis settings, live services, or Discord output.

The supplied tutorial is visual inspiration. Its setup commands, dependencies, hosting choices, and AI instructions are not requirements for this build.

## User experience

### Home

- Global ticker search with clear handling of unknown or unsupported symbols.
- Curated summaries of analyst posts, news, catalysts, and alerts, with source links and timestamps.
- Trade-setup cards with available entry levels, targets, invalidation, supporting evidence, and the time of the analysis.
- Source freshness and missing-data indicators. Research-only records must be labeled and kept distinct from live published setups.
- Clicking a ticker or setup opens its ticker research page.

### Unified ticker research page

One ticker submission loads all enabled sections automatically. On desktop, use a wide report area and a narrower context column; on smaller screens, stack sections in reading order. Anchor navigation can jump within the page without hiding the other research behind separate commands.

| Section | Existing behavior to reuse | Presentation |
| --- | --- | --- |
| Custom Stock Analysis | `!all` | Executive summary, direction, technical score, catalysts, evidence, conflicts, and available trade levels |
| SEC Filings | `!sec` | Filing timeline, insider activity, summaries, and original filing links |
| Options Activity | `!options` | Unusual activity, contracts, volume/open-interest comparisons, and call/put context |
| Daily Expected Move | `!em` | Daily chart, estimated range, expiry, and source timestamp |
| Weekly Expected Move | `!emw` | Weekly chart and range alongside the daily view, or directly below it on narrow screens |

Gamma exposure, IV skew, and risk metrics appear where the existing analysis supplies them, with their method and freshness retained. Missing values are unavailable, never zero-filled. Expected-move estimates remain distinct from trade targets and guaranteed price bounds.

Use cached results immediately when valid and show independent progress for unfinished sections. A slow or failed provider must not blank the rest of the page. Each section shows its own observation time; do not imply that results computed at different times form one simultaneous market snapshot.

The feed refresh target is separate from analysis duration. Expensive research may take longer and must show queued, running, completed, unavailable, or failed status. Manual refresh joins existing work or schedules a bounded refresh; it does not launch unrestricted duplicate jobs.

Provide a prominent Market Assistant entry point with the current ticker as context. The chat remains a separate conversation experience rather than a sixth auto-running ticker section.

### Market Assistant

Members can ask follow-up questions using approved market records and the selected LLM's reasoning capabilities. Answers cite retrieved evidence and distinguish observations from interpretation. Freshness and missing evidence remain visible.

Use a dedicated member-assistant service and tool allowlist. Do not forward web requests into the existing operational OpenClaw agent. Approved tools expose bounded market lookups and research jobs only. No shell, arbitrary SQL, unrestricted filesystem access, host configuration, secrets, private operational messages, or admin actions are available to this assistant.

Validate authorization and feature permissions at every tool invocation. Retrieved posts, filings, and documents are untrusted source material, not instructions. The assistant sees only the current member's conversation history and approved shared market information. Operational details and raw provider errors must not leak through normal answers, citations, or failure messages.

### Personal history

Store each member's conversations and saved report references under their account. Automatically retain completed requested reports, including the generated content, source timestamps, and analysis version needed to reopen the original result rather than silently substituting today's result.

Market computations can be shared in a cache, but conversations, history lists, and saved-report ownership are private per account. Deleting a member's saved report removes their copy/reference without deleting another member's report or source market records. Members can delete individual conversations and reports.

## Accounts and recovery

Recommended launch choice: admin-issued, single-use password-reset links. At this invitation-only size, this avoids requiring email collection and a mail-delivery service.

- An admin generates a cryptographically random invitation, delivered outside the application through their chosen existing contact method.
- Store only the token digest. Invitation creation displays the usable token/link once; logs and analytics must not record it.
- Default invitation expiry: seven days. The admin can revoke it before use.
- Redemption atomically consumes the invitation and creates the account. Concurrent redemption must create at most one account.
- Store passwords with an established password-hashing library and modern password hashing. Never store recoverable passwords.
- Use server-controlled sessions in secure cookies, request-forgery protection, login throttling, and generic authentication errors.
- An admin can suspend an account and revoke its sessions. Suspension also blocks queued member work from delivering new private results.
- Password reset uses a separate, revocable, single-use token with a one-hour expiry. A new reset token invalidates older unused tokens. Successful reset revokes existing sessions.
- The admin verifies the requester through the same trusted contact used for the invitation before providing a reset link. The admin never needs to know the new password.
- The first administrator is provisioned through a local management step; invitations cannot assign administrator privileges.

Expiry values are proposed defaults, not previously requested requirements. Recovery links and invitations must not appear in committed files or ordinary audit records.

## Admin panel

Separate administrator authorization from member access at the API layer, not only in navigation.

Monitoring shows service health, feed freshness, recent sanitized failures, queue status, and web AI usage. Monitoring is read-only. Admin views can show operational status, while member responses receive only user-relevant availability information.

Member management includes invitation creation/revocation, account suspension/reactivation, session revocation, and password-reset link creation. Audit these changes without storing raw tokens or passwords.

Feature switches are global web controls for the curated feed, trade-setup cards, custom analysis, SEC filings, options activity, daily expected move, weekly expected move, and Market Assistant. Enforce switches in web routes, APIs, and assistant tools. A hidden feature must not remain callable through a direct API request. Disable new web requests and visibility for that feature without modifying bot configuration or shared production work.

Bot model management, service restarts, channel remapping, and collection controls are outside this version's agreed admin scope.

## Repository findings and reuse boundaries

These are source-code findings from the reviewed worktree. Current production configuration, populated table coverage, capacity, and service versions have not been audited for this dashboard.

- [Discord listener](../../../consensus_engine/scanners/discord_tweetshift.py) receives message events and extracts source text and images. It is not proof of a complete archive of every channel.
- [Database definitions](../../../consensus_engine/db.py) include `analyst_post_views`, `signal_events`, `alert_history`, `decision_snapshots`, `options_flow`, expected-move-related snapshots, and health records. Expired `ticker_signals` are pruned.
- [Ingestion server](../../../consensus_engine/ingest_server.py) registers `POST /ingest` and `POST /heartbeat`; a member read API is new work.
- [Command handlers](../../../consensus_engine/alerts/commands.py) connect the requested command behaviors to the underlying analysis functions and Discord reply formatting.
- [Ticker analysis aggregator](../../../consensus_engine/alerts/all_command/aggregator.py) assembles cached, multi-source analysis and structured fields. Rich results are not all established as durable web-ready records.
- [Expected-move calculation](../../../consensus_engine/scanners/expected_move.py) provides a reusable calculation boundary for daily and weekly results.
- [Operational agent integration](../../../consensus_engine/main.py) gives the current `!ask` path host-oriented tools and context. It must not be used as the member assistant endpoint.

Reuse computation and structured results, not the Discord command handlers' send-message side effects. Where computation and delivery are coupled, introduce the smallest tested separation and keep existing Discord behavior working.

## Proposed architecture

Choose Next.js with TypeScript, Tailwind, and shadcn/ui for the web interface, plus a separate Python FastAPI service and bounded background worker for market research. Select supported package versions when preparing the implementation plan; do not copy the tutorial's version pins.

For 10-20 members, start with two distinct data stores on the VPS:

1. The existing bot SQLite database remains owned by the bot. A dedicated adapter uses short read-only queries and does not invoke bot database initialization or migrations.
2. A separate web SQLite database stores accounts, sessions, invitation/reset digests, chats, report snapshots, feature settings, audit events, and durable web job state. Use short transactions and a small worker pool. PostgreSQL is a later option if measured write load or multiple-host deployment requires it.

The frontend accesses data only through authenticated APIs. Database files are never exposed to browsers or mounted across a network. Persist selected publishable market records and completed research snapshots into the web store with source identifiers and update versions so expired bot records do not erase saved reports.

Use durable job identifiers, request deduplication, retries with bounds, and per-member rate limits. Share equivalent market computations across members while preserving each member's authorization and private context. A worker restart must recover job state without duplicating expensive provider calls where a completed result already exists.

Deliver an initial feed snapshot and poll for updates every 15 seconds while the page is active, using a cursor to avoid full reloads. Resume from the last cursor after reconnecting. Represent changed alerts as updates to an existing card instead of duplicate cards. Loading cached pages must not generate new AI summaries every 15 seconds.

Generate curated summaries once per source item/version where possible. Reuse existing structured summaries when suitable. Publication records need stable source IDs, content versions, timestamps, provenance, and publishability filters. Map each desired feed to real stored data before promising coverage; explicitly identify channel-only data that needs a new capture adapter.

Run the web services separately from production bot processes behind HTTPS. Apply resource and concurrency limits so member research cannot starve Discord workloads. Check actual VPS headroom before selecting same-host deployment; if inadequate, move web services to a separate host and transfer approved data through an authenticated service rather than sharing SQLite files.

## Design choices and alternatives

The Python API preserves the existing analysis language and provides a clear member-data boundary. A separate aiohttp API would reduce new dependencies but requires more API validation/documentation work. A Next.js-only backend would introduce more bridging to Python and is not the preferred design.

The small launch audience supports a simple local database and bounded worker design. Do not add a distributed queue, a second ingestion pipeline, or a replacement bot database without measured need.

## Acceptance checks

1. A valid invitation creates one username/password account exactly once; expired, revoked, and concurrently replayed tokens cannot create extra accounts.
2. Password recovery works without email, reveals no existing password, and invalidates older sessions and reset tokens.
3. Submitting a supported ticker automatically loads every enabled research section with independent progress and timestamps.
4. Stock analysis, SEC, options, and expected-move results agree with the reusable calculation paths for the same fixed inputs. Web research never posts to Discord.
5. Slow or missing data leaves other sections usable. Stale, delayed, research-only, and unavailable data are labeled rather than converted into favorable results.
6. New publishable alerts appear within the 15-30-second target under the agreed 10-20-member load. Analysis completion times are measured separately.
7. A member can reopen and delete their own chats and reports, but cannot retrieve another account's history by changing URLs, IDs, or assistant requests.
8. The member assistant cannot reach host files, secrets, admin endpoints, or unrestricted operational tools, including when retrieved content asks it to do so.
9. Feature switches affect the web interface and its API access while bot configuration, collection, and Discord output remain unchanged.
10. Page refreshes and simultaneous requests reuse valid results; the cache never shares private conversations between accounts.
11. Disabled or suspended access is enforced server-side. Private pages and responses are not placed in a public shared cache.
12. Job restarts, provider failures, and session expiry have usable recovery behavior and safe user-facing messages.
13. Desktop and mobile layouts are readable, keyboard usable, and show all user-facing timestamps in Pacific time.
14. Repository regression checks and the required live-service checks pass before production activation. Verify the actual member flow from invitation through saved research and chat, not just isolated endpoints.

## Next stage

Review this brief, then produce the implementation plan with exact file boundaries, data mappings, isolation checks, tests, and deployment steps. The implementation plan should sequence accounts and safe data access, the unified ticker page and feed, the member assistant and history, then admin controls and launch verification. This sequence is proposed planning structure, not authorization to implement or deploy now.

## Reusable implementation handoff prompt

Implement the approved member-dashboard design in this document using the separately approved implementation plan. Preserve the existing Discord bot's behavior. Build independent invitation-based accounts for 10-20 users, a curated feed, a unified ticker page covering all five research commands, and a separate market assistant with approved data tools only. Keep member history private and feature switches web-only. Reuse existing calculations without sending Discord messages from web requests. Verify current source data and production boundaries, follow repository rules, and complete the acceptance checks before describing the dashboard as ready. Read this document and the approved plan rather than relying on a summary of the conversation.
