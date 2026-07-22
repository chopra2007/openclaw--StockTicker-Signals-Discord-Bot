"""Tests for the repeated-tool-call watchdog (TODO #45).

The 2026-07-21 incident: the agent ran one identical `exec` query 39 times, same
arguments and same stale result every time, until its own 120s budget killed the
run. Nothing capped tool rounds, so the user waited 4.5 minutes for nothing.

These pin the guard that now ends such a run at the repeat:

1. counting — identical calls trip the limit, varied ones never do.
2. scoping — calls already in the transcript when the run started are ignored,
   because a channel transcript is reused across questions.
3. killing — a live run that starts repeating is actually killed.
4. patience — a healthy run is never killed.
5. end to end — `_handle_mention` reports a loop as a loop.
"""
import asyncio
import json
import os
from unittest.mock import AsyncMock

from consensus_engine import main as main_mod
from consensus_engine.tools import agent_watchdog as wd


def _call_row(row_id: str, name: str, arguments: dict) -> dict:
    """One assistant message carrying a single tool call, as the runtime writes it."""
    return {
        "type": "message",
        "id": row_id,
        "timestamp": "2026-07-21T08:00:00.000Z",
        "message": {
            "role": "assistant",
            "content": [{"type": "toolCall", "id": f"call_{row_id}",
                         "name": name, "arguments": arguments}],
        },
    }


def _write(path, rows) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def scan_answered(path) -> bool:
    return wd.scan(str(path), set())[1]


# ---------------------------------------------------------------- 1. counting

def _same_call_each_round(n, name="exec", arguments='{"command": "SELECT 1"}'):
    return [[(name, arguments)] for _ in range(n)]


def test_the_same_call_in_four_rounds_trips_the_limit():
    reason = wd.find_loop(_same_call_each_round(4), repeat_limit=4, max_rounds=25)
    assert "exec" in reason and "4 separate rounds" in reason


def test_three_rounds_are_still_allowed():
    """A model re-reading something twice is not a loop."""
    assert wd.find_loop(_same_call_each_round(3), repeat_limit=4, max_rounds=25) == ""


def test_many_different_calls_are_never_a_loop():
    """Real work: lots of rounds, none of them repeating. Must not trip."""
    rounds = [[("read", json.dumps({"path": f"file_{i}.py"}))] for i in range(20)]
    assert wd.find_loop(rounds, repeat_limit=4, max_rounds=25) == ""


def test_a_batch_of_identical_calls_in_one_round_is_not_a_loop():
    """Seen live 2026-07-21: one turn fired the same command 8 times in
    parallel. That is a single decision, not a model failing to converge.
    """
    rounds = [[("process", '{"command": "echo LOOPCHECK"}')] * 8]
    assert wd.find_loop(rounds, repeat_limit=4, max_rounds=25) == ""


def test_round_cap_catches_a_loop_that_varies_its_arguments():
    """The backstop: an offset creeping by one dodges the identical-args check."""
    rounds = [[("read", json.dumps({"path": "a.py", "offset": i}))] for i in range(25)]
    assert "25 tool rounds" in wd.find_loop(rounds, repeat_limit=4, max_rounds=25)


def test_the_real_incident_shape_is_caught():
    """39 rounds of the identical exec call — the exact 2026-07-21 failure."""
    rounds = _same_call_each_round(39, arguments='{"command": "sqlite3 rollups"}')
    assert wd.find_loop(rounds, repeat_limit=4, max_rounds=25) != ""


# ----------------------------------------------------------------- 2. scoping

def test_calls_from_earlier_questions_are_not_counted(tmp_path, monkeypatch):
    """A channel transcript is reused. Yesterday's repeats are not this loop."""
    monkeypatch.setattr(wd, "SESSION_DIR", str(tmp_path))
    path = tmp_path / "chan.jsonl"
    old = [_call_row(f"old{i}", "exec", {"command": "SELECT 1"}) for i in range(6)]
    _write(path, old)

    baseline = wd.row_ids(str(path))
    assert len(baseline) == 6

    # The new run makes one call. Six identical ones sit above it in the file.
    _write(path, old + [_call_row("new1", "exec", {"command": "SELECT 1"})])
    rounds = wd.tool_rounds(str(path), baseline)
    assert rounds == [[("exec", '{"command": "SELECT 1"}')]]
    assert wd.find_loop(rounds, repeat_limit=4, max_rounds=25) == ""


