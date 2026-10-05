"""Parity expectations recorded from original code, before extraction."""
import importlib.util
import json
from pathlib import Path

import pytest
import dataclasses
from collections.abc import Mapping
from datetime import date


GOLDEN = Path(__file__).parent / 'fixtures/research'
CASES = ('bullish', 'bearish', 'neutral', 'conflicting_sources', 'missing_quote',
         'missing_technical', 'no_catalyst', 'sparse_levels', 'stale_options',
         'sec_partial_failure', 'llm_failure')


def test_reusable_analysis_boundary_exists():
    assert importlib.util.find_spec('consensus_engine.analysis.research_compute'), (
        'The reusable calculation boundary is missing')


def test_reference_fixtures_are_actual_original_outputs():
    for case in CASES:
        value = json.loads((GOLDEN / (case + '.json')).read_text(encoding='utf-8'))
        assert value['case'] == case
        assert value['scoring_output']['_type'] == 'ScoreTickerResult'
        assert value['capture']['render_inputs'][0]['structured']['_type'] == 'StructuredFields'
        assert set(value['payload']) == {'embed', 'vault_md', 'cached_at'}


def clean(value):
    if dataclasses.is_dataclass(value):
        value = vars(value)
    if isinstance(value, Mapping):
        result = {key: clean(item) for key, item in value.items()
                  if key not in {'_type', '_extra_attributes', 'metrics'}}
        if '_extra_attributes' in value:
            result.update(clean(value['_extra_attributes']))
        return result
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    return value


def model_record(value):
    from consensus_engine.analysis.research_contracts import ModelRecord
    if value is None:
        return None
    return ModelRecord(value['_type'], clean(value))


def prepared_case(case):
    from consensus_engine.analysis.research_contracts import (
        CalculationSettings, ResearchClock, ScoreInputs, ConsolidationInput, ResearchInputs,
        SourceStatus, ResearchEvidence,
    )
    raw = json.loads((GOLDEN / (case + '.json')).read_text(encoding='utf-8'))
    scoring, gathered = raw['scoring_inputs_before_call'], raw['gathered_inputs_before_compute']
    settings = CalculationSettings({key: value for key, value in raw['synthetic_config'].items()
                                    if key not in {'database', 'vault'}})
    clock = ResearchClock(1791216000.0, 0.0, date(2026, 10, 5))
    score = ScoreInputs(
        catalyst=model_record(scoring['catalyst']), technical=model_record(scoring['technical']),
        options=model_record(scoring['options']), youtube=model_record(scoring['youtube']),
        sec_hit=scoring['sec_response'][0], sec_summary=scoring['sec_response'][1],
        aligned_analysts=scoring['analyst_groups']['aligned'],
        opposing_analysts=scoring['analyst_groups']['opposing'],
        social_data=scoring['social_data'], llm_score=scoring['llm_score_response'],
        consolidation=ConsolidationInput(**clean(raw['scoring_output']['consolidation_result'])),
    )
    earnings = next((row[key] for row in gathered['decision_snapshots']
                     for key in ('next_earnings', 'earnings_date', 'earnings') if row.get(key)), None)
    inputs = ResearchInputs(
        score=score, technical_long=model_record(gathered['technical_long']),
        technical_short=model_record(gathered['technical_short']),
        news_catalyst=model_record(gathered['news_catalyst']),
        options_unusual=model_record(gathered['options_unusual']),
        youtube_levels=gathered['yt_levels'], daily_candles=gathered['daily_candles'],
        earnings_date=earnings or gathered.get('next_earnings_iso'),
        company_name=gathered['company_name'], sanity_quote=None if case == 'missing_quote' else 100.0,
        source_statuses=(SourceStatus('synthetic-public', 'v1', 'completed', clock.epoch),),
        evidence=(ResearchEvidence('record-1', 'synthetic-public', 'v1', clock.epoch,
                                   None, 'Synthetic approved market evidence'),),
    )
    return raw, inputs, settings, clock


@pytest.mark.parametrize('case', CASES)
def test_score_matches_original_capture(case):
    from consensus_engine.analysis.research_compute import compute_score
    raw, inputs, settings, clock = prepared_case(case)
    result = compute_score('NVDA', inputs.score, settings, clock)
    assert clean(result) == clean(raw['scoring_output'])


