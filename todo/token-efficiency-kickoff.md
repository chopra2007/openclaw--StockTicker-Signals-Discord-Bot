Optimize token efficiency for Claude Code on this Ubuntu VPS, and prepare reusable local helpers for a subsequent Codex optimization session.

This is an execution task: audit, implement safe improvements, test them, and report what actually changed. Do not stop after proposing a plan.

OBJECTIVE

Reduce avoidable context, repeated work, and unnecessary output while preserving coding capability, required reasoning effort, correctness, security, and verification standards.

Treat 50% lower total token usage as a stretch target—not a guarantee or a reason to remove necessary information. Prefer a smaller verified improvement over a larger unverified one.

I previously used Claude and Codex through subscription logins rather than API keys. Verify the current situation without exposing credentials. Distinguish subscription allowance, token counts, and actual API billing.

EXPLICIT PERMISSION TO EDIT INSTRUCTION FILES

This request explicitly authorizes editing these specific files for Phase 2A (this overrides the standing "never edit CLAUDE.md" memory rule for this task only):
- /home/openclaw/.openclaw/workspace/CLAUDE.md
- /root/.claude/CLAUDE.md
- /root/.claude/projects/-home-openclaw--openclaw-workspace/memory/MEMORY.md (and the memory topic files it links to, if moving detail there)

Do NOT edit /home/openclaw/.openclaw/workspace/comm-check.md.

KNOWN SUSPECTS — START THE AUDIT HERE

