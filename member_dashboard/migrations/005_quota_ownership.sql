-- Admission IDs group one physical request across every intersecting scope.
CREATE TABLE quota_attempts (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL UNIQUE,
    owner TEXT NOT NULL,
    caller TEXT NOT NULL CHECK(caller IN ('bot','dashboard')),
    fingerprint TEXT NOT NULL,
    created_at REAL NOT NULL
) STRICT;
ALTER TABLE provider_admissions ADD COLUMN group_id TEXT REFERENCES quota_attempts(id);
CREATE INDEX provider_admissions_group ON provider_admissions(group_id);
CREATE TABLE quota_endpoints (
    endpoint TEXT PRIMARY KEY,
    scopes_json TEXT NOT NULL,
    participation_verified INTEGER NOT NULL CHECK(participation_verified IN (0,1)),
    minimum_units REAL NOT NULL CHECK(minimum_units>0)
) STRICT;
