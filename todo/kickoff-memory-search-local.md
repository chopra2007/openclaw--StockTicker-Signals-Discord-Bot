# Kickoff — fix OpenClaw memory search (switch it back to local, on this server)

Written 2026-09-24, right after the OpenClaw 2026.9.4 → 2026.9.6 update.
Plan agreed by Claude and Codex (gpt-5.6-sol) over three review rounds.
Read this whole file before touching anything.

## Goal

When the OpenClaw agent searches its notes by meaning ("memory search"), it
returns real results from the notes it's meant to see. It runs on this server
with the small search model that is already downloaded: no API key, no GitHub
Copilot, no cost per search. The searched notes stay current as new notes are
written.

## What is wrong (all checked on 2026-09-24)

There are **two separate problems**. Fixing only the first still leaves search empty.

1. **The search engine setting is broken.**
   `sudo -u openclaw -H openclaw memory status --deep` fails with
   `Unknown memory embedding provider: github-copilot`.
   OpenClaw's docs (`/usr/lib/node_modules/openclaw/docs/reference/memory-config.md`,
   lines 125–131) say a named provider that can't run "fails closed": memory
   search returns *unavailable*, with no fallback to keyword search.
   - `/home/openclaw/.openclaw/openclaw.json` has `memory.search.provider = "github-copilot"`.
     The user confirmed Copilot was never the plan. There's no Copilot credential,
     and the `github-copilot` add-on is disabled and not in `plugins.allow`.
     That's why OpenClaw calls it "unknown."
   - How it got there: `todo/openclaw-doctor-warnings.md` line 22. On 2026-06-12 a
     past session switched it from `local` to `github-copilot`, only to silence a
     "local not configured" warning. It hasn't worked since. Every config backup
     (`openclaw.json.bak*`, the oldest being `.bak.4`) already says Copilot, so
     today's update didn't cause this.

2. **The notes folder it points at can't be read by the bot.**
   `memory.search.extraPaths` is
   `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory`. The gateway
   runs as user `openclaw`, and the folder above it
   (`/root/.claude/projects/-home-openclaw--openclaw-workspace`) is `drwx------ root`.
   `sudo -u openclaw test -r .../memory/reference_schwab_api.md` fails.
   So even with a working search engine, that folder would add nothing.

**What the original setup was:** local search on this server.
- A search model was downloaded on 2026-05-20 19:54:
  `/home/openclaw/.node-llama-cpp/models/hf_ggml-org_embeddinggemma-300m-qat-Q8_0.gguf`
  (329 MB, owned by `openclaw`). Its SHA-256 is
  `6fa0c02a9c302be6f977521d399b4de3a46310a4f2621ee0063747881b673f67`, which is exactly
  what the installed 2026.9.6 llama-cpp add-on expects.
- An index was built the same evening (`todo/bot_chat_memory_redesign.md` line 134:
  "memory search index is frozen (May 20)").

**Why `local` alone isn't enough on 2026.9.6:** local search now runs through the
**llama.cpp add-on** (`llama-cpp`), which manages a small `llama-server` program on
this machine (`docs/plugins/llama-cpp.md`; `memory-config.md` lines 342–366). The
add-on is installed but disabled, isn't in `plugins.allow` (currently: brave, browser,
discord, exa, google, memory-core, openrouter, searxng, skills, zai), and has no
`models.providers.llama-cpp` section yet.

## The two notes folders

| | Codex folder `/root/.codex/openclaw-memory/` | Claude folder `/root/.claude/projects/-home-openclaw--openclaw-workspace/memory/` |
|---|---|---|
| Can the bot read it? | **Yes** | **No** |
| Active notes | 232 (230 top-level `.md` + 2 in `indexes/`); also has an `archive/` of old backups | 259 `.md` |
| Overlap | 231 names in both folders: 220 identical, 11 different. 1 file only here (`README.md`) | 28 notes only here, e.g. `reference_discord_self_bot_command_probe.md` and `reference_openclaw_update_as_root.md` |
| Role | Main private notes store, per `docs/agents/MEMORY_GUIDE.md` | Where Claude sessions save every new note; runtime code may still read it, so never move or delete it |

**Decision: search the Codex folder only, and copy new Claude notes into it every day.**