def test_one_message_carrying_several_calls_is_one_round(tmp_path):
    """The runtime packs parallel calls into a single row. One row, one round."""
    path = tmp_path / "s.jsonl"
    row = {
        "type": "message", "id": "r1",
        "message": {"role": "assistant", "content": [
            {"type": "toolCall", "name": "exec", "arguments": {"command": "x"}},
            {"type": "toolCall", "name": "exec", "arguments": {"command": "x"}},
            {"type": "toolCall", "name": "exec", "arguments": {"command": "x"}},
            {"type": "toolCall", "name": "exec", "arguments": {"command": "x"}},
        ]},
    }
    _write(path, [row])
    rounds = wd.tool_rounds(str(path), set())
    assert len(rounds) == 1 and len(rounds[0]) == 4
    assert wd.find_loop(rounds, repeat_limit=4, max_rounds=25) == ""


def test_argument_order_does_not_hide_a_repeat(tmp_path):
    """Same arguments written in a different key order is the same call."""
    path = tmp_path / "s.jsonl"
    rows = [
        _call_row("a", "read", {"path": "x.py", "limit": 50}),
        _call_row("b", "read", {"limit": 50, "path": "x.py"}),
    ]
    _write(path, rows)
    rounds = wd.tool_rounds(str(path), set())
    assert rounds[0] == rounds[1]


def test_missing_and_half_written_files_are_survivable(tmp_path):
    """The file is read while it is being appended to — never raise."""
    assert wd.row_ids(str(tmp_path / "nope.jsonl")) == set()
    assert wd.tool_rounds(str(tmp_path / "nope.jsonl"), set()) == []

    path = tmp_path / "torn.jsonl"
    good = json.dumps(_call_row("a", "exec", {"command": "x"}))
    path.write_text(good + "\n" + '{"type": "message", "id": "b", "mess')
    assert wd.tool_rounds(str(path), set()) == [[("exec", '{"command": "x"}')]]


def test_non_tool_rows_are_ignored(tmp_path):
    """User messages and results carry no toolCall blocks."""
    path = tmp_path / "s.jsonl"
    _write(path, [
        {"type": "session", "id": "s1", "version": 1},
        {"type": "message", "id": "u1",
         "message": {"role": "user", "content": "hello"}},
        {"type": "message", "id": "t1",
         "message": {"role": "toolResult", "content": [{"type": "text", "text": "ok"}]}},
    ])
    assert wd.tool_rounds(str(path), set()) == []


# ------------------------------------------------------- 3. killing the group

def test_kill_run_never_signals_our_own_process_group(monkeypatch):
    """The engine runs the agent as a subprocess. If the run somehow shares our
    process group, a group kill would take the engine down with it — so that
    case must fall back to killing the single process.
    """
    signalled, killed = [], []

    class _Proc:
        pid = os.getpid()  # same group as this test process

        def kill(self):
            killed.append(True)

    monkeypatch.setattr(wd.os, "killpg", lambda *a: signalled.append(a))
    wd.kill_run(_Proc())

    assert signalled == [], "must never signal a process group we are in"
    assert killed == [True]


def test_kill_run_kills_the_whole_group_when_the_run_has_its_own(monkeypatch):
    """The normal case: the run is its own group leader, so take the group."""
    signalled, killed = [], []
    monkeypatch.setattr(wd.os, "getpgid", lambda pid: 4242 if pid else os.getpgid(0))
    monkeypatch.setattr(wd.os, "killpg", lambda *a: signalled.append(a))

    class _Proc:
        pid = 99999

        def kill(self):  # pragma: no cover - group kill should have won
            killed.append(True)

    wd.kill_run(_Proc())
    assert signalled == [(4242, wd.signal.SIGKILL)]
    assert killed == []


# ----------------------------------------------------------------- 4. killing

