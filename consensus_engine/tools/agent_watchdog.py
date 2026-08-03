"""Kill an `openclaw agent` run once it starts repeating itself (TODO #45).

The agent runtime has no cap on tool rounds. On 2026-07-21 the model ran one
identical ``exec`` query **39 times** — same arguments, same stale result every
time — until its own 120s budget killed the run. The user waited 4.5 minutes and
got no answer. There is no ``--max-tool-rounds`` flag and no config key for it,
so the guard has to live out here in the wrapper.

It can, because the runtime writes every tool call to the session transcript
**as it happens**. Verified live 2026-07-21: during a 15s run the transcript grew
at 4.8s, 11.1s and 13.8s, one step at a time, each row carrying the tool name and
its arguments. Watching that file is enough to see a loop forming and end the run
at the repeat rather than at the wall.

Two things this deliberately does NOT do:

* It never counts rows that were already in the file when the run started. A
  channel transcript is reused across questions, and yesterday's identical
  lookups are not this run's loop.
* It only kills on *identical* (tool, arguments) pairs. A repeated call with
  different arguments is ordinary work; a repeated call with the same arguments
  cannot return anything new, which is exactly why the model never escapes it.
"""

import asyncio
import json
import logging
import os
import signal

log = logging.getLogger(__name__)


def kill_run(proc) -> None:
    """Kill an agent run and everything it spawned.

    Killing just the `openclaw` process is not enough. Its tools spawn shell
    children that inherit the output pipe, so the pipe stays open and
    ``communicate()`` keeps waiting on a run that is already dead — measured
    live 2026-07-21 at **9 seconds** between the kill and the call returning.
    Killing the whole process group ends the descendants too.

    Callers must spawn with ``start_new_session=True`` so the run is its own
    group leader. If it somehow is not, this falls back to killing the single
    process: signalling a group we share would take down the engine itself.
    """
    pid = getattr(proc, "pid", None)
    # `type(pid) is int` on purpose. isinstance() also accepts True, and True *is*
    # integer 1 — os.killpg(1, SIGKILL) becomes kill(-1, 9), which kills every
    # process this user owns. A mock pid converts to 1 the same way.
    if type(pid) is int and pid > 1:
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            return  # already gone
        except Exception:
            pgid = None
        # pgid == pid proves the child really leads its own group, as
        # start_new_session=True promises. Anything else may be a group we share.
        if pgid is not None and pgid > 1 and pgid == pid and pgid != os.getpgrp():
            try:
                os.killpg(pgid, signal.SIGKILL)
                return
            except ProcessLookupError:
                return  # already gone
            except Exception as exc:
                log.debug("process-group kill failed, falling back: %s", exc)
    try:
        proc.kill()
    except Exception as exc:
        log.warning("could not kill agent run: %s", exc)

SESSION_DIR = "/home/openclaw/.openclaw/agents/main/sessions"

# 39 rounds of the same call in the incident. Healthy runs on this bot use 1-3
# rounds, and those are 3 *different* calls. Coming back to the identical call a
# fourth time means the result is not moving the model along.
DEFAULT_REPEAT_LIMIT = 4
# Backstop for a loop that varies its arguments just enough to dodge the check
# above (e.g. an offset creeping by one). This is the max-tool-rounds cap TODO
# #45 asked for; set far above real use so it never fires on legitimate work.
DEFAULT_MAX_ROUNDS = 25
DEFAULT_POLL_SECONDS = 2.0


def session_path(session_id: str) -> str:
    return os.path.join(SESSION_DIR, f"{session_id}.jsonl")