Options we rejected, and why:
- **Opening a narrow permission on the Claude folder** (let `openclaw` pass through the
  project folder without listing it). The 102 transcript files there are locked to root,
  but session subfolders hold **92 more files anyone can read**: 76 saved tool outputs
  and 16 helper-agent files. Saved tool outputs can contain secrets. Rejected for that
  leak alone. (It would have kept the index current, but that doesn't outweigh the leak.)
- **Searching both folders.** OpenClaw's search has no duplicate filter: each result's ID
  is built from folder, file, lines, and text (`MemorySourceIndexKernel.replaceRows`).
  So the 220 identical notes would show up twice in every search.
- **Codex folder only, with no copying.** Claude sessions always save new notes to the
  Claude folder, so the searched notes would quietly fall further behind every day.

Also note: OpenClaw already searches the workspace's own `MEMORY.md`, `USER.md`, and
`memory/*.md` automatically. `extraPaths` only adds the private folder on top.

## Why local search, and not the other options

| Option | Verdict | Why |
|---|---|---|
| **Local search via the llama.cpp add-on (chosen)** | Do this | Restores the May setup. The model is already on disk and verified. Free, no outside key, nothing leaves the server. About 3.5 GiB of memory is free; measure the real memory use after setup instead of assuming it. |
| Get a Copilot key | No | The user said Copilot was never the plan. |
| A paid online service (OpenAI, Gemini, Voyage) | No | Needs a new key in both `.env` and `.env.service`, costs money per search, and sends the notes to an outside company. |
| `provider: "none"` (keyword search only) | Fallback only | Only finds exact words. Use it only if local truly can't run, and tell the user; never switch to it silently. |

## Rules for every step

- Run `openclaw` commands as the bot: `sudo -u openclaw -H openclaw ...`. Afterwards,
  run `python3 scripts/check_ownership.py --fix --quiet`.
- Before each config change:
  `cp -p /home/openclaw/.openclaw/openclaw.json /home/openclaw/.openclaw/openclaw.json.bak-memsearch-$(date +%Y%m%d-%H%M%S)`.
- `openclaw doctor --fix` and index rebuilds need the gateway **stopped**. The agent
  database only allows one owner at a time; see the comments in
  `/usr/local/bin/openclawupdate`. Use `systemctl stop|start openclaw-gateway.service`,
  and wait for port 18789 to be free.
- In `openclaw.json`, change only: the memory-search settings, the llama-cpp add-on
  entry and allow-list line, and the `models.providers.llama-cpp` section.
- Never add an ACL to, change permissions on, or move the Claude folder.
- The search index lives in `/home/openclaw/.openclaw/agents/main/agent/openclaw-agent.sqlite`.
  **Never delete it:** it also holds conversation history.

## Steps (check after each one)

0. **Preflight.** Save the exact output of
   `jq '.agents.defaults.model' /home/openclaw/.openclaw/openclaw.json`. That's the
   chat-model list, and it must end unchanged. Confirm the starting problem: `openclaw`
   can't read the Claude folder. As `openclaw`, check it can read
   `/root/.codex/openclaw-memory/`, every top-level `*.md` and `indexes/*.md` in it, and
   the model file. Check the model's SHA-256 matches the value above. Check that
   `/home/openclaw/.openclaw/agents/main/agent/` is writable by `openclaw`. Stop if any check fails.

1. **Build the daily note copy.** Write a small script run by root. It copies each `*.md`
   in the Claude folder that **does not yet exist** in the Codex folder.
   - Never overwrite (the 11 differing files keep Codex's version) and never delete.
   - Skip `MEMORY.md` (each folder keeps its own index), and skip anything that isn't
     a regular file.
   - Only copy names that match the known note styles (`feedback_`, `reference_`,
     `project_`, `user_`, `comm-check-fail-`, plus other existing patterns). Fail loudly
     on anything unexpected; don't import it silently.
   - New copies get `root:root`, mode `644`, the same as the existing Codex notes.
   - Add one line per copied note to `indexes/claude-import-index.md`, and link that
     file from the Codex folder's own `MEMORY.md` with one routing line.

   Known limit, record it: if an existing Claude note is edited later under the same
   name, the edit is **not** copied, because the copy never overwrites.

2. **Install it as a daily systemd timer.** Name it
   `openclaw-memory-sync.service` + `.timer`, runs as root, with logging and 3 retries.
   Follow the pattern of the existing daily timers in `/etc/systemd/system/`, for example
   `db-maintenance.timer`. (`/root/task_system/scripts/create_task.sh` only makes one-time
   tasks, so it isn't the right tool here.) Run it once right away.
   *Check the first run:* all 28 missing notes were copied; the 11 differing files are
   byte-for-byte unchanged; `MEMORY.md` is untouched apart from the one routing line;
   `openclaw` can read the copies; the index file exists; the top-level + `indexes/` count
   is 261 (232 + 28 + the new index file); the timer shows a next run and a clean log.

3. **Allow and enable the add-on.** Inspect it first with
   `sudo -u openclaw -H openclaw plugins inspect llama-cpp`. It should list
   `text-inference: llama-cpp` and `embedding: local`. Then run
   `sudo -u openclaw -H openclaw plugins enable --accept-capabilities llama-cpp`, which adds
   it to `plugins.allow`, records consent, and enables it. Don't hand-edit around the
   consent check.
   *Check:* `openclaw plugins list` shows it enabled; the config has the allow entry and
   `plugins.entries.llama-cpp.enabled: true`.

4. **Point memory search at local and the Codex folder.** Using `openclaw config set`:
   - `memory.search.provider` → `local`
   - `memory.search.local.modelPath` →
     `/home/openclaw/.node-llama-cpp/models/hf_ggml-org_embeddinggemma-300m-qat-Q8_0.gguf`
   - `memory.search.extraPaths` → exactly two entries:
     `{ "path": "/root/.codex/openclaw-memory", "pattern": "*.md" }` and
     `{ "path": "/root/.codex/openclaw-memory", "pattern": "indexes/*.md" }`
     (this skips `archive/` and any hidden folders).

   Run `openclaw config validate`. Diff against the backup: only these keys changed, and
   the chat-model list still matches step 0.

5. **Set up the managed local server, search model only.** The command is interactive:
   `sudo -u openclaw -H openclaw configure --section model`. Choose **llama.cpp**, decline
   any chat-model setup, and accept the separate embedding-only setup. If there's no live
   terminal, run it inside `tmux`, read each screen, answer, then close the tmux session.
   Don't hand it to the user just because it's interactive. Ask the user only if a screen
   asks for a secret, or offers a choice these instructions don't cover.
   *Check:* `models.providers.llama-cpp.localService` exists;
   `models.providers.llama-cpp.models` is empty; the chat-model list still matches step 0;
   `openclaw config validate` passes. A built-in `llama-cpp-local` marker in the provider
   section is expected. It isn't a real key, so leave it as is.

6. **Rebuild the search index** with the gateway stopped:
   `sudo -u openclaw -H openclaw memory index --force --agent main`. Then start the gateway.

7. **Prove it works for real. Settings that look right don't count.**
   - `sudo -u openclaw -H openclaw memory status --deep --agent main`: the local provider,
     the real model path, no skipped source folders, and no "stale index" warning.
   - Run a search by meaning, where the important words don't match:
     `sudo -u openclaw -H openclaw memory search --agent main --json "Why must a person periodically reauthorize the brokerage connection?"`
     It must return the **Codex-folder** `reference_schwab_api.md` (that passage says
     OAuth / refresh token / weekly manual re-login). Nothing from `archive/` may appear.
   - Search for something that only exists in an imported note, e.g. the one about
     posting a command as the bot. It must return the copied
     `reference_discord_self_bot_command_probe.md`.
   - Run a real `!ask` in Discord that explicitly tells the agent to use `memory_search`,
     asks the brokerage question, and requires the note's file name in the answer. Post
     it and read the reply using the method in `reference_discord_self_bot_command_probe.md`
     (in either notes folder). Read the reply that was actually posted.
   - `free -g`: server memory is still healthy. Note how much `llama-server` uses.

8. **Wrap up.**
   - Always-checks (`docs/agents/PROJECT_RULES.md` / CLAUDE.md `[always]`):
     `consensus-engine.service` and `openclaw-gateway.service` are both active;
     `openclaw gateway health` answers; the engine boot log shows
     "boot drift check: gateway chain matches consensus.yaml."
   - `openclaw doctor --non-interactive`: the "Memory search … github-copilot" warning is gone.
   - In `todo/openclaw-doctor-warnings.md` line 22, mark the Copilot switch as the wrong
     fix and add a dated note that it was reversed. Keep the history.
   - Save the lesson (local EmbeddingGemma via llama-cpp, never Copilot; search reads the
     Codex folder; the daily copy; why the permission option was rejected) where the running
     agent's own memory rules say. If that isn't the Codex folder, **also** save it there,
     so the agent can find it. Write it once if both are the same folder. Never overwrite
     one folder's `MEMORY.md` with the other's.
   - Commit locally (`python3 scripts/check_ownership.py` first). Don't push.

## Stop and ask the user if

- Any preflight check fails, or a file the bot must read isn't readable.
- The copy script or timer install fails, or the copy meets an unexpected file name.
- Anything from `archive/` shows up in search results, the database isn't writable, or
  the status shows a "stale index" warning or skipped folders.
- Setup tries to change the chat-model list or add a llama.cpp chat model.
- Setup can't reuse the existing model file and tries to download the same 329 MB model
  again. Stop before the download starts. Downloading the verified `llama-server` program is expected.
- Local setup needs something we don't have (a failed download, a build step, not enough
  memory). Report exactly what failed, and offer `provider: "none"` as the fallback.

## Not part of this job (noted, don't fix here)

- The stuck-run watchdog and conversation-reset helpers in `consensus_engine/main.py`
  (`_AGENT_SESSION_DIR`, `_build_agent_watchdog`, `_reset_agent_session`,
  `_roll_oversized_session`) read `/home/openclaw/.openclaw/agents/main/sessions/`, which
  OpenClaw hasn't written to since 2026-08-17. Those checks are probably doing nothing. Separate TODO.
- Other old doctor warnings (phone pairing, backups, GitHub login under root, the Discord
  add-on upgrade note while Discord is off on purpose). Leave them alone.
