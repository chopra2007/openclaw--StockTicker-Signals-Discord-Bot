"""Durable human labels and bounded, source-grounded example retrieval."""
from __future__ import annotations

import asyncio
import json
import math
import re
import time

from consensus_engine import db

# Shared by save/refresh operations; never held while doing AI inference.
lock = asyncio.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS analyst_feedback_samples (
 view_id INTEGER PRIMARY KEY REFERENCES analyst_post_views(id),
 source_key TEXT NOT NULL, ticker TEXT NOT NULL, analyst TEXT NOT NULL,
 raw_text TEXT NOT NULL, image_urls_json TEXT NOT NULL, original_direction TEXT NOT NULL,
 original_reason TEXT, source_url TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS analyst_feedback_labels (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 view_id INTEGER NOT NULL REFERENCES analyst_feedback_samples(view_id),
 direction TEXT NOT NULL CHECK(direction IN ('long','short','unclear')),
 actor TEXT NOT NULL, event_id TEXT NOT NULL UNIQUE, created_at REAL NOT NULL,
 generated_reason TEXT NOT NULL DEFAULT '', vision_json TEXT NOT NULL DEFAULT '[]',
 explained INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
 notified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_feedback_labels_view ON analyst_feedback_labels(view_id,id);
CREATE TABLE IF NOT EXISTS analyst_feedback_notes (
 id INTEGER PRIMARY KEY AUTOINCREMENT, label_id INTEGER NOT NULL REFERENCES analyst_feedback_labels(id),
 explanation TEXT NOT NULL, event_id TEXT NOT NULL UNIQUE, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS analyst_review_groups (
 message_id TEXT PRIMARY KEY, channel_id TEXT NOT NULL, ticker TEXT NOT NULL,
 embed_json TEXT NOT NULL, members_json TEXT NOT NULL,
 dirty INTEGER NOT NULL DEFAULT 0, thread_id TEXT
);
CREATE TABLE IF NOT EXISTS analyst_review_cards (
 group_id TEXT NOT NULL REFERENCES analyst_review_groups(message_id),
 view_id INTEGER NOT NULL REFERENCES analyst_feedback_samples(view_id),
 message_id TEXT, payload_json TEXT, next_part INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(group_id,view_id)
);
"""


async def schema(conn):
    await conn.executescript(SCHEMA)


async def register_group(channel_id, message_id, ticker, embed, members):
    conn = await db.get_db()
    await conn.execute('''INSERT OR IGNORE INTO analyst_review_groups
        (message_id,channel_id,ticker,embed_json,members_json) VALUES (?,?,?,?,?)''',
        (str(message_id),str(channel_id),ticker,json.dumps(embed),json.dumps(members)))
    for member in members:
        view_id = member.get('analyst_post_view_id')
        if not view_id:
            continue
        await conn.execute('''INSERT OR IGNORE INTO analyst_feedback_samples
            SELECT id,source_post_key,ticker,analyst,raw_text,COALESCE(image_urls_json,'[]'),
            display_direction,reason_text,source_url,? FROM analyst_post_views
            WHERE id=? AND ticker=? AND display_direction='unclear' ''', (time.time(),view_id,ticker))
        # A previously corrected sample remains reviewable in a later group too.
        await conn.execute('''INSERT OR IGNORE INTO analyst_review_cards(group_id,view_id)
            SELECT ?,view_id FROM analyst_feedback_samples WHERE view_id=?''', (str(message_id),view_id))
    await conn.commit()


async def get_sample(view_id):
    conn = await db.get_db()
    row = await (await conn.execute('''SELECT s.*,l.id AS label_id,l.direction,l.generated_reason,
        l.vision_json,l.created_at AS labeled_at,
        COALESCE((SELECT explanation FROM analyst_feedback_notes n WHERE n.label_id=l.id
          ORDER BY n.id DESC LIMIT 1),'') AS explanation
        FROM analyst_feedback_samples s LEFT JOIN analyst_feedback_labels l ON l.id=(
          SELECT id FROM analyst_feedback_labels WHERE view_id=s.view_id
          ORDER BY length(event_id) DESC,event_id DESC LIMIT 1) WHERE s.view_id=?''', (view_id,))).fetchone()
    return dict(row) if row else None


async def mark_dirty(view_id):
    conn = await db.get_db()
    # All alerts which contain the exact post, including ones without a review card.
    groups = await (await conn.execute('SELECT message_id,members_json FROM analyst_review_groups')).fetchall()
    for group in groups:
        if any(m.get('analyst_post_view_id') == view_id for m in json.loads(group['members_json'])):
            await conn.execute('UPDATE analyst_review_groups SET dirty=1 WHERE message_id=?', (group['message_id'],))


async def save_label(view_id, direction, actor, event_id):
    if direction not in {'long','short','unclear'} or not str(event_id).isdigit():
        raise ValueError('Invalid classification')
    conn = await db.get_db()
    sample = await get_sample(view_id)
    if not sample:
        raise ValueError('This post is not available for review')
    await conn.execute('''INSERT OR IGNORE INTO analyst_feedback_labels
        (view_id,direction,actor,event_id,created_at) VALUES (?,?,?,?,?)''',
        (view_id,direction,str(actor),str(event_id),time.time()))
    row = await (await conn.execute('SELECT id,view_id,direction FROM analyst_feedback_labels WHERE event_id=?', (str(event_id),))).fetchone()
    if row['view_id'] != view_id or row['direction'] != direction:
        raise ValueError('Interaction already belongs to another choice')
    latest = await get_sample(view_id)
    await conn.execute('UPDATE analyst_post_views SET display_direction=? WHERE id=?', (latest['direction'],view_id))
    await mark_dirty(view_id)
    await conn.commit()
    return row['id']


async def add_explanation(view_id, label_id, explanation, event_id):
    sample = await get_sample(view_id)
    if not sample or sample['label_id'] != label_id:
        raise ValueError('Your selection changed. Open Add explanation again.')
    if not explanation.strip() or len(explanation) > 2000:
        raise ValueError('Explanation must contain 1 to 2000 characters')
    conn = await db.get_db()
    await conn.execute('INSERT OR IGNORE INTO analyst_feedback_notes(label_id,explanation,event_id,created_at) VALUES (?,?,?,?)',
                       (label_id,explanation.strip(),str(event_id),time.time()))
    await conn.execute('UPDATE analyst_feedback_labels SET explained=0,attempts=0,notified=0 WHERE id=?', (label_id,))
    await conn.commit()


_STOP = set('a an the for and or to of is it in on at be will this that with from as by i we you are was my'.split())


def _terms(text):
    text = re.sub(r'\$[A-Za-z]{1,10}\b', ' ', text)
    text = re.sub(r'\b\d+(?:\.\d+)?\b', ' level ', text)
    return {term for term in re.findall(r'[a-z]{3,}', text.lower()) if term not in _STOP}


def _vision_text(vision):
    # Only observed prose contributes similarity, never JSON keys or default values.
    return ' '.join(str(item.get(key) or '') for item in vision if isinstance(item,dict)
        for key in ('summary','direction_evidence') if float(item.get('confidence') or 0) >= .65)


async def relevant_examples(text, vision, *, source_key=None, before=None, limit=4):
    """Use current labels only, excluding self and temporal leakage."""
    # The engine initializes its DB before ingest. Standalone model calls and
    # tools must not create/open the production database as a retrieval side effect.
    conn = db._db
    if conn is None:
        return []
    query_terms = _terms(text + ' ' + _vision_text(vision))
    if len(query_terms) < 2:
        return []
    rows = await (await conn.execute('''SELECT DISTINCT s.view_id FROM analyst_feedback_samples s
        JOIN analyst_feedback_labels l ON l.view_id=s.view_id
        WHERE l.created_at < ? ORDER BY l.id DESC LIMIT 500''', (before if before is not None else time.time()+1,))).fetchall()
    candidates = []
    for row in rows:
        sample = await get_sample(row['view_id'])
        if not sample['label_id'] or sample['source_key'] == source_key:
            continue
        if before is not None and sample['labeled_at'] >= before:
            continue
        if sample['raw_text'].strip() == text.strip():
            continue
        terms = _terms(sample['raw_text'] + ' ' + _vision_text(json.loads(sample['vision_json'])))
        overlap = query_terms & terms
        score = len(overlap) / max(1, len(query_terms | terms))
        if len(overlap) >= 2 and score >= .18:
            candidates.append((score,sample))
    candidates.sort(key=lambda pair: (pair[0],pair[1]['label_id']), reverse=True)
    return [dict(id=s['label_id'],ticker=s['ticker'],raw_text=s['raw_text'][:5000],
                 direction=s['direction'],user_explanation=s['explanation'],
                 inferred_explanation=s['generated_reason'][:2000],
                 image_evidence=json.loads(s['vision_json'])) for _,s in candidates[:limit]]


def validate_learned_view(item, ticker, text, examples):
    """Examples can explain a quote; they cannot supply missing source evidence."""
    from consensus_engine.models import TickerPostView, locate_unique_source_span
    from .analyst_evidence import direction_is_supported, unsided_option, shared_ticker_subject
    if item.get('decision_code') != 'feedback_example':
        return None
    direction = item.get('direction')
    if direction not in {'long','short'} or type(item.get('example_id')) is not int:
        return None
    if not any(e['id'] == item['example_id'] and e['direction'] == direction for e in examples):
        return None
    try:
        confidence = float(item.get('confidence',0))
    except (TypeError,ValueError):
        return None
    span = locate_unique_source_span(text,item.get('reason_text'))
    if not span or not math.isfinite(confidence) or not .8 <= confidence <= 1:
        return None
    quote = text[slice(*span)]
    named = {t.upper() for t in re.findall(r'\$([A-Za-z]{1,10})\b',quote)}
    if named != {ticker.upper()} or shared_ticker_subject(text,span,ticker) or unsided_option(quote):
        return None
    opposite = 'short' if direction == 'long' else 'long'
    from .analyst_evidence import ticker_text_context
    context = ticker_text_context(text,ticker)
    # An analogy must not carry a label across changed polarity. Leave these
    # clauses to the normal evidence validator, which can understand an explicit
    # supported setup; a retrieved example alone cannot resolve negation.
    negated_or_failed = re.search(
        r"\b(?:no|not|never|without|isn['’]?t|wasn['’]?t|aren['’]?t|weren['’]?t|"
        r"didn['’]?t|doesn['’]?t|don['’]?t|can['’]?t|cannot|won['’]?t|"
        r"failed|failure|invalidated|unable)\b",context,re.I)
    if negated_or_failed or (unsided_option(text) and not direction_is_supported(direction,quote)):
        return None
    if direction_is_supported(opposite,context):
        return None
    return TickerPostView(ticker=ticker,direction=direction,reason_text=quote,
        reason_start=span[0],reason_end=span[1],reason_kind='setup',
        decision_code='feedback_example',parser_version='analyst-feedback-v1',
        feedback_example_id=item['example_id'],feedback_confidence=confidence)
