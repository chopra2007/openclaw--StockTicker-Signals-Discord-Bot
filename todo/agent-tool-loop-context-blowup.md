# Agent tool-loop context blow-up (runaway token accumulation on heavy questions)

**Status:** DONE 2026-06-16 — status line backfilled 2026-07-12 (TODO #72 cleanup; the header and session notes had already recorded completion).
**Created:** 2026-06-16

## The problem
When the `@`-mention / `!ask` agent answers a heavy, tool-triggering question (e.g. "give me a
read on NVDA today"), some models keep calling tools and re-feeding the results until the
accumulated context explodes — then the whole turn times out and the user gets
"⚠️ Agent unavailable".

Measured live on 2026-06-16 (real `openclaw agent --local` path, `.omc/research/model-bakeoff-2026-06-15/agent_matrix_out/`):
- **gpt-oss-120b**: 233k–325k cumulative tokens/turn → timed out or returned empty on 5/5 heavy questions, even at the 240s production limit.
- **qwen3-235b-2507**: 173k–687k tokens/turn (worst: 976k on one NVDA run) → converged but slow/expensive.
- **gpt-4.1-nano**: 2k–21k tokens/turn → converged in 11–13s. **mistral-small**: 1.5k–84k → converged in 12–14s.

So it is strongly **model-dependent**: lean models terminate the tool loop quickly; others loop and balloon. We already worked around it by making **gpt-4.1-nano the agent lead** (TODO #44) — the bot works now. This item is to fix the **underlying loop**, so a future model swap doesn't silently reintroduce timeouts.

## Suspected root cause (unverified)
The agent re-sends growing tool-result context each round and either (a) the web/news tools return
very large bodies that aren't trimmed before being fed back, and/or (b) there's no hard cap on
tool-call rounds / cumulative context, so a verbose model never converges. The 976k-token figure
on a single NVDA question points at un-trimmed tool results more than model choice alone.

## Next steps (priority-ordered)
1. **Instrument one heavy run** — re-run "read on NVDA" with gpt-oss-120b via `--model` (temp
   allow-map add, revert after — see the ownership trap notes) and capture the trajectory
   (`/home/openclaw/.openclaw/agents/main/sessions/<id>.jsonl`) to see how many tool rounds fire and
   how big each tool result is.
2. **Check for a tool-result size cap** in the openclaw agent config / tool definitions — if web
   search returns full pages, truncate tool results before they re-enter context.
3. **Check for a max-tool-rounds / max-context guard** in the agent loop; add one if absent.
4. Re-test the heavy questions across models afterward — goal: even token-hungry models converge.

## Files / where to pick up cold
- Real-path harness + raw outputs: `.omc/research/model-bakeoff-2026-06-15/agent_matrix.sh`, `agent_matrix_out/`.
- Mention handler (the subprocess + timeout): `consensus_engine/main.py:600` (`_handle_mention`), `--timeout 240`.
- Agent chain config: `config/consensus.yaml` `llm.agent_model` / `agent_fallback_models`; mirrored to openclaw.json by `scripts/sync_gateway_models.py`.
- Full bake-off context: `todo/model-bakeoff-2026-06-15.md` (TODO #44).

## Caveat
n=1 question class (NVDA-style heavy reads, run repeatedly). Confirm it generalizes (it did across
qA/qB/qC in the matrix — all three heavy questions blew up gpt-oss-120b). Ownership trap: running
`openclaw` as root flips openclaw.json to root:root → breaks the openclaw-run gateway on next
restart. Always run as `sudo -u openclaw` and chown back.
