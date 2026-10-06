"""Owner report 2026-10-06: the analysis must match a Gemini note: news catalysts, a week / month /
year outlook, and a reason for every trade-plan level. Levels come from data; the note's figures too."""
from datetime import date, timedelta

import pandas as pd

from member_dashboard import trade_map
from member_dashboard.analysis_collector import check_note


def candles(n=260):
    """A rising year with pullbacks: a swing high every 20 days, then a dip."""
    rows, start = [], date(2025, 9, 1)
    for i in range(n):
        base = 100 + i * 0.3 + (6 if i % 20 == 10 else 3 if i % 20 in (9, 11) else 0)
        rows.append({'date': (start + timedelta(days=i)).isoformat(), 'open': base - 0.5, 'high': base + 1,
                     'low': base - 1, 'close': base, 'volume': 1_000_000 + (500_000 if 150 <= i < 170 else 0)})
    return rows


def frames(spot):
    strikes = [spot * k for k in (0.9, 0.95, 1.0, 1.05, 1.1)]
    calls = pd.DataFrame({'strike': strikes, 'openInterest': [10, 20, 30, 900, 40], 'impliedVolatility': 0.4, 'expiry': '2026-05-22'})
    puts = pd.DataFrame({'strike': strikes, 'openInterest': [50, 700, 30, 20, 10], 'impliedVolatility': 0.4, 'expiry': '2026-05-22'})
    return {'call': [calls], 'put': [puts], 'expirations': ['2026-05-22']}


def test_plan_levels_come_from_the_chart_and_say_why():
    rows = candles()
    spot = rows[-1]['close']
    average = trade_map.atr(rows)
    f = frames(spot)
    walls = trade_map.walls(f, spot)
    assert [(w['side'], w['rank']) for w in walls][:1] == [('call', 0)] and walls[0]['strike'] > spot
    ranges = {'week': trade_map.implied_range(f, spot, 7, date(2026, 5, 15)), 'month': None}
    assert ranges['week']['until'] == 'May 22' and ranges['week']['low'] < spot < ranges['week']['high']
    levels = trade_map.levels(rows, spot, average, walls, ranges)
    plan = trade_map.plan(levels, spot, average, 'BULLISH')
    assert plan['stop'] < plan['entry_low'] <= plan['entry_high'] <= spot
    prices = [t['price'] for t in plan['targets']]
    assert prices == sorted(prices) and prices[0] > spot and len(prices) == 3
    assert all(t['why'] for t in plan['targets']) and plan['entry_why'] and plan['stop_why']
    assert any('open call contracts' in t['why'] for t in plan['targets'])  # The call wall is a target.
    short = trade_map.plan(levels, spot, average, 'BEARISH')
    assert short['side'] == 'short' and short['stop'] > short['entry_high'] and short['targets'][0]['price'] < spot
    assert trade_map.plan(levels, spot, average, 'NEUTRAL') is None
    kinds = {row['kind'] for row in trade_map.key_levels(levels, spot)}
    assert kinds <= {'support', 'resistance'} and kinds


def test_close_levels_merge_without_chaining():
    """MU 2026-10-06: $10 round numbers chained $840-$1,180 into one level. Merging joins the strongest only."""
    rows = candles()
    spot = rows[-1]['close']
    levels = trade_map.levels(rows, spot, trade_map.atr(rows), [], {})
    span = max(level.price for level in levels) - min(level.price for level in levels)
    assert len(levels) > 5 and span > spot * 0.2


FACTS = {'ticker': 'NVDA', 'price': 239.24, 'signal': {'direction': 'bullish', 'confidence': 'low'},
         'trade_plan': {'entry_low': 236.54, 'entry_high': 239.24, 'stop': 229.13, 'targets': [{'price': 250.0, 'why': ''}]},
         'options': {'next_week_range': {'low': 231.75, 'high': 246.73}},
         'news': [{'title': 'Nvidia nears $6 trillion', 'summary': 'BNP Paribas raised its target to $345.'}]}
NOTE = ('**TL;DR:** Bullish, low confidence, as Nvidia nears $6 trillion.\n\n## Catalysts\n- **Target (Oct 5):** BNP raised its target to $345.\n'
        '- **Made up (Oct 5):** Sales jumped 41%.\n\n## Outlook\n- **Next week:** $231.75 to $246.73.\n\n## Risk Considerations\n'
        '- A failed $229.13 stop.\n- China export limits.')


def test_note_figures_must_come_from_the_facts():
    problems, cleaned = check_note(NOTE, FACTS)
    assert any('41' in p for p in problems) and any('trade-plan price' in p for p in problems)
    assert 'Sales jumped' not in cleaned and '$229.13' not in cleaned and '$345' in cleaned and 'China' in cleaned
    problems, _ = check_note(NOTE.replace('Bullish', 'Bearish'), FACTS)
    assert any('calls it bearish' in p for p in problems)
    problems, cleaned = check_note(NOTE.replace('nears $6 trillion', 'is worth $9 trillion'), FACTS)
    assert cleaned == ''  # A wrong figure in the TL;DR rejects the draft.
    assert check_note('## Catalysts\n- x', FACTS)[0][0] == 'missing **TL;DR:**'


def test_bing_news_gives_the_publisher_link_and_summary():
    from member_dashboard.news import Headline, about, parse_bing, short_name
    xml = ('<rss xmlns:News="https://www.bing.com/news/search?q=x"><channel><item><title>Micron settles Netlist dispute</title>'
           '<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;url=https%3a%2f%2fwww.reuters.com%2fa%3fmod%3drss&amp;c=1</link>'
           '<description>Micron will pay $600 million.</description><pubDate>Tue, 06 Oct 2026 12:00:00 GMT</pubDate>'
           '<News:Source>Reuters on MSN</News:Source></item></channel></rss>')
    from datetime import datetime, timezone
    rows = parse_bing(xml, now=datetime(2026, 10, 6, 13, tzinfo=timezone.utc).timestamp())
    assert [(r.url, r.source, r.summary) for r in rows] == [('https://www.reuters.com/a', 'Reuters', 'Micron will pay $600 million.')]
    assert short_name('Micron Technology, Inc. Common Stock') == 'Micron Technology'
    assert about(rows[0], 'MU', 'Micron Technology')  # "Micron" alone matches the company.
    assert not about(Headline('Advanced chips rally', 'X', 0, 'https://a.com'), 'AMD', 'Advanced Micro Devices')


def test_wall_street_view_parses_nasdaq_data():
    from member_dashboard.street import parse
    s = parse({'data': {'companyName': 'NVIDIA Corporation Common Stock'}},
              {'data': {'consensusOverview': {'lowPriceTarget': 275.0, 'highPriceTarget': '465.00', 'priceTarget': 325.03, 'buy': 32, 'sell': 0, 'hold': 0}}},
              {'data': {'reportText': 'is estimated to report earnings on  11/18/2026. The upcoming'}})
    assert (s.target_average, s.target_high, s.buy, s.earnings_date) == (325.03, 465.0, 32, '2026-11-18')
    assert parse(None, None, None).target_average is None
