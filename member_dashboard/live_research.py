"""One live look at a ticker for the assistant: the Custom Stock Analysis facts (price, signal,
trade plan with reasons, key levels, option ranges, Wall Street targets, news, analyst calls).

Owner report 2026-10-06: asking "is NVDA a buy?" answered "Market Assistant is unavailable"
because the assistant could only start a report, never read data in the same answer. This runs
the same study as the analysis section (no AI write-up) right away.
"""
import dataclasses


async def snapshot(collector, ticker):
    """Returns (content, evidence): the analysis facts without the write-up. Evidence ids are
    prefixed with the ticker so two looks never clash."""
    study = await collector.study(ticker)
    evidence = [dataclasses.replace(row, id=f'{ticker}-{row.id}') for row in study.evidence]
    if study.facts is None:
        return {'ticker': ticker, 'unavailable': 'Price data is not available right now.'}, evidence
    content = dict(study.facts)
    content['news'] = [{'id': f'{ticker}-news-{index}', **row} for index, row in enumerate(content['news'])]
    calls = [row for row in evidence if '-analyst-' in row.id]
    content['analyst_calls'] = [{'id': row.id, **call} for row, call in zip(calls, content['analyst_calls'])]
    return content, evidence
