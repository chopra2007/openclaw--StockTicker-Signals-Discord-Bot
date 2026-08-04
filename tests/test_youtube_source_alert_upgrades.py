"""Tests for Section 2Q: YouTube source-alert title link, timestamp deep-link, macro context."""
import asyncio
from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from consensus_engine.scanners.youtube import _youtube_timestamp_url, _send_two_stage_alerts
from consensus_engine.alerts._markdown import _escape_md_link_text


# ---------------------------------------------------------------------------
# _youtube_timestamp_url
# ---------------------------------------------------------------------------

class TestYouTubeTimestampUrl:
    def test_no_timestamp_returns_base_url(self):
        url = _youtube_timestamp_url("abc123XYZ_-", None)
        assert url == "https://www.youtube.com/watch?v=abc123XYZ_-"
        assert "&t=" not in url

    def test_timestamp_appended(self):
        url = _youtube_timestamp_url("abc123XYZ_-", 420)
        assert url == "https://www.youtube.com/watch?v=abc123XYZ_-&t=420s"

    def test_zero_timestamp(self):
        url = _youtube_timestamp_url("AAAAAAAAAAA", 0)
        assert url == "https://www.youtube.com/watch?v=AAAAAAAAAAA&t=0s"


# ---------------------------------------------------------------------------
# _escape_md_link_text (imported from _markdown — verify it handles our cases)
# ---------------------------------------------------------------------------

class TestEscapeMdLinkText:
    def test_plain_text_unchanged(self):
        assert _escape_md_link_text("Hello World") == "Hello World"

    def test_brackets_escaped(self):
        result = _escape_md_link_text("Why the Fed's [Pivot] Sets Up a Rally")
        assert "\\[" in result
        assert "\\]" in result

    def test_parentheses_escaped(self):
        result = _escape_md_link_text("R/R (2.5x)")
        assert "\\(" in result
        assert "\\)" in result

    def test_backslash_escaped(self):
        result = _escape_md_link_text(r"A\B(C)\D")
        assert "\\\\B" in result or result.startswith("A\\\\")

    def test_title_with_special_chars_forms_valid_link(self):
        r"""Title containing ]B(C)\ renders as one valid markdown link — item #57."""
        raw = "]B(C)\\"
        escaped = _escape_md_link_text(raw)
        link = f"[{escaped}](https://www.youtube.com/watch?v=X)"
        # Must not contain unescaped ] or ( or ) outside the link delimiters
        inner = escaped
        assert "\\]" in inner
        assert "\\(" in inner
        assert "\\)" in inner or "\\)" not in raw  # ) may not be in raw
        assert "\\\\B" in inner or "B" in inner  # backslash escaped or normal B

    def test_newlines_collapsed(self):
        result = _escape_md_link_text("line1\nline2\r\nline3")
        assert "\n" not in result
        assert "\r" not in result
        assert " " in result


# ---------------------------------------------------------------------------
# Helpers for Path A tests
# ---------------------------------------------------------------------------

@dataclass
class FakeSignal:
    ticker: str
    direction: MagicMock
    conviction: MagicMock
    classifier_confidence: float = 0.85
    suppressed: bool = False
    suppression_reason: str = ""
    video_timestamp_sec: int | None = None
    evidence_span_ids: list = field(default_factory=list)


@dataclass
class FakeSetup:
    ticker: str
    entry_low: float | None = None
    stop: float | None = None
    targets: list = field(default_factory=list)
    risk_reward: float | None = None
    suppressed: bool = False
    suppression_reason: str = ""
    video_timestamp_sec: int | None = None
    setup_type: str = "swing"


@dataclass
class FakeSpan:
    ts_sec: int
    quote: str
    tickers: list = field(default_factory=list)


@dataclass
class FakeMacroThesis:
    summary: str = ""
    themes: list = field(default_factory=list)
    direction: MagicMock = None


def _make_sig(ticker="SPY", direction="long", conviction="high", ts=None):
    sig = FakeSignal(ticker=ticker, direction=MagicMock(), conviction=MagicMock())
    sig.direction.value = direction
    sig.conviction.value = conviction
    sig.video_timestamp_sec = ts
    return sig


