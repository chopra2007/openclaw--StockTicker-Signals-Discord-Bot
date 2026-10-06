ALTER TABLE web_jobs ADD COLUMN lease_token TEXT;
ALTER TABLE web_jobs ADD COLUMN lineage_json TEXT CHECK(lineage_json IS NULL OR json_valid(lineage_json));
ALTER TABLE web_jobs ADD COLUMN input_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(input_json));
ALTER TABLE web_jobs ADD COLUMN feature_mask_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(feature_mask_json));
ALTER TABLE web_jobs ADD COLUMN result_id TEXT REFERENCES market_results(id) ON DELETE SET NULL;
ALTER TABLE web_jobs ADD COLUMN actual_finished INTEGER NOT NULL DEFAULT 0 CHECK(actual_finished IN (0,1));
ALTER TABLE job_subscribers ADD COLUMN role TEXT NOT NULL DEFAULT 'member';
CREATE TABLE research_cache (
    dedupe_key TEXT PRIMARY KEY,
    result_id TEXT NOT NULL REFERENCES market_results(id) ON DELETE CASCADE
) STRICT;
CREATE TABLE worker_exits (
    worker_id TEXT PRIMARY KEY,
    confirmed_at REAL NOT NULL,
    reconciled INTEGER NOT NULL CHECK(reconciled IN (0,1))
) STRICT;
CREATE TABLE provider_calls (
    call_id TEXT PRIMARY KEY,
    worker_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running','draining','completed','failed','uncertain')),
    started_at REAL NOT NULL,
    draining_at REAL,
    completed_at REAL,
    reconciled INTEGER NOT NULL DEFAULT 0 CHECK(reconciled IN (0,1))
) STRICT;
CREATE INDEX provider_calls_active ON provider_calls(status);
CREATE TABLE provider_circuits (
    provider TEXT PRIMARY KEY,
    opened_at REAL NOT NULL,
    probe_after REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','probing','closed'))
) STRICT;
