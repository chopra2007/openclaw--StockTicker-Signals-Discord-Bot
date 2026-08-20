"""The morning-brief checker must count charts the way Discord stores them.

TODO #88 check 4. On 2026-08-18 this checker reported "charts=0" on cards that
carried two SPY charts. It counted the message's `attachments` list — and Discord
MOVES an uploaded image out of that list once an embed points at it. So the one
automatic check on the feature confidently reported the opposite of the truth.

A checker that reports the wrong number is worse than no checker, so it gets the
same test treatment as a feature: a card that really has charts, a card that
really has none, and the exact shape that produced the false zero.
"""
import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "check_morning_brief_card.py"
_spec = importlib.util.spec_from_file_location("check_morning_brief_card", _SCRIPT)
checker = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(checker)


def _card(embeds, attachments=None):
    return {"id": "999", "embeds": embeds, "attachments": attachments or []}


def _main_embed(title="📋 Morning Brief — Wed Aug 19"):
    return {"title": title, "fields": [{"name": str(i), "value": "x"} for i in range(5)]}


def _chart_embed(name):
    return {"title": name, "image": {"url": "attachment://%s.png" % name}}


def test_charts_in_embeds_are_counted():
    """Two chart embeds -> charts=2."""
    msgs = [_card([_main_embed(), _chart_embed("SPY_daily"), _chart_embed("SPY_weekly")])]
    assert "charts=2" in checker.verdict_for(msgs)


def test_the_exact_shape_that_reported_a_false_zero():
    """The real 2026-08-18 shape: images live in the embeds, and `attachments` is
    EMPTY because Discord moved them. Counting attachments gives 0; the truth is 2."""
    msgs = [_card([_main_embed(), _chart_embed("SPY_daily"), _chart_embed("SPY_weekly")],
                  attachments=[])]
    verdict = checker.verdict_for(msgs)
    assert "charts=0" not in verdict
    assert "charts=2" in verdict


def test_a_card_with_genuinely_no_charts_reports_zero():
    msgs = [_card([_main_embed()])]
    verdict = checker.verdict_for(msgs)
    assert "charts=0" in verdict
    assert "embeds=1" in verdict


def test_no_brief_in_the_channel_is_said_plainly():
    msgs = [{"id": "1", "embeds": [{"title": "something else"}], "attachments": []}]
    assert "no brief card found" in checker.verdict_for(msgs)


def test_five_sections_are_counted_from_the_first_embed():
    msgs = [_card([_main_embed(), _chart_embed("SPY_daily")])]
    assert "sections=5/5" in checker.verdict_for(msgs)


def test_an_eastern_time_label_is_flagged_as_a_bug():
    """PDT only is a hard rule; the checker exists partly to catch a leaked 'ET'."""
    embed = _main_embed()
    embed["fields"][0] = {"name": "Open", "value": "9:30 AM ET"}
    assert "eastern_label=YES — BUG" in checker.verdict_for([_card([embed])])
