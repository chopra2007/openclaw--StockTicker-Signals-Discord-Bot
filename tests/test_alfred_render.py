import json

import pytest
from consensus_engine.briefing import alfred


FORBIDDEN = ("Eastern", "EST", "EDT")

DATA = {
    "session_start_utc": 0, "session_end_utc": 1,
    "alerts": [{"ticker": "NVDA", "confidence_score": 90, "catalyst": "earnings",
                "catalyst_type": "news", "alerted_at": 0, "price_at_alert": 150}],
    "levels": [], "yt_signals": [],
    "macro": {"direction": "risk-on", "themes": "AI", "summary": "steady tape"},
    "top_tickers": [{"ticker": "NVDA", "sections": {"analyst": {"content": "bullish"}}}],
}


def _empty_data():
    return {"session_start_utc": 0, "session_end_utc": 1,
            "alerts": [], "levels": [], "yt_signals": [], "macro": None,
            "top_tickers": []}


def _good_json(**over):
    payload = {"overnight": "NVDA strong overnight.", "levels": "SPY 630 support",
               "calls": "NVDA bullish", "macro": "risk-on", "top_tickers": "NVDA"}
    payload.update(over)
    return json.dumps(payload)


def _assert_all_sections(out):
    for title in alfred._SECTION_TITLES.values():
        assert f"### {title}" in out, f"missing section {title}"


def _assert_no_exchange_timezone(out):
    assert not alfred._has_forbidden_timezone_label(out), out


async def test_render_briefing_uses_llm_sections(monkeypatch):
    async def fake_llm(prompt):
        assert "NVDA" in prompt
        return _good_json()
    monkeypatch.setattr(alfred, "_llm_synthesize", fake_llm)

    out = await alfred._render_briefing(dict(DATA))
    assert "Morning Brief" in out
    assert "NVDA strong overnight." in out
    _assert_all_sections(out)
    _assert_no_exchange_timezone(out)


async def test_render_briefing_keeps_top_story_without_dropping_sections(monkeypatch):
    async def fake_llm(prompt):
        return _good_json(top_story="NVDA gapped 4% on earnings.")
    monkeypatch.setattr(alfred, "_llm_synthesize", fake_llm)

    out = await alfred._render_briefing(dict(DATA))
    assert "> NVDA gapped 4% on earnings." in out
    _assert_all_sections(out)


@pytest.mark.parametrize("reply", ["", "not json at all", '{"overnight": "x"}',
                                   '{"overnight": 1, "levels": "", "calls": "",'
                                   ' "macro": "", "top_tickers": ""}'])
async def test_render_briefing_falls_back_on_bad_llm_output(monkeypatch, reply):
    async def bad(prompt): return reply
    monkeypatch.setattr(alfred, "_llm_synthesize", bad)

    out = await alfred._render_briefing(dict(DATA))
    _assert_all_sections(out)
    assert "NVDA" in out          # deterministic fallback still carries the data
    _assert_no_exchange_timezone(out)


async def test_render_briefing_falls_back_when_llm_raises(monkeypatch):
    async def boom(prompt): raise RuntimeError("openrouter down")
    monkeypatch.setattr(alfred, "_llm_synthesize", boom)

    out = await alfred._render_briefing(dict(DATA))
    _assert_all_sections(out)
    assert "NVDA" in out


async def test_render_briefing_rejects_exchange_timezone_labels(monkeypatch):
    async def wrong_timezone(prompt):
        return _good_json(overnight="Cash opens 9:30 EST. Watch NVDA.")
    monkeypatch.setattr(alfred, "_llm_synthesize", wrong_timezone)

    out = await alfred._render_briefing(dict(DATA))
    assert "EST" not in out
    _assert_all_sections(out)
    _assert_no_exchange_timezone(out)


async def test_render_briefing_preserves_et_stock_ticker(monkeypatch):
    async def ticker_not_timezone(prompt):
        return _good_json(overnight="Energy Transfer ($ET) is unchanged.")
    monkeypatch.setattr(alfred, "_llm_synthesize", ticker_not_timezone)

    out = await alfred._render_briefing(dict(DATA))
    assert "$ET" in out


