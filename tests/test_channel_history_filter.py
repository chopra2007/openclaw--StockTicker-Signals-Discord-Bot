"""The agent's channel-history context must not contain the bot's own errors.

2026-07-21: after a failed run the bot posted "⚠️ Agent unavailable after 2
attempts". The next question fed the last 10 channel messages back to the agent
as context — including that line. The agent read its own error notice and
reported it to the user as a live system status ("the agent was unavailable
after multiple attempts, likely a temporary internal problem"), which sounded
like a diagnosis but was just its own output echoed back.

These lines are noise to the agent, never conversation. Filtering them is what
stops a failure from feeding the next answer's hallucination.
"""
import pytest

from consensus_engine.alerts import commands as commands_mod


def _reply(text: str) -> dict:
    """A message the BOT posted."""
    return {"author": {"username": "API", "bot": True}, "content": text, "embeds": []}


def _user_says(text: str) -> dict:
    """A message a HUMAN posted."""
    return {"author": {"username": "akash_chopra"}, "content": text, "embeds": []}


async def _history(monkeypatch, messages: list) -> str:
    """Run _fetch_channel_history against a stubbed Discord response."""
    class _Resp:
        status = 200

        async def json(self):
            return list(reversed(messages))  # API returns newest-first

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

    class _Session:
        def get(self, *_args, **_kwargs):
            return _Resp()

    async def _get_session():
        return _Session()

    monkeypatch.setattr(commands_mod.cfg, "get_api_key", lambda _k: "token")
    monkeypatch.setattr("consensus_engine.utils.http.get_session", _get_session)
    return await commands_mod._fetch_channel_history("chan_1", limit=10)


@pytest.mark.parametrize("notice", [
    "⚠️ I couldn't answer that. I tried 2× (a different model each time) and each try ran out of time.",
    "⚠️ Agent unavailable after 2 attempts. Last error: agent run aborted before answering",
    "⚠️ 🛠️ Exec failed: `run python3 inline script` (agent)",
])
async def test_bot_failure_notices_are_stripped(monkeypatch, notice):
    """The bot's own failure text must never re-enter the agent's context."""
    history = await _history(monkeypatch, [
        _reply(notice),
        _reply("NVDA closed at 178.20."),
    ])

    assert "NVDA closed at 178.20." in history, "real replies must survive"
    for marker in ("couldn't answer that", "unavailable after", "Exec failed"):
        assert marker not in history, f"{marker!r} leaked into agent context"


async def test_ordinary_conversation_is_untouched(monkeypatch):
    """The filter must be narrow — only the bot's own error notices."""
    history = await _history(monkeypatch, [
        _reply("Here is the options flow for AMD."),
        _reply("The scan found 3 candidates."),
    ])

    assert "options flow for AMD" in history
    assert "found 3 candidates" in history


@pytest.mark.parametrize("prose", [
    "I cannot access the message with ID 1521022584072831057 directly.",
    "I cannot retrieve the last message and I lack the message content currently.",
    "The system response indicated an agent error, and the agent was unavailable.",
    "It appears the agent encountered a failure and is unavailable after multiple attempts.",
    "This suggests a temporary internal system or agent problem.",
])
async def test_bot_self_talk_prose_is_stripped(monkeypatch, prose):
    """The second wave: free prose the model writes about its own broken state.

    These are not the structured notices this code posts — they are sentences a
    model invented. Left in the history they became the next answer's source,
    so a single failure kept re-infecting every reply after it.
    """
    history = await _history(monkeypatch, [
        _reply(prose),
        _reply("SPY closed at 742.15."),
    ])

    assert "SPY closed at 742.15." in history, "real replies must survive"
    assert prose not in history, "the bot's self-talk must never become context"


@pytest.mark.parametrize("text", [
    "I cannot access my brokerage account, is that related?",
    "I can't read the chart you posted — can you repost it?",
])
async def test_the_user_saying_the_same_words_is_kept(monkeypatch, text):
    """Scoping matters: this filter is about the BOT talking about itself.

    A human saying "I can't access X" is a real question. Dropping it would
    silently delete the thing the agent most needs to answer.
    """
    history = await _history(monkeypatch, [_user_says(text)])

    assert text in history, "a user's own words must never be filtered"
