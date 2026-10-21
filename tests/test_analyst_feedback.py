"""Human corrections are durable examples, not manufactured market evidence."""
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import db
from consensus_engine.analysis import analyst_feedback as feedback


@pytest.fixture
async def store(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'feedback.db'))
    monkeypatch.setattr(db, '_db', None)
    conn = await db.init_db()
    yield conn
    await db.close_db()


async def seed(conn, text='$AAPL winding up for a move', ticker='AAPL', side='unclear', key='post-1'):
    cur = await conn.execute('''INSERT INTO analyst_post_views
        (source_post_key,analyst,ticker,detected_at,raw_text,raw_text_sha256,
         display_direction,reason_kind,decision_code,parser_version,created_at,image_urls_json)
        VALUES (?, 'test', ?, ?, ?, 'hash', ?, 'none','missing','test',?,?)''',
        (key,ticker,time.time(),text,side,time.time(),json.dumps(['https://pbs.twimg.com/chart.png'])))
    await conn.commit()
    return cur.lastrowid


async def group(conn, view_id):
    members = [dict(analyst='test', direction='unclear', analyst_post_view_id=view_id,
                    signal_event_id=None, reason='reason not stated')]
    await feedback.register_group('10', '20', 'AAPL', {'title':'group'}, members)
    return await feedback.get_sample(view_id)


async def test_latest_label_history_and_duplicate_event(store):
    view_id = await seed(store)
    await group(store, view_id)
    first = await feedback.save_label(view_id, 'long', 'user', '100')
    assert await feedback.save_label(view_id, 'long', 'user', '100') == first
    await feedback.save_label(view_id, 'short', 'user', '101')
    sample = await feedback.get_sample(view_id)
    assert sample['direction'] == 'short'
    assert sample['original_direction'] == 'unclear'
    assert sample['raw_text'] == '$AAPL winding up for a move'
    assert json.loads(sample['image_urls_json']) == ['https://pbs.twimg.com/chart.png']
    rows = await (await store.execute('SELECT * FROM analyst_feedback_labels')).fetchall()
    assert len(rows) == 2
    assert (await (await store.execute('SELECT display_direction FROM analyst_post_views')).fetchone())[0] == 'short'


async def test_stale_explanation_does_not_attach_to_new_label(store):
    view_id = await seed(store)
    await group(store, view_id)
    old = await feedback.save_label(view_id, 'long', 'user', '100')
    await feedback.save_label(view_id, 'unclear', 'user', '101')
    with pytest.raises(ValueError, match='changed'):
        await feedback.add_explanation(view_id, old, 'old rationale', '102')
    assert (await feedback.get_sample(view_id))['explanation'] == ''


async def test_retrieval_latest_relevant_only_and_no_self_or_future(store):
    view_id = await seed(store, '$AAPL winding up for a move through resistance')
    await group(store, view_id)
    await feedback.save_label(view_id, 'long', 'user', '100')
    await feedback.save_label(view_id, 'short', 'user', '101')
    examples = await feedback.relevant_examples('$MSFT winding up for a move through resistance', [])
    assert len(examples) == 1
    assert examples[0]['direction'] == 'short'
    assert await feedback.relevant_examples('$AAPL dividend meeting tomorrow', []) == []
    assert await feedback.relevant_examples('$AAPL winding up for a move through resistance', [], source_key='post-1') == []
    assert await feedback.relevant_examples('$MSFT winding up for a move through resistance', [], before=1) == []


async def test_non_unclear_cannot_be_registered_for_review(store):
    view_id = await seed(store, side='long')
    assert await group(store, view_id) is None


async def test_text_model_receives_real_examples(store):
    from models.text_model import analyze_tweet
    view_id = await seed(store)
    await group(store, view_id)
    await feedback.save_label(view_id, 'long', 'user', '100')
    with patch('models.text_model.chat_completion', new=AsyncMock(return_value=json.dumps({'tickers':['MSFT']}))) as chat:
        await analyze_tweet('$MSFT winding up for a move', 'other')
    context = json.loads(chat.call_args.args[1][1]['content'])
    assert context['human_examples'][0]['direction'] == 'long'
    assert context['human_examples'][0]['raw_text'] == '$AAPL winding up for a move'


def test_learned_view_needs_matching_example_and_current_source_quote():
    examples = [dict(id=1, direction='long')]
    item = dict(direction='long', decision_code='feedback_example', example_id=1,
                confidence=.9, reason_text='$MSFT bet it will be the largest company')
    text = item['reason_text']
    assert feedback.validate_learned_view(item, 'MSFT', text, examples).direction == 'long'
    assert feedback.validate_learned_view({**item,'example_id':2}, 'MSFT', text, examples) is None
    assert feedback.validate_learned_view({**item,'direction':'short'}, 'MSFT', text, examples) is None
    assert feedback.validate_learned_view(item, 'MSFT', '$MSFT not bullish', examples) is None
    assert feedback.validate_learned_view({**item,'reason_text':'$MSFT calls traded'}, 'MSFT', '$MSFT calls traded', examples) is None