async def test_render_briefing_shows_placeholders_when_nothing_happened(monkeypatch):
    async def empty(prompt): return ""
    monkeypatch.setattr(alfred, "_llm_synthesize", empty)

    out = await alfred._render_briefing(_empty_data())
    _assert_all_sections(out)
    assert "_Nothing overnight._" in out


async def test_render_briefing_rejects_absurdly_long_section(monkeypatch):
    async def huge(prompt): return _good_json(overnight="x" * 5000)
    monkeypatch.setattr(alfred, "_llm_synthesize", huge)

    out = await alfred._render_briefing(dict(DATA))
    assert "x" * 5000 not in out
    _assert_all_sections(out)


# --- size limits -----------------------------------------------------------

def test_trim_to_limit_marks_the_cut_at_a_boundary():
    text = "First sentence here. Second sentence here. Third sentence here."
    out = alfred._trim_to_limit(text, 45)
    assert len(out) <= 45
    assert out.endswith("…")
    assert out.startswith("First sentence here.")
    # cut on a sentence boundary, not mid-word
    assert not out[:-1].rstrip().endswith("Seco")


def test_trim_to_limit_leaves_short_text_alone():
    assert alfred._trim_to_limit("short", 100) == "short"


def test_embed_fields_respect_discord_limits():
    sections = {k: ("line %d of a very long section.\n" % i) * 200
                for i, k in enumerate(alfred._SECTION_KEYS)}
    embed = alfred._build_briefing_embed(sections, "top story", "⚠️ 2 levels hidden as out-of-range.")

    assert len(embed["fields"]) == len(alfred._SECTION_KEYS)
    for field in embed["fields"]:
        assert len(field["value"]) <= 1024
        assert field["value"].endswith("…")      # visible marker, nothing silently lost
    total = (len(embed["title"]) + len(embed["description"])
             + len(embed["footer"]["text"])
             + sum(len(f["name"]) + len(f["value"]) for f in embed["fields"]))
    assert total <= 6000


def test_embed_shows_placeholder_for_empty_section():
    embed = alfred._build_briefing_embed({k: "" for k in alfred._SECTION_KEYS}, "", "")
    values = [f["value"] for f in embed["fields"]]
    assert "_Nothing overnight._" in values
    assert all(v.strip() for v in values)
    _assert_no_exchange_timezone(json.dumps(embed))


def test_sections_round_trip_through_the_archived_text():
    text = alfred._sections_to_text(
        {"overnight": "a", "levels": "b", "calls": "c", "macro": "d", "top_tickers": "e"},
        "the story",
    ) + "⚠️ 1 level hidden as out-of-range.\n"
    sections, top_story, footnote = alfred._sections_from_text(text)
    assert sections["overnight"] == "a"
    assert sections["top_tickers"] == "e"
    assert top_story == "the story"
    assert footnote.startswith("⚠️")


# --- SPY expected-move payload --------------------------------------------

class _FakeEM:
    """Minimal stand-in for ExpectedMoveResult (only what the card reads)."""
    def __init__(self, horizon="daily"):
        self.ticker = "SPY"
        self.horizon = horizon
        self.spot = 631.20
        self.primary_em = 4.21
        self.upper = 635.41
        self.lower = 626.99
        self.expiration = "2026-08-18"
        self.em = {"raw_straddle_em_pct": 0.0067}


BRIEF_TEXT = alfred._sections_to_text(
    {"overnight": "a", "levels": "SPY 630", "calls": "c", "macro": "d", "top_tickers": "e"}, "")


async def _payload(monkeypatch, table):
    async def fake_em(horizon):
        return table.get(horizon, (None, None))
    monkeypatch.setattr(alfred, "_spy_expected_move", fake_em)
    return await alfred._build_briefing_payload(BRIEF_TEXT)


