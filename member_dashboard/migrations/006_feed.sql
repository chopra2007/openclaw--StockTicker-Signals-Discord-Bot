-- Preserve the AUTOINCREMENT high-water even when its last rows were purged.
CREATE TEMP TABLE feed_sequence_backup AS SELECT COALESCE(MAX(seq),0) AS value FROM sqlite_sequence WHERE name='publication_changes';
DROP TRIGGER publication_changes_immutable;
ALTER TABLE publication_changes RENAME TO publication_changes_old;
CREATE TABLE publication_changes (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id TEXT NOT NULL CHECK(length(card_id)=36 AND substr(card_id,9,1)='-' AND substr(card_id,14,1)='-' AND substr(card_id,19,1)='-' AND substr(card_id,24,1)='-' AND length(replace(card_id,'-',''))=32 AND replace(card_id,'-','') NOT GLOB '*[^0-9a-f]*'),
    content_version TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('upsert','delete')),
    feature TEXT NOT NULL CHECK(feature IN ('feed','setups')),
    content_json TEXT CHECK(content_json IS NULL OR json_valid(content_json)),
    source_lineage_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_lineage_json) AND json_type(source_lineage_json)='array'),
    field_dependencies_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(field_dependencies_json) AND json_type(field_dependencies_json)='array'),
    required_features_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(required_features_json) AND json_type(required_features_json)='array'),
    retention_deadline REAL,
    changed_at REAL NOT NULL
) STRICT;
INSERT INTO publication_changes SELECT * FROM publication_changes_old;
UPDATE sqlite_sequence SET seq=MAX(seq,(SELECT value FROM feed_sequence_backup)) WHERE name='publication_changes';
INSERT INTO sqlite_sequence(name,seq) SELECT 'publication_changes',value FROM feed_sequence_backup WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name='publication_changes');
DROP TABLE publication_changes_old;
CREATE TRIGGER publication_changes_immutable BEFORE UPDATE ON publication_changes BEGIN SELECT RAISE(ABORT,'immutable publication change; create a new version or delete'); END;
CREATE INDEX publication_changes_feature_sequence ON publication_changes(feature,sequence);
CREATE INDEX publication_changes_changed ON publication_changes(changed_at,sequence);
CREATE INDEX publications_retention ON publications(published_at,id);
CREATE INDEX publications_observation_retention ON publications(observed_at,id);
CREATE TABLE feed_state (
    singleton INTEGER PRIMARY KEY CHECK(singleton=1),
    high_water INTEGER NOT NULL DEFAULT 0,
    retained_floor INTEGER NOT NULL DEFAULT 0,
    source_rotation INTEGER NOT NULL DEFAULT 0,
    head_cursor TEXT NOT NULL DEFAULT '',
    retraction_authority_required INTEGER NOT NULL DEFAULT 0 CHECK(retraction_authority_required IN (0,1))
) STRICT;
INSERT INTO feed_state(singleton,high_water,retained_floor) SELECT 1,value,value FROM feed_sequence_backup;
DROP TABLE feed_sequence_backup;
CREATE TABLE publication_heads (
    card_id TEXT PRIMARY KEY,
    publication_id TEXT REFERENCES publications(id) ON DELETE SET NULL,
    feature TEXT NOT NULL CHECK(feature IN ('feed','setups')),
    active INTEGER NOT NULL CHECK(active IN (0,1)),
    last_sequence INTEGER NOT NULL,
    updated_at REAL NOT NULL,
    source_id TEXT,
    source_key TEXT,
    ticker TEXT,
    stale INTEGER NOT NULL DEFAULT 0 CHECK(stale IN (0,1)),
    authority_blocked INTEGER NOT NULL DEFAULT 0 CHECK(authority_blocked IN (0,1))
) STRICT;
CREATE INDEX publication_heads_source ON publication_heads(source_id,source_key,ticker);
CREATE TABLE publication_intervals (
    card_id TEXT NOT NULL REFERENCES publication_heads(card_id) ON DELETE CASCADE,
    publication_id TEXT NOT NULL REFERENCES publications(id) ON DELETE CASCADE,
    start_sequence INTEGER PRIMARY KEY,
    end_sequence INTEGER,
    ended_at REAL,
    CHECK((end_sequence IS NULL AND ended_at IS NULL) OR (end_sequence>start_sequence AND ended_at IS NOT NULL))
) STRICT;
CREATE UNIQUE INDEX publication_intervals_active ON publication_intervals(card_id) WHERE end_sequence IS NULL;
CREATE INDEX publication_intervals_page ON publication_intervals(card_id,start_sequence,end_sequence);
CREATE INDEX publication_intervals_cleanup ON publication_intervals(ended_at,start_sequence);
CREATE TABLE feed_source_status (
    source_id TEXT PRIMARY KEY,
    checked_at REAL NOT NULL,
    succeeded_at REAL,
    available INTEGER NOT NULL CHECK(available IN (0,1))
) STRICT;
-- Only a surviving last upsert proves visibility. Missing lifecycle authority
-- stays closed until trusted projection revisits the source.
INSERT INTO publication_heads(card_id,publication_id,feature,active,last_sequence,updated_at)
SELECT c.card_id,p.id,c.feature,CASE WHEN c.operation='upsert' AND p.id IS NOT NULL AND p.retracted_at IS NULL THEN 1 ELSE 0 END,c.sequence,c.changed_at
FROM publication_changes c LEFT JOIN publications p
 ON publication_card_id(p.source_post_key,p.ticker)=c.card_id AND p.content_version=c.content_version
WHERE c.sequence=(SELECT MAX(n.sequence) FROM publication_changes n WHERE n.card_id=c.card_id);
INSERT INTO publication_intervals(card_id,publication_id,start_sequence)
SELECT card_id,publication_id,last_sequence FROM publication_heads WHERE active=1 AND publication_id IS NOT NULL;
CREATE TABLE publication_retractions (
    card_id TEXT PRIMARY KEY,
    recorded_at REAL NOT NULL,
    source_lineage_json TEXT NOT NULL CHECK(json_valid(source_lineage_json) AND json_type(source_lineage_json)='array' AND json_array_length(source_lineage_json) BETWEEN 1 AND 200)
) STRICT;
CREATE TABLE evidence_retractions (
    evidence_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    recorded_at REAL NOT NULL,
    source_lineage_json TEXT NOT NULL CHECK(json_valid(source_lineage_json) AND json_type(source_lineage_json)='array' AND json_array_length(source_lineage_json) BETWEEN 1 AND 200),
    PRIMARY KEY(evidence_id,source_id,source_version)
) STRICT;
-- Existing explicit retractions must remain closed after licensed revision
-- deletion, even when their metadata retention authority is not yet verified.
UPDATE feed_state SET retraction_authority_required=1 WHERE EXISTS (SELECT 1 FROM publications WHERE retracted_at IS NOT NULL);