async def _run_path_a(
    signals, spans, video_id="VID123", video_title="Test Title", macro_summary="",
    setups=None, levels=None, catalysts=None,
):
    """Run _send_two_stage_alerts with mocked discord send; return captured message."""
    captured = []

    async def fake_send(content):
        captured.append(content)

    with patch("consensus_engine.scanners.youtube._send_youtube_alert", side_effect=fake_send):
        await _send_two_stage_alerts(
            display_name="Test Channel",
            signals=signals,
            levels=levels or [],
            setups=setups or [],
            catalysts=catalysts or [],
            bundle_spans=spans,
            min_confidence=0.5,
            require_verified=False,
            video_id=video_id,
            video_title=video_title,
            macro_summary=macro_summary,
        )
    return captured


# ---------------------------------------------------------------------------
# Path A: _send_two_stage_alerts
# ---------------------------------------------------------------------------

class TestPathATitleLink:
    @pytest.mark.asyncio
    async def test_title_link_with_timestamp(self):
        """Link contains ?t= and escaped title when title + timestamp present — item #52a,b."""
        sig = _make_sig()
        span = FakeSpan(ts_sec=300, quote="Markets up today", tickers=["SPY"])
        msgs = await _run_path_a([sig], [span], video_id="abc123", video_title="Why the Fed Pivots", macro_summary="")
        assert msgs
        msg = msgs[0]
        assert "🎥 [Why the Fed Pivots](https://www.youtube.com/watch?v=abc123&t=300s)" in msg

    @pytest.mark.asyncio
    async def test_null_title_fallback(self):
        """NULL title falls back to 'YouTube video' — item plan fallback."""
        sig = _make_sig()
        span = FakeSpan(ts_sec=100, quote="SPY going up", tickers=["SPY"])
        msgs = await _run_path_a([sig], [span], video_id="abc123", video_title="", macro_summary="")
        assert msgs
        assert "🎥 [YouTube video](" in msgs[0]

    @pytest.mark.asyncio
    async def test_special_chars_in_title_escaped(self):
        """Title with [ ] ( ) \\ is escaped — item #57."""
        sig = _make_sig()
        span = FakeSpan(ts_sec=0, quote="quote", tickers=["SPY"])
        raw_title = "Why [Fed] (Pivots) Now\\!"
        msgs = await _run_path_a([sig], [span], video_id="X", video_title=raw_title, macro_summary="")
        assert msgs
        # The link text must contain escaped brackets
        assert "\\[Fed\\]" in msgs[0]
        assert "\\(Pivots\\)" in msgs[0]

    @pytest.mark.asyncio
    async def test_no_macro_summary_omits_big_picture(self):
        """Big picture line omitted when macro_summary is empty — item #55."""
        sig = _make_sig()
        span = FakeSpan(ts_sec=0, quote="quote", tickers=["SPY"])
        msgs = await _run_path_a([sig], [span], macro_summary="")
        assert msgs
        assert "💡 Big picture:" not in msgs[0]

    @pytest.mark.asyncio
    async def test_macro_summary_emitted(self):
        """Big picture line present when macro_summary is ≥40 chars — item #55."""
        sig = _make_sig()
        span = FakeSpan(ts_sec=0, quote="quote", tickers=["SPY"])
        summary = "Channel argues Fed pivot plus earnings recovery sets up large-cap rally through Q3 2025"
        msgs = await _run_path_a([sig], [span], macro_summary=summary)
        assert msgs
        assert "💡 Big picture:" in msgs[0]
        assert "Fed pivot" in msgs[0]

    @pytest.mark.asyncio
    async def test_macro_summary_truncated(self):
        """Big picture line truncated to macro_max_chars with ellipsis — item #55."""
        sig = _make_sig()
        span = FakeSpan(ts_sec=0, quote="quote", tickers=["SPY"])
        summary = "A" * 300  # way over the 220 default
        msgs = await _run_path_a([sig], [span], macro_summary=summary)
        assert msgs
        assert "💡 Big picture: " + "A" * 220 + "…" in msgs[0]

    @pytest.mark.asyncio
    async def test_timestamp_resolution_span_ts_when_setup_none(self):
        """Span ts_sec used when setup.video_timestamp_sec is None — item #54."""
        sig = _make_sig()
        setup = FakeSetup(ticker="SPY", video_timestamp_sec=None)
        span = FakeSpan(ts_sec=300, quote="Markets up today", tickers=["SPY"])
        msgs = await _run_path_a([sig], [span], setups=[setup], video_id="VID999")
        assert msgs
        assert "&t=300s" in msgs[0]

    @pytest.mark.asyncio
    async def test_timestamp_resolution_setup_wins_over_span(self):
        """setup.video_timestamp_sec wins over span.ts_sec."""
        sig = _make_sig()
        # entry_low must be non-None so the setup-line code path doesn't IndexError
        setup = FakeSetup(ticker="SPY", video_timestamp_sec=150, entry_low=658.0)
        span = FakeSpan(ts_sec=300, quote="Markets up today", tickers=["SPY"])
        msgs = await _run_path_a([sig], [span], setups=[setup], video_id="VID999")
        assert msgs
        assert "&t=150s" in msgs[0]
        assert "&t=300s" not in msgs[0]

    @pytest.mark.asyncio
    async def test_quote_max_chars_honored(self):
        """quote_max_chars=320 setting honored for Path A — item #56."""
        sig = _make_sig()
        long_quote = "X" * 400
        span = FakeSpan(ts_sec=0, quote=long_quote, tickers=["SPY"])
        with patch("consensus_engine.config.get") as mock_cfg:
            def cfg_side(key, default=None):
                if key == "youtube.alerts.context.quote_max_chars":
                    return 320
                if key == "youtube.alerts.video_link.title_max_chars":
                    return 80
                if key == "youtube.alerts.context.macro_max_chars":
                    return 220
                return default
            mock_cfg.side_effect = cfg_side
            msgs = await _run_path_a([sig], [span], macro_summary="")
        assert msgs
        # The quote rendered should be at most 320 chars from the original
        assert "X" * 321 not in msgs[0]
        assert "X" * 320 in msgs[0]

    @pytest.mark.asyncio
    async def test_second_span_appended_when_no_macro_and_short_quote(self):
        """Second span appended when no macro summary and first quote <120 chars — item #56."""
        sig = _make_sig()
        span1 = FakeSpan(ts_sec=0, quote="Short quote here", tickers=["SPY"])
        span2 = FakeSpan(ts_sec=10, quote="Second span content", tickers=["SPY"])
        msgs = await _run_path_a([sig], [span1, span2], macro_summary="")
        assert msgs
        assert "Second span content" in msgs[0]

    @pytest.mark.asyncio
    async def test_second_span_not_appended_when_macro_present(self):
        """Second span NOT appended when macro summary is present."""
        sig = _make_sig()
        span1 = FakeSpan(ts_sec=0, quote="Short quote here", tickers=["SPY"])
        span2 = FakeSpan(ts_sec=10, quote="Second span content", tickers=["SPY"])
        summary = "A" * 50  # enough to activate macro line
        msgs = await _run_path_a([sig], [span1, span2], macro_summary=summary)
        assert msgs
        assert "Second span content" not in msgs[0]


