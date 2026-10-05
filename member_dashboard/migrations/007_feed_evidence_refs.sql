-- Source computation time is retention authority, never a substitute for an
-- unavailable observation time in the public feed.
ALTER TABLE publications ADD COLUMN source_computed_at REAL;
DROP TRIGGER publications_immutable_content;
CREATE TRIGGER publications_immutable_content BEFORE UPDATE OF content_json,content_version,source_lineage_json,field_dependencies_json,required_features_json,retention_deadline,source_computed_at ON publications BEGIN SELECT RAISE(ABORT,'immutable publication; create a new version or delete'); END;
CREATE INDEX publications_computation_retention ON publications(source_computed_at,id);
-- Authorized exact metadata survives feed-content expiry so later retraction
-- can still annotate immutable saved evidence. No content or private grants.
CREATE TABLE publication_evidence_refs (
    card_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    recorded_at REAL NOT NULL,
    source_lineage_json TEXT NOT NULL CHECK(json_valid(source_lineage_json) AND json_type(source_lineage_json)='array' AND json_array_length(source_lineage_json) BETWEEN 1 AND 200),
    PRIMARY KEY(card_id,evidence_id,source_id,source_version)
) STRICT;
-- Version 6 could already have discarded references. Never guess their
-- historical completeness from a surviving latest revision or saved narrative.
UPDATE feed_state SET retraction_authority_required=1 WHERE retained_floor>0 OR EXISTS (SELECT 1 FROM publication_heads h LEFT JOIN publications p ON p.id=h.publication_id WHERE p.id IS NULL);