async def test_payload_attaches_both_charts(monkeypatch):
    embeds, files, meta = await _payload(monkeypatch, {
        "daily": (_FakeEM("daily"), b"png-a"),
        "weekly": (_FakeEM("weekly"), b"png-b"),
    })
    assert [name for name, _ in files] == [alfred.SPY_EM_DAILY_FILE, alfred.SPY_EM_WEEKLY_FILE]
    assert embeds[0]["image"]["url"] == f"attachment://{alfred.SPY_EM_DAILY_FILE}"
    assert embeds[1]["image"]["url"] == f"attachment://{alfred.SPY_EM_WEEKLY_FILE}"
    assert json.loads(meta)["daily"]["chart"] is True
    levels = [f["value"] for f in embeds[0]["fields"]
              if f["name"] == alfred._SECTION_TITLES["levels"]][0]
    assert "631.20" in levels


async def test_payload_posts_without_charts_when_render_returns_none(monkeypatch):
    embeds, files, meta = await _payload(monkeypatch, {
        "daily": (_FakeEM("daily"), None), "weekly": (_FakeEM("weekly"), None),
    })
    assert files == []
    assert "image" not in embeds[0]
    assert json.loads(meta)["daily"]["chart"] is False
    _assert_all_sections("\n".join(f"### {f['name']}" for f in embeds[0]["fields"]))


async def test_payload_survives_daily_expected_move_failure(monkeypatch):
    embeds, files, meta = await _payload(monkeypatch, {
        "daily": (None, None), "weekly": (_FakeEM("weekly"), b"png-b"),
    })
    assert json.loads(meta)["daily"] == {"error": "unavailable"}
    assert len(embeds[0]["fields"]) == len(alfred._SECTION_KEYS)
    assert [name for name, _ in files] == [alfred.SPY_EM_WEEKLY_FILE]


async def test_payload_survives_weekly_expected_move_failure(monkeypatch):
    embeds, files, meta = await _payload(monkeypatch, {
        "daily": (_FakeEM("daily"), b"png-a"), "weekly": (None, None),
    })
    assert json.loads(meta)["weekly"] == {"error": "unavailable"}
    assert len(embeds) == 1
    assert [name for name, _ in files] == [alfred.SPY_EM_DAILY_FILE]


async def test_spy_expected_move_never_raises(monkeypatch):
    from consensus_engine.scanners import expected_move as em_mod

    async def boom(ticker, executor=None, horizon="daily"):
        raise em_mod.EMUnavailable("no usable quotes")
    monkeypatch.setattr(em_mod, "compute_em", boom)
    assert await alfred._spy_expected_move("daily") == (None, None)


def test_section_headings_survive_drift():
    """A pending brief reparsed after the headings change must NOT come back empty.

    The archived corpus carries a dozen spellings of these five headings; matching
    on the exact decorated title returned an empty card for all 79 of them.
    """
    for heading, expected in [
        ("Overnight", "overnight"),
        ("🌙  Overnight", "overnight"),
        ("Overnight Highlights", "overnight"),
        ("Levels to Watch (SPY)", "levels"),
        ("📊 Levels to Watch", "levels"),
        ("High-Conviction Calls", "calls"),
        ("High‑Conviction Analyst Calls", "calls"),
        ("Macro Pulse", "macro"),
        ("🔝 Top Tickers (quick glance)", "top_tickers"),
    ]:
        assert alfred._section_key_for_heading(heading) == expected, heading
    for heading in ("Something Else", "Risk", "", "###"):
        assert alfred._section_key_for_heading(heading) is None, heading


def test_undecorated_headings_still_parse_into_all_five_sections():
    content = (
        "## Morning Brief\n\n"
        "### Overnight\nalpha\n\n"
        "### Levels to Watch\nbravo\n\n"
        "### High-Conviction Analyst Calls\ncharlie\n\n"
        "### Macro Pulse\ndelta\n\n"
        "### Top Tickers to Watch\necho\n"
    )
    sections, _top, _foot = alfred._sections_from_text(content)
    assert sections == {"overnight": "alpha", "levels": "bravo", "calls": "charlie",
                        "macro": "delta", "top_tickers": "echo"}
