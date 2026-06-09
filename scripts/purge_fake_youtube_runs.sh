#!/usr/bin/env bash
# Purge the 5 hallucinated Gemini-v2 YouTube runs (June 1-5 2026) that poisoned the
# live brief with fabricated levels: NVDA 850 (x3), MSFT 415, SPY 500, TSLA 175.
# Root cause was a live-engine Gemini hallucination (spans returned but NULL
# prompt_token_count) — see item B in deep-dive-2026-06-08. The persist path is
# fixed by the quarantine guard in gemini_video_parser; this script removes the
# already-persisted poison.
#
# Hardened per Pass-3: stop the engine for the ~1s delete (no SQLITE_BUSY), run the
# write as the openclaw user (no root-owned WAL/SHM -> no EACCES crash-loop), and
# chown the DB + WAL/SHM + backup back to openclaw afterwards.
#
# Idempotent (re-running deletes nothing). Reversible: cp "$BAK" "$DB" with engine stopped.
set -euo pipefail
DB=/home/openclaw/.openclaw/workspace/consensus.db
BAK=/home/openclaw/.openclaw/workspace/consensus.db.bak.pre-purge

echo "=== 1. online backup -> $BAK ==="
sudo -u openclaw sqlite3 "$DB" ".backup '$BAK'"

echo "=== 2. stop consensus-engine for the delete ==="
systemctl stop consensus-engine.service

echo "=== 3. atomic delete (as openclaw) anchored on the 5 video_ids ==="
sudo -u openclaw sqlite3 "$DB" <<'SQL'
PRAGMA busy_timeout=30000;
PRAGMA foreign_keys=0;
BEGIN IMMEDIATE;
CREATE TEMP TABLE _bad(vid TEXT PRIMARY KEY);
INSERT INTO _bad(vid) VALUES
  ('SNWK2j6liDs'),('Dh7KxoS1gqE'),('EkBOYSy2jWs'),('YpsdjHaJm7E'),('e_iCwe2yX14');
DELETE FROM youtube_levels          WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_signals         WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_catalysts       WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_evidence_spans  WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_visual_evidence WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_macro           WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_options         WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_setups          WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_transcripts     WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_analysis_runs   WHERE video_id IN (SELECT vid FROM _bad);
DELETE FROM youtube_videos          WHERE video_id IN (SELECT vid FROM _bad);
DROP TABLE _bad;
COMMIT;
SQL

echo "=== 4. chown DB + WAL/SHM + backup back to openclaw ==="
chown openclaw:openclaw "$DB" "$BAK" 2>/dev/null || true
[ -f "$DB-wal" ] && chown openclaw:openclaw "$DB-wal" || true
[ -f "$DB-shm" ] && chown openclaw:openclaw "$DB-shm" || true
chmod 600 "$DB" 2>/dev/null || true

echo "=== 5. restart consensus-engine ==="
systemctl start consensus-engine.service

echo "=== 6. verify all poison rows gone (every count must be 0) ==="
sudo -u openclaw sqlite3 "$DB" <<'SQL'
.mode column
.headers on
SELECT 'runs' t, COUNT(*) n FROM youtube_analysis_runs WHERE video_id IN ('SNWK2j6liDs','Dh7KxoS1gqE','EkBOYSy2jWs','YpsdjHaJm7E','e_iCwe2yX14')
UNION ALL SELECT 'videos', COUNT(*) FROM youtube_videos WHERE video_id IN ('SNWK2j6liDs','Dh7KxoS1gqE','EkBOYSy2jWs','YpsdjHaJm7E','e_iCwe2yX14')
UNION ALL SELECT 'levels', COUNT(*) FROM youtube_levels WHERE video_id IN ('SNWK2j6liDs','Dh7KxoS1gqE','EkBOYSy2jWs','YpsdjHaJm7E','e_iCwe2yX14')
UNION ALL SELECT 'signals', COUNT(*) FROM youtube_signals WHERE video_id IN ('SNWK2j6liDs','Dh7KxoS1gqE','EkBOYSy2jWs','YpsdjHaJm7E','e_iCwe2yX14')
UNION ALL SELECT 'spans', COUNT(*) FROM youtube_evidence_spans WHERE video_id IN ('SNWK2j6liDs','Dh7KxoS1gqE','EkBOYSy2jWs','YpsdjHaJm7E','e_iCwe2yX14')
UNION ALL SELECT 'visual', COUNT(*) FROM youtube_visual_evidence WHERE video_id IN ('SNWK2j6liDs','Dh7KxoS1gqE','EkBOYSy2jWs','YpsdjHaJm7E','e_iCwe2yX14')
UNION ALL SELECT 'macro', COUNT(*) FROM youtube_macro WHERE video_id IN ('SNWK2j6liDs','Dh7KxoS1gqE','EkBOYSy2jWs','YpsdjHaJm7E','e_iCwe2yX14');
SELECT 'active_poison_levels' tag, COUNT(*) n FROM youtube_levels WHERE id IN (398,396,414,424,445,412);
SQL
echo "=== done ==="