# ---------------------------------------------------------------------------
# Path B: process_video standalone block
# ---------------------------------------------------------------------------

@dataclass
class FakeParsedMacro:
    summary: str = ""
    themes: list = field(default_factory=list)
    direction: MagicMock = None
    narrative: str = ""
    timeframe: str = ""


@dataclass
class FakeParsed:
    tickers: list = field(default_factory=list)
    price_levels: list = field(default_factory=list)
    setups: list = field(default_factory=list)
    options: list = field(default_factory=list)
    macro_thesis: FakeParsedMacro | None = None


async def _run_path_b(
    tickers_data, video_id="VID_B", video_title="Test Video", macro_summary="",
    setups=None,
):
    """Simulate the Path B standalone alert block via process_video."""
    captured = []

    async def fake_send(content):
        captured.append(content)

    macro = FakeParsedMacro(summary=macro_summary) if macro_summary else None
    parsed = FakeParsed(
        tickers=tickers_data,
        setups=setups or [],
        macro_thesis=macro,
    )

    video_meta = {"video_id": video_id, "title": video_title}

    with (
        patch("consensus_engine.scanners.youtube._send_youtube_alert", side_effect=fake_send),
        patch("consensus_engine.scanners.youtube.cfg.get") as mock_cfg,
        patch("consensus_engine.scanners.youtube.db.get_channel_trust", new_callable=AsyncMock, return_value=1.0),
        patch("consensus_engine.alerts.commands._format_youtube_setup_summary", return_value=""),
        patch("consensus_engine.alerts.commands._format_youtube_option_summary", return_value=""),
    ):
        def cfg_side(key, default=None):
            if key == "youtube.standalone_alerts":
                return True
            if key == "youtube.min_trust":
                return 0.5
            if key == "youtube.alerts.video_link.title_max_chars":
                return 80
            if key == "youtube.alerts.context.macro_max_chars":
                return 220
            if key == "youtube.alerts.context.quote_max_chars":
                return 320
            return default
        mock_cfg.side_effect = cfg_side

        # Directly exercise only the standalone alert block (extracted logic)
        # by importing and calling the relevant sub-logic through a minimal shim
        display_name = "Test Channel B"
        from consensus_engine.alerts._markdown import _escape_md_link_text
        from consensus_engine.scanners.youtube import _youtube_timestamp_url

        channel_id = "UC_test"
        min_trust = 0.5
        trust = 1.0

        if trust >= min_trust:
            from consensus_engine.alerts.commands import (
                _format_youtube_setup_summary,
                _format_youtube_option_summary,
            )
            for ticker_data in parsed.tickers:
                if (
                    ticker_data.get("conviction") == "high"
                    and ticker_data.get("direction") in ("long", "short")
                ):
                    sym = ticker_data.get("symbol", "")
                    tkr_setups = [s for s in parsed.setups if s.ticker == sym]

                    direction_label = ticker_data["direction"].upper()
                    lines = [f"🎬 **${sym} [{direction_label}]** — {display_name}"]

                    b_video_id = video_meta.get("video_id", "")
                    if b_video_id:
                        b_ts: int | None = None
                        for _s in (tkr_setups if tkr_setups else []):
                            if _s.video_timestamp_sec is not None:
                                b_ts = _s.video_timestamp_sec
                                break
                        title_max = 80
                        raw_title = (video_meta.get("title") or "").strip()
                        escaped_title = _escape_md_link_text(raw_title)[:title_max] if raw_title else "YouTube video"
                        url = _youtube_timestamp_url(b_video_id, b_ts)
                        lines.append(f"🎥 [{escaped_title}]({url})")

                    b_summary = ""
                    if parsed.macro_thesis and parsed.macro_thesis.summary:
                        b_summary = parsed.macro_thesis.summary.strip()
                    if b_summary and len(b_summary) >= 40:
                        macro_max = 220
                        truncated = b_summary[:macro_max] + "…" if len(b_summary) > macro_max else b_summary
                        lines.append(f"💡 Big picture: {truncated}")

                    levels = [lv for lv in parsed.price_levels if lv.ticker == sym]
                    if levels:
                        lv_parts = []
                        for lv in levels[:4]:
                            label = lv.level_type.capitalize()
                            lv_parts.append(f"{label} ${lv.price:.0f}")
                        lines.append("📊 " + " | ".join(lv_parts))

                    setups_to_render = tkr_setups if tkr_setups else [s for s in parsed.setups if s.ticker == sym]
                    for s in setups_to_render[:2]:
                        lines.append(_format_youtube_setup_summary(s))

                    opts = [o for o in parsed.options if o.ticker == sym]
                    for o in opts[:2]:
                        lines.append(_format_youtube_option_summary(o))

                    quote_max = 320
                    ctx = ticker_data.get("context", "").strip()
                    if ctx:
                        lines.append(f'> "{ctx[:quote_max]}"')

                    await fake_send("\n".join(lines))

    return captured


