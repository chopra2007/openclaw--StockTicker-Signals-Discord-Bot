"""One live look at a ticker for the assistant: price, signal, trade plan, news, analyst calls.

Owner report 2026-10-06: asking "is NVDA a buy?" answered "Market Assistant is unavailable"
because the assistant could only start a report, never read data in the same answer. This runs
the same calculation as the trade-setup levels (the `!all` math, no AI write-up) right away.
"""
import dataclasses

_DIRECTIONS = {'BULLISH': 'bullish', 'BEARISH': 'bearish', 'NEUTRAL': 'neutral'}


async def _no_write_up(request):
    return ''


def _round(value):
    return round(value, 2) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


async def snapshot(collector, ticker):
    """Returns (content, evidence). Evidence ids are prefixed with the ticker so two looks never clash."""
    from consensus_engine.analysis.research_compute import compute_research
    inputs = await collector(ticker)
    services = dataclasses.replace(collector.services(), synthesis=_no_write_up)
    result = await compute_research(ticker, inputs, services)
    s = result.structured
    evidence = [dataclasses.replace(row, id=f'{ticker}-{row.id}') for row in result.evidence]
    technical = inputs.technical_long.values if inputs.technical_long else {}
    options = inputs.options_unusual.values if inputs.options_unusual else {}
    content = {
        'ticker': ticker,
        'price': _round(s.current_price),
        'day_change_pct': _round(technical.get('price_change_pct')),
        'signal': _DIRECTIONS.get(s.direction, 'neutral'),
        'confidence': (s.confidence_label or '').lower() or None,
        'score': _round(result.score_breakdown.total),
        'trade_plan': {'buy_zone': [_round(s.buy_zone_low), _round(s.buy_zone_high)], 'stop': _round(s.sl),
                       'targets': [v for v in (_round(s.tp1), _round(s.tp2), _round(s.tp3)) if v is not None]},
        'next_event': s.next_catalyst_mechanism,
        'technical_checks': [{'name': f.get('name'), 'passed': f.get('passed')} for f in technical.get('filters', [])][:8],
        'options_put_call': _round(options.get('put_call_ratio')),
        'news': [{'id': row.id, 'headline': row.excerpt} for row in evidence if '-news-' in row.id],
        'analyst_calls': [{'id': row.id, 'text': row.excerpt[:400]} for row in evidence if '-analyst-' in row.id],
    }
    return content, evidence
