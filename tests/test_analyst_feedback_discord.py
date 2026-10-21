import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from consensus_engine import db
from consensus_engine.analysis import analyst_feedback as store
from consensus_engine.alerts import analyst_feedback as ui


@pytest.fixture
async def example(tmp_path, monkeypatch):
    monkeypatch.setattr(db,'DB_PATH',str(tmp_path/'review.db'))
    monkeypatch.setattr(db,'_db',None)
    conn = await db.init_db()
    cur = await conn.execute('''INSERT INTO analyst_post_views
      (source_post_key,analyst,ticker,detected_at,raw_text,raw_text_sha256,
       display_direction,reason_kind,decision_code,parser_version,created_at,image_urls_json)
      VALUES ('post','test','AAPL',?,'$AAPL bet on upside','hash','unclear','none','missing','test',?,?)''',
      (time.time(),time.time(),json.dumps(['https://pbs.twimg.com/one.png'])))
    view_id = cur.lastrowid
    await conn.commit()
    members=[dict(analyst='test',direction='unclear',reason='reason not stated',analyst_post_view_id=view_id),
             dict(analyst='other',direction='short',reason='breakdown',analyst_post_view_id=None)]
    await store.register_group('10','20','AAPL',{'title':'original','fields':[]},members)
    await conn.execute("UPDATE analyst_review_cards SET message_id='30',payload_json=?",(json.dumps({'content':'source'}),))
    await conn.commit()
    yield view_id,conn
    await db.close_db()


def test_review_payloads_preserve_entire_text_all_images_and_per_post_buttons():
    text = ('$AAPL **full source** @everyone\n' * 350) + 'THE END'
    images = ['https://pbs.twimg.com/%s.png'%i for i in range(14)]
    parts = ui.review_payloads(dict(view_id=7,ticker='AAPL',analyst='test',raw_text=text,
        image_urls_json=json.dumps(images),source_url=None,direction=None),'20')
    combined = ''.join(p['content'] for p in parts)
    assert text in combined
    assert all(len(p['content']) <= 2000 for p in parts)
    assert [e['image']['url'] for p in parts for e in p.get('embeds',[])] == images
    assert all(len(p.get('embeds',[])) <= 10 for p in parts)
    buttons=parts[-1]['components'][0]['components']
    assert [b['label'] for b in buttons[:3]] == ['Bullish','Bearish','Unclear']
    assert len({b['custom_id'] for b in buttons}) == 4
    assert all(p['allowed_mentions']=={'parse':[]} for p in parts)


