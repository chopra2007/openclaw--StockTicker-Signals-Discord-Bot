"""A quote delay must not consume the following gap-fill stage's own budget."""
from datetime import date
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize('quote_seconds, expected_budget', [(25.0, 20.0), (155.0, 5.0)])
async def test_gap_budget_starts_after_quote_and_respects_overall_budget(
    monkeypatch, quote_seconds, expected_budget,
):
    from consensus_engine.alerts.all_command import aggregator
    from consensus_engine.analysis import level_display_sanity
    from consensus_engine.analysis.research_compute import research_calculation
    from consensus_engine.analysis.research_contracts import CalculationSettings
    from consensus_engine.models import ScoreBreakdown

    current = [1000.0]
    monkeypatch.setattr(aggregator, 'time', SimpleNamespace(
        time=lambda: current[0], monotonic=lambda: current[0] - 1000.0))
    monkeypatch.setattr(aggregator, '_remaining', lambda start: 160.0 - (current[0] - 1000.0))

    async def delayed_quote(ticker, rows):
        current[0] += quote_seconds
        return rows, 0

    async def capture_gap(**kwargs):
        return {'usable_budget': max(0.0, kwargs['deadline'] - current[0])}

    monkeypatch.setattr(level_display_sanity, 'filter_levels_for_display', delayed_quote)
    monkeypatch.setattr(aggregator.gap_fill, 'run_gap_fill', capture_gap)
    data = {'score': SimpleNamespace(breakdown=ScoreBreakdown()), 'yt_levels': [],
            'technical_long': None, 'technical_short': None, 'news_catalyst': None,
            'options_unusual': None, 'decision_snapshots': [], 'daily_candles': [],
            'sec_filings': []}
    calculation = research_calculation(
        'NVDA', data, settings=CalculationSettings(), epoch=current[0],
        today=date(2026, 10, 5), start=0.0,
        remaining=lambda: aggregator._remaining(0.0), telemetry=lambda event: None)
    request = next(calculation)
    assert request.kind == 'sane_levels'
    response = await aggregator._collect_research_request(request, 'NVDA', data, 0.0, {})
    while True:
        request = calculation.send(response)
        if request.kind == 'gap_fill':
            result = await aggregator._collect_research_request(request, 'NVDA', data, 0.0, {})
            assert result['usable_budget'] == expected_budget
            break
        assert request.kind in {'direction_parity', 'stage'}
        response = None