These were observed at session start on 2026-09-22. Measure them first before searching elsewhere:
1. The SessionStart hook pastes about 10KB of /root/task_system/notifications.log into every session (15 lines, mostly the same Schwab-login warning repeated daily, plus repeated TODO #117 sync warnings).
2. The "superpowers" plugin injects its full using-superpowers skill text at every session start.
3. The oh-my-claudecode (OMC) plugin adds about 70 deferred MCP tools plus its own hooks and session-restore text.
4. The project CLAUDE.md (~15.5KB) and MEMORY.md (~14.5KB) load every session.
5. A PostToolUse hook injected ~17KB (the full workspace AGENTS.md, labelled "[Project AGENTS: ...]") into context after a single Write call. Find which hook does this and how often it fires.
Changing a plugin's enabled state or a hook counts as a configuration change: back it up, and verify the features that depend on it still work (e.g. the stop-hook verifier, the claim tripwire, the notifications check the project CLAUDE.md requires at session start).

MACHINE-SPECIFIC FACTS

- Claude sessions run as root, but workspace files are owned by openclaw. After every edit or new file inside /home/openclaw/.openclaw, restore the original owner, group, and mode (compare with `stat` before and after). /root/.openclaw is a symlink to /home/openclaw/.openclaw.
- A daily systemd timer (omc_claudemd_trim.service, 03:30 PDT) edits /root/.claude/CLAUDE.md. Check recorded hashes before any rollback, and do not re-add the OMC block it removes.
- Run benchmark sessions OUTSIDE /home/openclaw/.openclaw/workspace (e.g. a fixture under the scratchpad or $HOME/.local/share/cli-token-efficiency/). A Claude session inside the workspace blocks the trade-alert builder.
- A Stop hook (/root/.claude/hooks/verify-on-done.py) re-runs tests when a session says it is done. Record it as a confounder in benchmark measurements and count its cost.
- Codex reads its own AGENTS.md files (/home/openclaw/.openclaw/workspace/AGENTS.md and /root/.codex/AGENTS.md). These are separate files from CLAUDE.md — do not edit them.
- All times shown to the user must be PDT, never ET.

SCOPE AND SAFETY

1. Work on the current user's Claude configuration and the project from which this session was launched. Resolve the real project path and inspect Git status first. Do not scan the entire VPS or modify unrelated repositories.

2. Codex will receive a separate prompt afterward. Do not edit Codex configuration, AGENTS.md, or other instruction files shared with Codex during this phase. You may inspect relevant non-secret configuration to avoid conflicts.

3. Preserve the current model, provider, authentication, reasoning/thinking effort, permissions, and normal output budget. Do not enable paid API access, extra credits, cheaper-model fallbacks, or new external services.

4. Do not alter production application code, restart services, interfere with running builds, change ownership broadly, or use destructive Git commands. Preserve all existing user changes (the repo currently has many uncommitted files — do not touch them). Check symlinks before treating a temporary copy or worktree as isolated.

5. BACKUPS AND PARTIAL ROLLBACK (required):
   - Back up every file before modifying it, including settings.json, plugin/hook configs, CLAUDE.md files, MEMORY.md, and memory topic files. Preserve ownership and permissions in the backup.
   - Keep private backups, logs, and reports outside the repository and outside automatically loaded instruction directories. Use:
     $HOME/.local/share/cli-token-efficiency/
     Organize records by canonical project path and timestamp.
   - Group every change into named rollback groups, at minimum: (a) instruction files (CLAUDE.md files), (b) memory files, (c) hooks/settings/plugin config, (d) helper scripts. Each group must be revertible on its own, and all groups together.
   - Provide one rollback script with these modes: revert one group, revert one file, revert everything, and a dry-run that shows what would change. Before restoring a file, it must compare the current hash with the recorded "after" hash; if they differ (the file was edited since), it must refuse and show a diff instead of overwriting. It must restore original owner and mode.
   - Test the rollback script: dry-run all groups, then actually revert and re-apply one group on a copy, and confirm hashes match.
   - Create a manifest containing the project path, changed files, group of each file, before/after hashes, owner/mode, helper locations, and rollback instructions. Never include credentials in reports.

6. Prefer existing utilities and native features. Do not upgrade the CLIs, perform system-wide package changes, install global command replacements, or run unreviewed installation scripts.

7. Continue through safe, reversible work without repeatedly asking for confirmation. Skip changes outside these boundaries and explain them in the report.

PHASE 1 — BOUNDED AUDIT AND BASELINE

Check:
- Installed Claude version, executable path, launch wrappers, and relevant environment-variable names. Do not dump environment values or credential files.
- Authentication/billing mode using supported, non-secret status information.
- Effective configuration and instruction-loading hierarchy, including global/project/local instructions, imports, rules, auto-memory indexes, hooks, skills, plugins, MCP definitions, and launch-time overrides.
- Any existing output filters, usage collectors, or context-management tools.
- A small sample of recent usage metadata, where available, to identify large tool outputs, repeated reads, repeated instructions, unnecessary delegation, and retries. Do not ingest entire session histories.

Use official documentation applicable to the installed version. Confirm settings and flags through installed help, schemas, or observed behavior. Latest documentation alone is not proof that an older installed version supports a feature.

Do not assume .claudeignore exists or that Git ignore rules prevent every form of file access.

Identify the highest-impact sources of waste before adding tools.

Before changing configuration or instructions, record a baseline and define a small fixed benchmark:
A. Locate relevant code and explain a narrow behavior.
B. Diagnose a deliberately noisy failing test or log.
C. Make a small, constrained code change and pass its tests in an isolated fixture or safe project copy.

Keep tasks, starting files, acceptance criteria, model, and reasoning settings identical between before and after. Never run benchmark edits against production.

PHASE 2 — IMPLEMENT LOW-RISK IMPROVEMENTS

A. Instruction hygiene

Remove duplication and unnecessary prose from the named instruction files while preserving every substantive constraint, exception, command, path, safety rule, and testing obligation.

Use concise, complete sentences, not ambiguous shorthand.

Keep essential rules always available. Move genuinely task-specific detail to supported on-demand mechanisms only when reliable discovery and loading can be demonstrated.

Do not claim savings from splitting files into imports that still load automatically.

Record a brief old-requirement-to-new-location checklist. If a rule's meaning is uncertain, preserve it.

Keep audit reports and optimization history out of permanent startup instructions.

B. Repository navigation

Prefer targeted file discovery, symbol searches, bounded reads, and narrow diffs over recursive dumps or repeatedly reading entire files.

Avoid generated files, dependencies, binaries, and large logs during routine discovery through verified search behavior and explicit search scopes.

Do not modify .gitignore just to control AI context.
Do not blanket-ban lockfiles, migrations, generated interfaces, or dependency files. Read them when the task requires them.

Keep context hygiene separate from security permissions.

C. Local command-output handling

Reuse an existing safe helper if available. Otherwise create the smallest practical, explicitly named helper for verbose diagnostic commands. Prefer already-installed tools or the language standard library.

Do not replace or globally alias git, cat, grep, test runners, or other standard commands.

The helper must:
- Run the underlying command without changing its meaning.
- Preserve its exit status and handle interruption correctly.
- Save complete stdout/stderr locally with restrictive permissions.
- Return a bounded, useful diagnostic view with status, test counts where available, warnings, errors, and relevant surrounding lines.
- Explicitly label truncation or summarization and provide the full-log path and a retrieval command.
- Allow further targeted reads and an unfiltered bypass.
- Avoid silently turning helper failures into command success.
- Never be inserted where another program requires the original stdout format.

Do not use "success means print nothing" or indiscriminate head/tail filtering as the only strategy. Important warnings and failures can occur in the middle of output.

Saving the original does not make a summary lossless. Retrieve omitted material whenever it may affect the decision.

Test the helper locally with successful commands, warnings on success, nonzero exits, a traceback in the middle of a long log, large output, and raw-log retrieval.

If integrating through a hook, verify that filtering occurs before the output enters model context. Appending a summary after the full output is already included is not an optimization.

D. Workflow and visible responses

Add concise guidance to:
- Read relevant files once where practical and reuse established facts.
- Inspect before editing, make focused changes, and run appropriate tests.
- Avoid unnecessary full-file rewrites and repeating code already written to disk.
- End with a brief result, tests, and unresolved risks.
- Preserve necessary explanations, warnings, and architectural reasoning.
- Start a fresh task session or use supported compaction when appropriate, retaining a compact handoff of constraints, decisions, changed files, tests, and next steps.

Do not disable required reviews or tests. Do not lower reasoning effort or impose restrictive generation limits to manufacture savings.

Do not add agent swarms or recursive self-optimization. Future delegation should use bounded tasks and concise handoffs, not full transcript forwarding. Include delegated usage when evaluating total savings.

Inspect existing retry behavior only within this scope. Flag repeated output-limit failures or no-progress retries; do not change production controllers as part of this task.

E. Optional tools

Briefly evaluate Headroom, 9Router/NineRouter, and Caveman only against demonstrated needs. Do not install a proxy/router or enable model substitution in this pass.

For any proposed later experiment, identify:
- Exact project/version and maintenance status.
- Compatibility with the installed CLI and current authentication.
- Credential handling and whether provider-supported access is preserved.
- Streaming, tool-call, and signed/encrypted reasoning-state compatibility.
- Effects on prompt caching.
- Exact-source retrieval, failure behavior, rollback, and ongoing maintenance.

Do not treat marketing percentages as measured results. Do not add an LLM-based summarizer without accounting for its own cost and potential information loss.

PHASE 3 — VERIFY AND MEASURE

Validate configuration syntax, confirm that the CLI actually loads the changes, and test the helper's real integration.

Run the predefined before/after comparisons in fresh, isolated task sessions. Use at most one baseline and one optimized run per benchmark task for this initial pass. Do not launch an expensive benchmark campaign or repeatedly rerun failed comparisons.

Use native usage records or supported structured output where available. Report:
- Input and output tokens.
- Cached input and cache-creation/read categories where exposed.
- Reasoning tokens where exposed.
- Tool calls, retries, elapsed time, and acceptance-test results.

Respect each provider's accounting semantics. Do not double-count cached tokens or cumulative session totals. Include any subagent, hook, or compression-model usage.

Record cache conditions and other confounders. Treat the small sample as a smoke test, not proof of identical quality across all future tasks.

Separate:
1. Smaller tool output or startup instructions.
2. Lower measured total task tokens.
3. Estimated API cost, only when applicable and clearly labeled.
4. Observed subscription usage, only when exposed.

Do not estimate precise subscription savings from token counts. Do not present character counts as measured tokens.

If reliable token telemetry is unavailable, say so and provide a ready-to-run measurement procedure. Never invent before/after numbers.

Keep only changes that pass correctness checks. Revert demonstrated regressions. A rollback must not overwrite subsequent user edits; use recorded hashes or a reviewed reverse patch.

Before finishing, confirm consensus-engine.service and openclaw-gateway.service are both still active.

DELIVERABLES

Save:
- A short audit and change report.
- The manifest, backups, grouped rollback script, and its test results.
- Any shared helper, local tests, and exact usage commands.
- Benchmark definitions, results, and limitations.
- claude-handoff.md for the subsequent Codex session.

The handoff must explain what Codex should reuse, what remains untouched, helper interfaces, known limitations, and how to verify the shared components without repeating the whole audit.

In the final response (plain language — the user is not a coder), give the changed-file paths, measured results, any skipped risky proposals, the exact rollback commands (per group and all), and the exact handoff path. Be concise. Do not claim the 50% target was achieved unless the measurements support it.