def _rows(path: str) -> list[dict]:
    """Every parsable row of a session transcript, oldest first.

    Read whole rather than tailed from a byte offset: the runtime rewrites and
    can *shrink* this file when a run ends, so a remembered offset goes stale.
    """
    try:
        with open(path, "r", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return []
    out = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a row half-written at the moment we read it
        if isinstance(row, dict):
            out.append(row)
    return out


def row_ids(path: str) -> set:
    """Ids of the rows already present — the baseline to exclude."""
    return {r.get("id") for r in _rows(path) if r.get("id")}


def scan(path: str, exclude_ids: set) -> tuple[list[list[tuple[str, str]]], bool]:
    """Read one run out of a transcript: its tool rounds, and whether it answered.

    Returns ``(rounds, answered)``. A *round* is one assistant turn, holding the
    ``(tool name, canonical arguments)`` of every call that turn made.

    Rounds, not raw calls, are the unit that matters. A model may batch several
    identical calls into a single turn — verified live 2026-07-21, one turn fired
    the same command 8 times in parallel — and that is one decision, not a loop.
    A loop is the model issuing the same call *again after seeing its result*,
    round after round, which is exactly what the 2026-07-21 incident did 39 times
    while its prompt grew from 117k to 336k tokens.

    ``answered`` means the model has produced a reply — it spoke instead of
    calling a tool, or called the runtime's explicit ``sessions_yield``. Once
    that happens the run is done and must not be killed, whatever else is in the
    file. The tradeoff is that a model which speaks and *then* loops goes
    unguarded — a missed catch, which is the cheaper mistake.
    """
    rounds = []
    answered = False
    for row in _rows(path):
        if row.get("type") != "message" or row.get("id") in exclude_ids:
            continue
        message = row.get("message") or {}
        content = message.get("content")
        is_assistant = message.get("role") == "assistant"
        if is_assistant and isinstance(content, str) and content.strip():
            answered = True
        if not isinstance(content, list):
            continue
        calls = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and is_assistant:
                if str(block.get("text") or "").strip():
                    answered = True
                continue
            if block.get("type") != "toolCall":
                continue
            name = str(block.get("name") or "")
            if name == "sessions_yield":
                answered = True
            try:
                args = json.dumps(block.get("arguments"), sort_keys=True)
            except (TypeError, ValueError):
                args = repr(block.get("arguments"))
            calls.append((name, args))
        if calls:
            rounds.append(calls)
    return rounds, answered


def tool_rounds(path: str, exclude_ids: set) -> list[list[tuple[str, str]]]:
    """Just the tool rounds taken since the baseline."""
    return scan(path, exclude_ids)[0]


def find_loop(rounds, *, repeat_limit: int, max_rounds: int) -> str:
    """Describe the loop these rounds are in, or "" if they look healthy."""
    if max_rounds and len(rounds) >= max_rounds:
        return f"{len(rounds)} tool rounds in one run (limit {max_rounds})"
    counts: dict[tuple[str, str], int] = {}
    for calls in rounds:
        for key in set(calls):  # a batch of identical calls is still one round
            counts[key] = counts.get(key, 0) + 1
            if repeat_limit and counts[key] >= repeat_limit:
                name, args = key
                return (f"called {name} in {counts[key]} separate rounds with "
                        f"identical arguments {args[:120]}")
    return ""


class AgentWatchdog:
    """Watches one `openclaw agent` run and kills it if it starts looping.

    Construct it *before* spawning the subprocess so the baseline is taken from
    the transcript as the run finds it. Then::

        wd = AgentWatchdog(session_id)
        proc = await asyncio.create_subprocess_exec(...)
        wd.start(proc)
        try:
            ... await proc.communicate() ...
        finally:
            await wd.stop()
        if wd.triggered:
            ...   # a loop, not an ordinary empty reply
    """

    def __init__(self, session_id: str, *, repeat_limit: int = DEFAULT_REPEAT_LIMIT,
                 max_rounds: int = DEFAULT_MAX_ROUNDS,
                 poll_seconds: float = DEFAULT_POLL_SECONDS):
        self.session_id = session_id
        self.repeat_limit = repeat_limit
        self.max_rounds = max_rounds
        self.poll_seconds = poll_seconds
        self.path = session_path(session_id)
        self.triggered = False
        self.reason = ""
        self._baseline = row_ids(self.path)
        self._task = None

    def start(self, proc) -> None:
        self._task = asyncio.ensure_future(self._watch(proc))

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    async def _watch(self, proc) -> None:
        while proc.returncode is None:
            await asyncio.sleep(self.poll_seconds)
            try:
                rounds, answered = scan(self.path, self._baseline)
                if answered:
                    return  # it has replied; nothing left worth killing
                reason = find_loop(rounds, repeat_limit=self.repeat_limit,
                                   max_rounds=self.max_rounds)
            except Exception as exc:
                # A watchdog must never be the thing that breaks the run.
                log.debug("agent watchdog read failed: %s", exc)
                continue
            if not reason:
                continue
            # The transcript lags the run by a few seconds, so an answer may have
            # landed since. Look once more before killing rather than throw one away.
            if scan(self.path, self._baseline)[1]:
                return
            self.triggered = True
            self.reason = reason
            log.error("Agent stuck in a tool loop on session=%s — killing the run: %s",
                      self.session_id, reason)
            kill_run(proc)
            return