async def test_learned_view_survives_parser_storage_and_swarm(store):
    from consensus_engine.models import TickerSignal, SourceType, Sentiment
    from consensus_engine.analysis.herding import _swarm_members
    from consensus_engine.analysis.tweet_parser import _parse_ticker_views
    original = await seed(store, '$AAPL bet it will be the largest company', key='training')
    await group(store,original)
    label = await feedback.save_label(original,'long','user','100')
    text = '$MSFT bet it will be the largest company'
    examples = await feedback.relevant_examples(text,[])
    views = _parse_ticker_views(dict(ticker_views=[dict(ticker='MSFT',direction='long',
        decision_code='feedback_example',reason_text=text,example_id=label,confidence=.9)],
        _human_examples=examples),['MSFT'],text)
    signal = TickerSignal(ticker='MSFT',source_type=SourceType.TWITTER,source_detail='new',
        raw_text=text,sentiment=Sentiment.NEUTRAL)
    await db.insert_signal(signal,ticker_view=views[0],source_url='https://x.com/new/status/123')
    _,_,details = await _swarm_members(store,'MSFT',0,time.time()+1,{'new'})
    assert details[0].direction == 'long'
    row = await (await store.execute("SELECT feedback_evidence_json FROM analyst_post_views WHERE ticker='MSFT'")).fetchone()
    assert json.loads(row[0])['example_id'] == label


async def test_unreadable_images_do_not_make_unrelated_posts_similar(store):
    from models.vision_model import _default_vision_output
    view_id=await seed(store,'$AAPL dividend meeting tomorrow')
    await group(store,view_id)
    label=await feedback.save_label(view_id,'unclear','user','100')
    empty=[_default_vision_output()]
    await store.execute('UPDATE analyst_feedback_labels SET vision_json=? WHERE id=?',(json.dumps(empty),label))
    await store.commit()
    assert await feedback.relevant_examples('$MSFT momentum breakout above resistance',empty)==[]


@pytest.mark.parametrize('text', ['$MSFT not bullish','$MSFT no breakout yet',
    '$MSFT breakout failed','$MSFT watching. Calls traded today',
    "$MSFT isn't bullish",'$MSFT breakout did not happen','$MSFT failed to break out',
    '$MSFT without a breakout'])
def test_learned_view_cannot_bypass_negative_or_unsided_context(text):
    quote = '$MSFT watching' if 'watching' in text else text
    assert feedback.validate_learned_view(dict(decision_code='feedback_example',direction='long',
        example_id=1,confidence=.9,reason_text=quote),'MSFT',text,[dict(id=1,direction='long')]) is None


async def test_image_relevant_example_survives_storage(store):
    from consensus_engine.models import TickerSignal, SourceType, Sentiment
    from consensus_engine.analysis.tweet_parser import _parse_ticker_views
    original=await seed(store,'$AAPL coil',key='image-training')
    await group(store,original)
    label=await feedback.save_label(original,'long','user','100')
    vision=[dict(summary='Large symmetrical triangle approaching apex',
        direction_evidence='Tight consolidation approaching resistance',confidence=.9)]
    await store.execute('UPDATE analyst_feedback_labels SET vision_json=? WHERE id=?',(json.dumps(vision),label))
    await store.commit()
    text='$MSFT coil'
    examples=await feedback.relevant_examples(text,vision)
    assert examples
    views=_parse_ticker_views(dict(ticker_views=[dict(ticker='MSFT',direction='long',
        decision_code='feedback_example',reason_text=text,example_id=label,confidence=.9)],
        _human_examples=examples,vision_outputs=vision),['MSFT'],text)
    await db.insert_signal(TickerSignal(ticker='MSFT',source_type=SourceType.TWITTER,
        source_detail='new',raw_text=text,sentiment=Sentiment.NEUTRAL),ticker_view=views[0])
    row=await (await store.execute("SELECT display_direction FROM analyst_post_views WHERE ticker='MSFT'")).fetchone()
    assert row[0]=='long'


async def test_standalone_classifier_does_not_open_or_initialize_database(monkeypatch):
    monkeypatch.setattr(db,'_db',None)
    with patch.object(db,'get_db',new=AsyncMock()) as opening:
        assert await feedback.relevant_examples('$MSFT winding up for a move',[])==[]
    opening.assert_not_called()