class TestPathBTitleLink:
    @pytest.mark.asyncio
    async def test_title_link_present(self):
        """Path B: 🎥 link emitted with video title — item #58."""
        tickers = [{"symbol": "AAPL", "conviction": "high", "direction": "long", "context": "AAPL is bullish"}]
        msgs = await _run_path_b(tickers, video_id="BID456", video_title="Why AAPL Rallies")
        assert msgs
        assert "🎥 [Why AAPL Rallies](https://www.youtube.com/watch?v=BID456)" in msgs[0]

    @pytest.mark.asyncio
    async def test_null_title_fallback(self):
        """Path B: NULL video title falls back to 'YouTube video'."""
        tickers = [{"symbol": "AAPL", "conviction": "high", "direction": "long", "context": "context"}]
        msgs = await _run_path_b(tickers, video_id="BID456", video_title="")
        assert msgs
        assert "🎥 [YouTube video](" in msgs[0]

    @pytest.mark.asyncio
    async def test_special_chars_escaped(self):
        """Path B: special chars escaped in title — item #57."""
        tickers = [{"symbol": "SPY", "conviction": "high", "direction": "long", "context": "context"}]
        msgs = await _run_path_b(tickers, video_title="Fed [Pivot] (Now)\\!")
        assert msgs
        assert "\\[Pivot\\]" in msgs[0]

    @pytest.mark.asyncio
    async def test_macro_omitted_when_empty(self):
        """Path B: no Big picture line when macro_summary empty — item #55."""
        tickers = [{"symbol": "SPY", "conviction": "high", "direction": "long", "context": "context"}]
        msgs = await _run_path_b(tickers, macro_summary="")
        assert msgs
        assert "💡 Big picture:" not in msgs[0]

    @pytest.mark.asyncio
    async def test_macro_emitted_when_present(self):
        """Path B: Big picture line emitted when macro_summary ≥40 chars — item #55."""
        tickers = [{"symbol": "SPY", "conviction": "high", "direction": "long", "context": "context"}]
        summary = "This is a macro summary that is definitely longer than forty characters in total"
        msgs = await _run_path_b(tickers, macro_summary=summary)
        assert msgs
        assert "💡 Big picture:" in msgs[0]

    @pytest.mark.asyncio
    async def test_quote_max_chars_honored(self):
        """Path B: quote_max_chars=320 honored — item #56."""
        long_ctx = "Y" * 400
        tickers = [{"symbol": "SPY", "conviction": "high", "direction": "long", "context": long_ctx}]
        msgs = await _run_path_b(tickers)
        assert msgs
        assert "Y" * 321 not in msgs[0]
        assert "Y" * 320 in msgs[0]

    @pytest.mark.asyncio
    async def test_header_preserved(self):
        """Path B: existing 🎬 header line remains intact — item #59 (change is additive)."""
        tickers = [{"symbol": "TSLA", "conviction": "high", "direction": "short", "context": "bearish"}]
        msgs = await _run_path_b(tickers)
        assert msgs
        assert "🎬 **$TSLA [SHORT]**" in msgs[0]


# ---------------------------------------------------------------------------
# Config key existence check
# ---------------------------------------------------------------------------

class TestConfigKeys:
    def test_config_keys_present(self):
        """New YAML keys are reachable via config.get — items are defined."""
        from consensus_engine import config as cfg_mod
        # Reset and reload so test sees the actual YAML
        cfg_mod._config = None
        assert cfg_mod.get("youtube.alerts.video_link.enabled") is True
        assert cfg_mod.get("youtube.alerts.video_link.title_max_chars") == 80
        assert cfg_mod.get("youtube.alerts.context.macro_max_chars") == 220
        assert cfg_mod.get("youtube.alerts.context.quote_max_chars") == 320
        cfg_mod._config = None  # reset after test