@pytest.mark.parametrize('case', CASES)
async def test_fields_and_levels_match_original_capture(case):
    from consensus_engine.analysis.research_compute import compute_research
    from consensus_engine.analysis.research_contracts import ResearchServices, GapFillResult
    raw, inputs, settings, clock = prepared_case(case)
    requests, events = [], []

    async def gap_fill(request):
        requests.append(request)
        return GapFillResult()

    async def synthesis(request):
        assert 'Synthetic private bot' not in repr(request)
        return ''

    frozen_before = clean(inputs)
    result = await compute_research('NVDA', inputs, ResearchServices(settings, clock, synthesis, gap_fill, events.append))
    assert clean(inputs) == frozen_before
    expected = raw['capture']['render_inputs'][0]
    assert clean(result.structured) == clean(expected['structured'])
    assert clean(result.score_breakdown) == clean(expected['score_breakdown'])
    assert clean(result.trade_plan) == clean(raw['capture']['trade_plans'][-1])
    assert result.evidence == inputs.evidence
    expected_gap = raw['capture']['gap_requests'][0]
    assert requests[0].anchors_count == expected_gap['anchors_count']
    assert requests[0].direction == expected_gap['direction']
    again = await compute_research('NVDA', inputs, ResearchServices(settings, clock, synthesis, gap_fill, events.append))
    assert clean(inputs) == frozen_before
    assert clean(again.structured) == clean(result.structured)


async def test_synthesis_uses_original_ten_second_budget_gate():
    from consensus_engine.analysis.research_compute import compute_research
    from consensus_engine.analysis.research_contracts import ResearchServices, GapFillResult
    _, inputs, settings, clock = prepared_case('bullish')
    calls = []
    async def gap(request): return GapFillResult()
    async def synthesis(request):
        calls.append(request)
        return ''
    await compute_research('NVDA', inputs, ResearchServices(
        settings, clock, synthesis, gap, lambda event: None, deadline_seconds=12.0))
    assert len(calls) == 1


def test_member_records_reject_opaque_or_private_slots_and_own_nested_values():
    from consensus_engine.analysis.research_contracts import ModelRecord, ScoreInputs, ResearchInputs
    with pytest.raises(TypeError):
        ResearchInputs(prior_vault='private')
    with pytest.raises(TypeError):
        ScoreInputs(technical=object())
    with pytest.raises(TypeError):
        ScoreInputs(social_data={'db': object()})
    with pytest.raises(ValueError):
        ModelRecord('TechnicalResult', {'ticker': 'SPY', 'private_context': 'private'})
    original = {'ticker': 'SPY', 'filters': [], 'price': 100.0}
    record = ModelRecord('TechnicalResult', original)
    original['price'] = 1.0
    assert record.values['price'] == 100.0
    with pytest.raises(TypeError):
        record.values['price'] = 2.0


def test_score_requests_preserve_skip_and_consolidation_order():
    from consensus_engine.analysis.research_compute import score_calculation
    from consensus_engine.analysis.research_contracts import CalculationSettings, ConsolidationInput, ScoreRequest
    from types import SimpleNamespace
    from consensus_engine.models import TechnicalResult
    inputs = SimpleNamespace(catalyst=None, sec_hit=False, sec_summary='', social_data={},
                             technical=TechnicalResult('SPY'), analyst_groups={'aligned': [], 'opposing': []},
                             options=None, youtube=None)
    settings = CalculationSettings({'scoring': {'skip_llm_below_threshold': True}})
    calculation = score_calculation('SPY', inputs, settings=settings, now=1791216000)
    assert calculation.send(None).kind == 'consolidation'
    with pytest.raises(StopIteration) as completed:
        calculation.send(ConsolidationInput())
    assert completed.value.value.breakdown.llm_boost == 0
    calculation = score_calculation('SPY', inputs, settings=CalculationSettings({}), now=1791216000)
    assert calculation.send(None).kind == 'llm_score'
    assert calculation.send((50, 'synthetic')).kind == 'consolidation'
    with pytest.raises(ValueError):
        ScoreRequest('database')


def test_gap_fill_requires_source_provenance():
    from consensus_engine.analysis.research_contracts import GapFillResult
    with pytest.raises(ValueError, match='provenance'):
        GapFillResult(catalyst_research_snippets=('An unattributed catalyst',))
def test_task6_pure_calculator_exists():
    from pathlib import Path
    source = Path('consensus_engine/scanners/expected_move.py').read_text(encoding='utf-8')
    assert 'def compute_em_from_bundle(' in source, 'Pure expected-move boundary is missing'


def test_task6_options_selection_exists():
    from importlib.util import find_spec
    assert find_spec('consensus_engine.analysis.options_presentation'), 'Shared options selection is missing'


