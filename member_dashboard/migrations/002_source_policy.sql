-- Additional license obligations. Authority/backups are verified outside the
-- historical web snapshot; defaults do not confer permission after restore.
ALTER TABLE source_permissions ADD COLUMN delete_on_expiry INTEGER NOT NULL DEFAULT 0 CHECK(delete_on_expiry IN (0,1));
ALTER TABLE source_permissions ADD COLUMN tombstone_allowed INTEGER NOT NULL DEFAULT 0 CHECK(tombstone_allowed IN (0,1));
CREATE INDEX source_permissions_product ON source_permissions(source_id,product_id);
CREATE TRIGGER source_permissions_immutable BEFORE UPDATE ON source_permissions BEGIN SELECT RAISE(ABORT,'immutable policy; record a new policy version'); END;
CREATE TABLE content_tombstones (
    object_type TEXT NOT NULL CHECK(object_type IN ('publications','publication_changes','assets','messages','report_versions','market_results')),
    object_id TEXT NOT NULL,
    reason TEXT NOT NULL CHECK(reason IN ('source_permission_unavailable','explicit_retraction')),
    removed_at REAL NOT NULL,
    PRIMARY KEY(object_type,object_id)
) STRICT;
