# CI auto-fixer model race (#59)

Capability is a **gate**, not a score. Among models that clear the bar, the cheapest wins; a model that fails it is out at any price.

**The gate** is the job the fixer actually does: `ci_autofix.sh` reaches the AI branch only after it has ruled out a missing package and reproduced the failure locally twice. So the model must (a) recognise a real logic bug and (b) patch it so the failing test passes and its siblings stay green. The `flaky` column is informational — the deterministic layer catches those before a model ever sees them.

| model | dep | flaky (not scored) | real bug | patch passes? | $ / race | latency |
|---|---|---|---|---|---|---|
| `qwen/qwen3-coder-next` | ✅ | ❌ real_logic_bug | ✅ | ✅ yes | $0.0086 | 11s |
| `deepseek/deepseek-chat-v3.1` | ✅ | ❌ real_logic_bug | ✅ | ❌ the failing test still fails | $0.0172 | 35s |
| `z-ai/glm-4.5-air` | ✅ | ❌ ERROR | ✅ | ❌ the failing test still fails | $0.0060 | 26s |

**Winner: `qwen/qwen3-coder-next`** — cleared the capability gate at the lowest cost ($0.0086 for the whole race).

### Errors seen

- flaky: FixerError: z-ai/glm-4.5-air: no complete reply within 210s — giving up

---

## The single-sample result above is not trustworthy — here is the measured one

The table is one attempt per model. These models are nondeterministic even at
`temperature=0`, and re-running the winner's exact case by hand did **not** reproduce
its pass. So each model was then run **5 times** on the same reproduced bug, verifying
every patch against the failing test and its siblings:

| model | working patch | bad patch | no usable patch |
|---|---|---|---|
| `qwen/qwen3-coder-next` | **1 / 5** | 4 | 0 |
| `deepseek/deepseek-chat-v3.1` | 0 / 5 | 5 | 0 |
| `z-ai/glm-4.5-air` | 0 / 5 | 2 | 3 |

`qwen/qwen3-coder-next` is the only model that ever produces a correct fix. It is also
the cheapest. It is pinned — but at **one attempt in five**, not the "✅ yes" the
single-sample table implies.

**So the branch retries three times** (`AI_ATTEMPTS=3` in `ci_autofix.sh`), verifying
after each and reverting a patch that doesn't work. That lifts a ~20% chance to ~49%
per red gate, for roughly 1.5 cents. A wrong patch is harmless: it must make the failing
tests pass **and** leave the full suite clean against `.test-baseline`, or it is reverted
and a human is paged — exactly today's behaviour.

## Two harness bugs the first race exposed (both were mine, not the models')

1. **The models never saw the code under test.** Context was assembled from the files
   named in the traceback. The frozen-date bug is caused by `wolf_news.post_event()`
   stamping `time.time()`, and `wolf_news.py` appears nowhere in the traceback — so every
   model failed a question no human could have answered. `relevant_files()` now follows
   the failing test's imports two hops deep.
2. **A hung call could hang forever.** `requests`' read timeout measures the gap *between*
   bytes, and OpenRouter sends SSE keepalive comments while a model thinks — which resets
   that clock indefinitely. One call blocked for 25 minutes with a 240s timeout set. The
   fixer now streams under a hard wall-clock deadline. `glm-4.5-air` hit it during the
   re-race, which is the guard doing its job.

## How often does this branch even fire?

Measured from 64 `session_close` logs (2026-05-30 → 2026-07-09):

- 13 red gates (20% of sessions) — but **7 of the 13 were the same persistent
  frozen-date test**, a time bomb unrelated to that session's changes.
- Since that bug was fixed on 2026-07-02: **1 red gate in 17 sessions (~6%)**.
- `undeclared_dependency` — the class the deterministic layer handles — has occurred
  **once, ever**, and in CI rather than at session close.

So a genuine logic bug reddens the gate roughly **once a month**. With three attempts at
~49%, this branch saves a human session about **six times a year** and costs pennies.
That is worth wiring, and it is nowhere near good enough to be trusted to push.
