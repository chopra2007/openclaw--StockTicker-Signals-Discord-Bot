# Member dashboard (TODO #121): Phase C kickoff

Read `todo/member-dashboard-finish.md` (Phases A and B are DONE) and `deploy/member-dashboard/README.md` first.
Implementer: main session. Verifier: a separate subagent that wrote none of the code. Follow CLAUDE.md
"Start of Build", "Definition of Done" and "Regression Gate". Run the full test suite ONCE, at the end (user rule).

## User decisions (2026-10-05, given in chat)

1. **Provider permissions** (Finnhub etc.): the user gets these personally. Not our gate. Wire real sources in;
   don't block on paperwork.
2. **Assistant model key:** use the user's existing OpenRouter key (`OPENROUTER_API_KEY` in
   `/root/.openclaw/.env.service`, the same one OpenClaw uses), through OpenRouter, with the model the design picked
   (`gpt-4o-mini-2024-07-18` → the matching OpenRouter id; confirm it exists in OpenRouter's live model list).
   **The key must never be visible:** copy it with a script straight from the env file into the dashboard's
   protected key file (mode 600, owned by the dashboard's service user). Never `cat`/`echo`/print it, never put it in
   a command line, log, commit, test fixture or chat. Verify by length/hash only.
3. **Budget:** $3/day total for the dashboard's paid calls. The bot shares the same OpenRouter balance, and the
   dashboard's own budget ledger enforces the cap.
4. **HTTPS domain:** none yet. Build and test everything else on the server without a public address. Domain and
   certificate wait until the user has one.
5. **Go-live approval:** ask the user only once everything else is done and proven.
6. **Research page vs `!all`:** keep them separate. The dashboard writes its own analysis, as designed. Don't make it
   reuse the bot's `!all` result.

## Scope for this session

- Production service users, units and config from `deploy/member-dashboard/` (still switched off for the public;
  no public address).
- Assistant on via OpenRouter with the $3/day cap. Prove one real assistant answer and that the cap stops spending.
- Real data sources wired (read-only from the bot's database, as designed).
- The launch gate "same-server bot speed comparison with dashboard running" (see the finish plan's Phase C table).
- Disk recheck (`df -h /`, need ≥10 GiB and ≥15% free).

Out of scope: domain/HTTPS, public exposure, go-live. At the end, list exactly what remains for go-live and ask the user.