class _FakeProc:
    """A run that appends one tool call per tick until something kills it."""

    def __init__(self, path, name="exec", arguments=None, vary=False, stdout=b""):
        self.returncode = None
        self.killed = False
        self._path = path
        self._name = name
        self._args = arguments if arguments is not None else {"command": "SELECT 1"}
        self._vary = vary
        self._stdout = stdout
        self._n = 0

    async def communicate(self):
        while self.returncode is None and self._n < 60:
            self._n += 1
            args = dict(self._args)
            if self._vary:
                args["path"] = f"file_{self._n}.py"
            with open(self._path, "a") as fh:
                fh.write(json.dumps(_call_row(f"n{self._n}", self._name, args)) + "\n")
            await asyncio.sleep(0.01)
        return self._stdout, b""

    def kill(self):
        self.killed = True
        self.returncode = -9


async def test_watchdog_kills_a_run_that_starts_repeating(tmp_path, monkeypatch):
    monkeypatch.setattr(wd, "SESSION_DIR", str(tmp_path))
    path = tmp_path / "chan.jsonl"
    path.write_text("")

    watchdog = wd.AgentWatchdog("chan", repeat_limit=4, max_rounds=25, poll_seconds=0.02)
    proc = _FakeProc(str(path))
    watchdog.start(proc)
    await asyncio.wait_for(proc.communicate(), timeout=5)
    await watchdog.stop()

    assert proc.killed is True, "the looping run should have been killed"
    assert watchdog.triggered is True
    assert "exec" in watchdog.reason
    # Killed at the repeat, not after dozens of calls.
    assert proc._n < 20, f"killed too late, after {proc._n} calls"


async def test_watchdog_leaves_a_healthy_run_alone(tmp_path, monkeypatch):
    """Different arguments every time — ordinary work, must survive."""
    monkeypatch.setattr(wd, "SESSION_DIR", str(tmp_path))
    path = tmp_path / "chan.jsonl"
    path.write_text("")

    watchdog = wd.AgentWatchdog("chan", repeat_limit=4, max_rounds=100, poll_seconds=0.02)
    proc = _FakeProc(str(path), name="read", arguments={}, vary=True)
    watchdog.start(proc)
    await asyncio.wait_for(proc.communicate(), timeout=5)
    await watchdog.stop()

    assert proc.killed is False
    assert watchdog.triggered is False


def test_an_answered_run_is_recognised(tmp_path):
    """Assistant text and sessions_yield both mean "this run has replied"."""
    spoke = tmp_path / "spoke.jsonl"
    _write(spoke, [
        _call_row("a", "exec", {"command": "x"}),
        {"type": "message", "id": "b", "message": {
            "role": "assistant", "content": [{"type": "text", "text": "here you go"}]}},
    ])
    assert scan_answered(spoke) is True

    yielded = tmp_path / "yielded.jsonl"
    _write(yielded, [_call_row("a", "sessions_yield", {"message": "DONE"})])
    assert scan_answered(yielded) is True

    working = tmp_path / "working.jsonl"
    _write(working, [_call_row("a", "exec", {"command": "x"})])
    assert scan_answered(working) is False


async def test_a_run_that_already_answered_is_never_killed(tmp_path, monkeypatch):
    """The live 2026-07-21 case: the answer came at 6.2s, the repeated calls
    only reached the transcript afterwards. Killing then destroys a good reply.
    """
    monkeypatch.setattr(wd, "SESSION_DIR", str(tmp_path))
    path = tmp_path / "chan.jsonl"
    rows = [_call_row(f"n{i}", "exec", {"command": "SELECT 1"}) for i in range(8)]
    rows.append({"type": "message", "id": "final", "message": {
        "role": "assistant", "content": [{"type": "text", "text": "the answer"}]}})
    _write(path, rows)

    watchdog = wd.AgentWatchdog("chan", repeat_limit=4, max_rounds=25, poll_seconds=0.01)

    class _Lingering:
        returncode = None
        killed = False

        def kill(self):
            self.killed = True

    proc = _Lingering()
    watchdog.start(proc)
    await asyncio.sleep(0.1)
    await watchdog.stop()

    assert proc.killed is False, "a run that already answered must not be killed"
    assert watchdog.triggered is False