def test_task6_dashboard_adapter_exists():
    from importlib.util import find_spec
    assert find_spec('member_dashboard.research'), 'Approved collection adapter is missing'


def _task6_decode(value):
    from datetime import datetime
    import pandas as pd
    if isinstance(value, list): return [_task6_decode(v) for v in value]
    if not isinstance(value, dict): return value
    if '_nonfinite' in value: return float(value['_nonfinite'])
    if value.get('_type') == 'DataFrame':
        result = pd.DataFrame(_task6_decode(value['records']), columns=value['columns'])
        if 'lastTradeDate' in result:
            result['lastTradeDate'] = pd.to_datetime(result['lastTradeDate'])
        return result
    return {key: _task6_decode(val) for key, val in value.items()}


def _task6_encode(value):
    import dataclasses, math
    from datetime import date, datetime
    import pandas as pd
    import numpy as np
    if dataclasses.is_dataclass(value):
        return {'_type': type(value).__name__, **{f.name: _task6_encode(getattr(value,f.name)) for f in dataclasses.fields(value)}}
    if isinstance(value,pd.DataFrame): return {'_type':'DataFrame','columns':list(value.columns),'records':_task6_encode(value.to_dict('records'))}
    if isinstance(value,(datetime,date)): return value.isoformat()
    if isinstance(value,dict): return {k:_task6_encode(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [_task6_encode(v) for v in value]
    if isinstance(value,(float,np.floating)) and not math.isfinite(value): return {'_nonfinite':str(float(value))}
    if isinstance(value,np.generic): return value.item()
    return value


@pytest.mark.parametrize('case', sorted(p.stem for p in (Path(__file__).parent/'fixtures/task6_golden').glob('*.json')))
@pytest.mark.asyncio
async def test_task6_original_recorded_outputs(case, monkeypatch):
    from datetime import datetime
    from types import SimpleNamespace
    from consensus_engine.scanners import expected_move as em, options
    from consensus_engine.analysis import options_presentation as selection
    raw = json.loads((Path(__file__).parent/'fixtures/task6_golden'/f'{case}.json').read_text())
    inputs = _task6_decode(raw['inputs'])
    def outcome(operation):
        try: return {'status':'returned','value':_task6_encode(operation())}
        except Exception as exc: return {'status':'raised','exception':type(exc).__name__,'message':str(exc)}
    if case.startswith('em_'):
        calls=[]
        now=datetime.fromisoformat(inputs['now'])
        monkeypatch.setattr(em,'now_eastern',lambda:now)
        monkeypatch.setattr(em.cfg,'get',lambda key,default=None: inputs['settings'].get(key,default))
        monkeypatch.setattr(em,'_fetch_bundle',lambda *args:inputs['bundle'])
        def fallback(ticker,now,horizon):
            calls.append([ticker,now.isoformat(),horizon])
            if case == 'em_quality_fallback_failed': raise RuntimeError('synthetic delayed fetch failure')
            return {**inputs['good_fallback'],'source':'yfinance'}
        monkeypatch.setattr(em,'_yfinance_bundle',fallback)
        try:
            result = await em.compute_em('SPY',horizon=inputs['horizon'])
            actual={'status':'returned','result':_task6_encode(result),'absent_chart':em.render_chart(result)}
            chosen = inputs['good_fallback'] if calls else inputs['bundle']
            if calls: chosen = {**chosen,'source':'yfinance'}
            pure = em.compute_em_from_bundle('SPY',chosen,em.ExpectedMoveSettings(),now,inputs['horizon'])
            assert _task6_encode(pure) == actual['result']
        except em.EMUnavailable as exc:
            actual={'status':'raised','exception':type(exc).__name__,'message':str(exc)}
        actual['fallback_calls']=calls
    elif case.startswith('atm_'):
        actual=outcome(lambda:em.select_atm(inputs['calls'],inputs['puts'],inputs['spot'],min_open_interest=100))
    elif case.startswith('pool_'):
        actual=[vars(h) for h in selection._current_day_pool([SimpleNamespace(**h) for h in inputs])]
    elif case == 'options_directional_boundaries':
        actual=[selection._is_directional(*row) for row in inputs]
    else:
        import pandas as pd
        chain=SimpleNamespace(calls=inputs['calls'],puts=pd.DataFrame())
        actual={'unusual':outcome(lambda:options._detect_unusual_activity(chain)),
                'flow':outcome(lambda:options._scan_chain_for_flow('SYNTH',chain,'2026-06-26',inputs['spot'],**inputs['flow_args']))}
    assert actual == raw['output']