def test_long_emoji_post_respects_discord_utf16_limit_without_losing_text():
    text='🚀'*2400
    parts=ui.review_payloads(dict(view_id=1,ticker='AAPL',analyst='test',raw_text=text,
        image_urls_json='[]',source_url=None,direction=None),'20')
    assert text in ''.join(p['content'] for p in parts)
    assert all(len(p['content'].encode('utf-16-le'))//2 <= 2000 for p in parts)


def interaction(view_id, side='long', message='30', event='100'):
    return dict(id=event,token='fake',application_id='app',type=3,channel_id='10',
                member={'user':{'id':'user'}},message={'id':message},
                data={'custom_id':f'af:{view_id}:{side}'})


async def test_click_saves_before_network_refresh_and_survives_failure(example):
    view_id,conn=example
    async def api(method,path,payload=None):
        if method=='PATCH':
            assert (await store.get_sample(view_id))['direction']=='long'
            raise RuntimeError('network unavailable')
        return {'id':'50'}
    with patch.object(ui,'api',side_effect=api):
        await ui.handle_interaction(interaction(view_id))
    assert (await store.get_sample(view_id))['direction']=='long'
    assert (await (await conn.execute('SELECT dirty FROM analyst_review_groups')).fetchone())[0]==1
    with patch.object(ui,'api',new=AsyncMock(return_value={'id':'50'})) as remote:
        await ui.refresh_groups()
    assert (await (await conn.execute('SELECT dirty FROM analyst_review_groups')).fetchone())[0]==0
    payloads=[c.args[2] for c in remote.call_args_list if c.args[0]=='PATCH']
    group=next(p for p in payloads if p.get('embeds'))['embeds'][0]
    bias=next(f for f in group['fields'] if f['name']=='Group bias')['value']
    assert '1 bullish' in bias and '1 bearish' in bias and 'Mixed' in bias


async def test_forged_message_cannot_label_stored_sample(example):
    view_id,_=example
    with patch.object(ui,'api',new=AsyncMock(return_value={})):
        await ui.handle_interaction(interaction(view_id,message='999'))
    assert (await store.get_sample(view_id))['direction'] is None


async def test_optional_modal_bound_to_current_label(example):
    view_id,_=example
    await store.save_label(view_id,'long','user','100')
    with patch.object(ui,'api',new=AsyncMock(return_value={})) as remote:
        await ui.handle_interaction(interaction(view_id,side='note',event='101'))
    callback=remote.call_args.args[2]
    assert callback['type']==9
    modal=callback['data']['custom_id']
    await store.save_label(view_id,'short','user','102')
    data=interaction(view_id,event='103')
    data['type']=5
    data['data']={'custom_id':modal,'components':[{'components':[{'custom_id':'reason','value':'old reason'}]}]}
    with patch.object(ui,'api',new=AsyncMock(return_value={})):
        await ui.handle_interaction(data)
    assert (await store.get_sample(view_id))['explanation']==''


async def test_gateway_routes_interactions_without_blocking():
    import asyncio
    from consensus_engine.scanners.discord_tweetshift import DiscordTweetShiftListener
    listener=DiscordTweetShiftListener(AsyncMock())
    with patch.object(ui,'handle_interaction',new=AsyncMock()) as handle:
        await listener._handle_dispatch('INTERACTION_CREATE',{'data':{'custom_id':'af:1:long'}})
        await asyncio.sleep(0)
    handle.assert_awaited_once()


async def test_thread_explanation_distinguishes_human_label_from_evidence(example):
    view_id,conn=example
    await store.save_label(view_id,'long','user','100')
    with patch.object(ui,'api',new=AsyncMock(return_value={'id':'70'})) as remote, \
         patch('models.router._vision_for_url',new=AsyncMock(return_value={'ticker':'AAPL','summary':'upward arrow'})), \
         patch('models.text_model.chat_completion',new=AsyncMock(return_value='The arrow points above resistance.')):
        await ui.explain_pending()
    sample=await store.get_sample(view_id)
    assert 'arrow' in sample['generated_reason']
    assert 'upward arrow' in sample['vision_json']
    thread_posts=[c.args[2]['content'] for c in remote.call_args_list if c.args[1]=='/channels/70/messages']
    assert thread_posts and 'Your label: **Bullish**' in thread_posts[0]
    assert 'Bot interpretation' in thread_posts[0]


async def test_deleted_summary_does_not_block_later_group(example):
    view_id,conn=example
    first=await (await conn.execute('SELECT * FROM analyst_review_groups')).fetchone()
    await store.register_group('10','21','AAPL',json.loads(first['embed_json']),json.loads(first['members_json']))
    await store.save_label(view_id,'long','user','100')
    calls=[]
    async def remote(method,path,payload=None):
        calls.append(path)
        if path.endswith('/messages/20'):
            raise ui.DiscordError(404)
        return {'id':'50'}
    with patch.object(ui,'api',side_effect=remote):
        await ui.refresh_groups()
    assert '/channels/10/messages/21' in calls
    assert (await (await conn.execute('SELECT count(*) FROM analyst_review_groups WHERE dirty=1')).fetchone())[0]==0


async def test_published_cards_resume_after_restart_without_losing_source(example):
    view_id,conn=example
    await conn.execute('UPDATE analyst_review_cards SET message_id=NULL,payload_json=NULL')
    await conn.commit()
    with patch.object(ui,'api',new=AsyncMock(return_value={'id':'80'})) as remote:
        await ui.publish_pending()
        await ui.publish_pending()
    assert remote.call_count >= 1
    first_count=remote.call_count
    await db.close_db()
    conn=await db.init_db()
    with patch.object(ui,'api',new=AsyncMock(return_value={'id':'81'})) as after_restart:
        await ui.publish_pending()
    after_restart.assert_not_awaited()
    row=await (await conn.execute('SELECT * FROM analyst_review_cards')).fetchone()
    assert row['message_id']=='80'
    assert first_count==1