async def test_watchdog_stops_cleanly_when_the_run_ends_first(tmp_path, monkeypatch):
    """Normal case: the run finishes, the watchdog is cancelled, nothing raises."""
    monkeypatch.setattr(wd, "SESSION_DIR", str(tmp_path))
    (tmp_path / "chan.jsonl").write_text("")
    watchdog = wd.AgentWatchdog("chan", poll_seconds=0.01)

    class _Quick:
        returncode = 0

        def kill(self):  # pragma: no cover - must never be reached
            raise AssertionError("healthy run was killed")

    watchdog.start(_Quick())
    await watchdog.stop()
    assert watchdog.triggered is False


# -------------------------------------------------------------- 4. end to end

async def test_handle_mention_reports_a_tool_loop_as_a_loop(tmp_path, monkeypatch):
    """The whole path: a looping run is killed, and the user is told why.

    Pinned to a single attempt (no fallback models) so the test does not sit
    through the inter-attempt backoff.
    """
    monkeypatch.setattr(wd, "SESSION_DIR", str(tmp_path))
    real_get = main_mod.cfg.get

    def _fake_get(key, default=None):
        if key == "llm.agent_fallback_models":
            return []
        if key == "llm.agent_watchdog_poll_seconds":
            return 0.02
        return real_get(key, default)

    monkeypatch.setattr(main_mod.cfg, "get", _fake_get)

    session_file = tmp_path / "channel-chan_loop.jsonl"
    session_file.write_text("")
    proc = _FakeProc(str(session_file))

    async def _factory(*a, **kw):
        return proc

    monkeypatch.setattr(main_mod.asyncio, "create_subprocess_exec", _factory)
    monkeypatch.setattr(main_mod, "_roll_oversized_session", lambda _s: None)
    monkeypatch.setattr(main_mod, "_reset_agent_session", lambda _s: None)

    from consensus_engine.alerts import discord as discord_mod
    reply_mock = AsyncMock()
    monkeypatch.setattr(discord_mod, "send_command_reply", reply_mock)

    await asyncio.wait_for(
        main_mod._handle_mention("what is up", "chan_loop", "msg_1"), timeout=20)

    assert proc.killed is True, "the looping run should have been killed"
    assert reply_mock.await_count == 1
    text = reply_mock.call_args.args[2]
    assert "repeating the same lookup" in text, text
    assert "stopped it early" in text, text


async def test_a_real_answer_beats_the_watchdog(tmp_path, monkeypatch):
    """If the run answered before the kill landed, post the answer.

    Otherwise the guard becomes the outage: the user loses a reply the bot
    already had. Seen live 2026-07-21 on a real `openclaw agent` run.
    """
    monkeypatch.setattr(wd, "SESSION_DIR", str(tmp_path))
    real_get = main_mod.cfg.get

    def _fake_get(key, default=None):
        if key == "llm.agent_fallback_models":
            return []
        if key == "llm.agent_watchdog_poll_seconds":
            return 0.02
        return real_get(key, default)

    monkeypatch.setattr(main_mod.cfg, "get", _fake_get)

    session_file = tmp_path / "channel-chan_ok.jsonl"
    session_file.write_text("")
    proc = _FakeProc(str(session_file), stdout=b"NVDA closed at 4")

    async def _factory(*a, **kw):
        return proc

    monkeypatch.setattr(main_mod.asyncio, "create_subprocess_exec", _factory)
    monkeypatch.setattr(main_mod, "_roll_oversized_session", lambda _s: None)
    monkeypatch.setattr(main_mod, "_reset_agent_session", lambda _s: None)

    from consensus_engine.alerts import discord as discord_mod
    reply_mock = AsyncMock()
    monkeypatch.setattr(discord_mod, "send_command_reply", reply_mock)

    await asyncio.wait_for(
        main_mod._handle_mention("what is up", "chan_ok", "msg_1"), timeout=20)

    assert reply_mock.await_count == 1
    text = reply_mock.call_args.args[2]
    assert text == "NVDA closed at 4", text
    assert "couldn't answer" not in text
