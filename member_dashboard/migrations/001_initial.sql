-- This migration runs only against the explicit web database.
-- JSON content stores immutable versions; [] lineage means unverified, never allowed.
CREATE TABLE members (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    username TEXT NOT NULL UNIQUE CHECK(length(username) BETWEEN 3 AND 32 AND username=lower(username) AND username NOT GLOB '*[^a-z0-9_]*'),
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'member' CHECK(role IN ('member','admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')),
    authorization_version INTEGER NOT NULL DEFAULT 1 CHECK(authorization_version>0),
    created_at REAL NOT NULL,
    updated_at REAL
) STRICT;

CREATE TABLE sessions (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    token_digest BLOB NOT NULL UNIQUE CHECK(length(token_digest)=32),
    csrf_digest BLOB NOT NULL CHECK(length(csrf_digest)=32),
    authorization_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    absolute_expires_at REAL NOT NULL,
    idle_expires_at REAL NOT NULL,
    revoked_at REAL
) STRICT;

CREATE TABLE invites (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    token_digest BLOB NOT NULL UNIQUE CHECK(length(token_digest)=32),
    created_by TEXT REFERENCES members(id) ON DELETE SET NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    consumed_at REAL,
    revoked_at REAL,
    consumed_by TEXT REFERENCES members(id) ON DELETE SET NULL
) STRICT;

CREATE TABLE password_resets (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    token_digest BLOB NOT NULL UNIQUE CHECK(length(token_digest)=32),
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    consumed_at REAL,
    revoked_at REAL
) STRICT;

CREATE TABLE auth_attempts (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    username_digest BLOB NOT NULL CHECK(length(username_digest)=32),
    address_digest BLOB NOT NULL CHECK(length(address_digest)=32),
    attempted_at REAL NOT NULL,
    success INTEGER NOT NULL CHECK(success IN (0,1)),
    not_before REAL
) STRICT;
CREATE INDEX auth_attempts_username_time ON auth_attempts(username_digest,attempted_at);
CREATE INDEX auth_attempts_address_time ON auth_attempts(address_digest,attempted_at);

CREATE TABLE features (
    name TEXT PRIMARY KEY CHECK(name IN ('feed','setups','analysis','sec','options','em_daily','em_weekly','assistant')),
    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
    version INTEGER NOT NULL DEFAULT 1,
    updated_at REAL NOT NULL DEFAULT 0
) STRICT;
INSERT INTO features(name,enabled) VALUES ('feed',1),('setups',1),('analysis',1),('sec',1),('options',1),('em_daily',1),('em_weekly',1),('assistant',1);

CREATE TABLE audit_events (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    actor_member_id TEXT REFERENCES members(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_id TEXT,
    occurred_at REAL NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(detail_json))
) STRICT;

CREATE TABLE web_jobs (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    dedupe_key TEXT NOT NULL,
    ticker TEXT NOT NULL,
    section TEXT NOT NULL CHECK(section IN ('analysis','sec','options','em_daily','em_weekly')),
    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','unavailable','failed','draining','cancelled')),
    work_version INTEGER NOT NULL DEFAULT 1,
    feature_version INTEGER NOT NULL DEFAULT 1,
    policy_version TEXT NOT NULL DEFAULT 'unverified',
    required_features_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(required_features_json) AND json_type(required_features_json)='array'),
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    started_at REAL,
    finished_at REAL,
    not_before REAL,
    lease_until REAL,
    worker_id TEXT,
    error_code TEXT
) STRICT;
CREATE UNIQUE INDEX web_jobs_active_dedupe ON web_jobs(dedupe_key) WHERE status IN ('queued','running','draining');
CREATE INDEX web_jobs_pending ON web_jobs(status,not_before,created_at);

CREATE TABLE market_results (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    fingerprint TEXT NOT NULL UNIQUE,
    ticker TEXT NOT NULL,
    section TEXT NOT NULL CHECK(section IN ('analysis','sec','options','em_daily','em_weekly')),
    content_version INTEGER NOT NULL DEFAULT 1 CHECK(content_version>0),
    analysis_version TEXT NOT NULL DEFAULT 'v1',
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    source_lineage_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_lineage_json) AND json_type(source_lineage_json)='array'),
    field_dependencies_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(field_dependencies_json) AND json_type(field_dependencies_json)='array'),
    required_features_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(required_features_json) AND json_type(required_features_json)='array'),
    retention_deadline REAL,
    observed_at REAL,
    computed_at REAL,
    valid_until REAL,
    created_at REAL NOT NULL
) STRICT;
CREATE TRIGGER market_results_immutable BEFORE UPDATE ON market_results BEGIN SELECT RAISE(ABORT,'immutable result; create a new version or delete'); END;

CREATE TABLE report_versions (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    report_id TEXT NOT NULL CHECK(length(report_id)=36 AND substr(report_id,9,1)='-' AND substr(report_id,14,1)='-' AND substr(report_id,19,1)='-' AND substr(report_id,24,1)='-' AND length(replace(report_id,'-',''))=32 AND replace(report_id,'-','') NOT GLOB '*[^0-9a-f]*'),
    version INTEGER NOT NULL CHECK(version>0),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    source_lineage_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_lineage_json) AND json_type(source_lineage_json)='array'),
    field_dependencies_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(field_dependencies_json) AND json_type(field_dependencies_json)='array'),
    required_features_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(required_features_json) AND json_type(required_features_json)='array'),
    retention_deadline REAL,
    created_at REAL NOT NULL,
    finalized INTEGER NOT NULL DEFAULT 0 CHECK(finalized IN (0,1)),
    UNIQUE(report_id,version)
) STRICT;
CREATE TRIGGER report_versions_immutable BEFORE UPDATE ON report_versions BEGIN SELECT RAISE(ABORT,'immutable report; create a new version or delete'); END;

-- Ownership references exist before the first report version is completed.
CREATE TABLE report_owners (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    report_id TEXT NOT NULL CHECK(length(report_id)=36 AND substr(report_id,9,1)='-' AND substr(report_id,14,1)='-' AND substr(report_id,19,1)='-' AND substr(report_id,24,1)='-' AND length(replace(report_id,'-',''))=32 AND replace(report_id,'-','') NOT GLOB '*[^0-9a-f]*'),
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    current_version_id TEXT REFERENCES report_versions(id) ON DELETE SET NULL,
    authorization_version INTEGER NOT NULL DEFAULT 1,
    subscriber_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    deleted_at REAL,
    UNIQUE(report_id,member_id)
) STRICT;
CREATE INDEX report_owners_member ON report_owners(member_id,deleted_at,created_at);

CREATE TABLE research_requests (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    report_owner_id TEXT REFERENCES report_owners(id) ON DELETE SET NULL,
    ticker TEXT NOT NULL,
    authorization_version INTEGER NOT NULL DEFAULT 1,
    subscriber_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    deleted_at REAL
) STRICT;
CREATE INDEX research_requests_member ON research_requests(member_id,created_at);

CREATE TABLE request_sections (
    request_id TEXT NOT NULL REFERENCES research_requests(id) ON DELETE CASCADE,
    section TEXT NOT NULL CHECK(section IN ('analysis','sec','options','em_daily','em_weekly')),
    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','unavailable','failed')),
    job_id TEXT REFERENCES web_jobs(id) ON DELETE SET NULL,
    result_id TEXT REFERENCES market_results(id) ON DELETE SET NULL,
    message_code TEXT,
    PRIMARY KEY(request_id,section)
) STRICT;

CREATE TABLE job_subscribers (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    job_id TEXT NOT NULL REFERENCES web_jobs(id) ON DELETE CASCADE,
    request_id TEXT NOT NULL REFERENCES research_requests(id) ON DELETE CASCADE,
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    authorization_version INTEGER NOT NULL DEFAULT 1,
    subscriber_version INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL,
    deleted_at REAL,
    UNIQUE(job_id,request_id,member_id)
) STRICT;

CREATE TABLE conversations (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    title TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    deleted_at REAL,
    version INTEGER NOT NULL DEFAULT 1
) STRICT;
CREATE INDEX conversations_member ON conversations(member_id,deleted_at,created_at);

CREATE TABLE messages (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content_version INTEGER NOT NULL DEFAULT 1,
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    source_lineage_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_lineage_json) AND json_type(source_lineage_json)='array'),
    field_dependencies_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(field_dependencies_json) AND json_type(field_dependencies_json)='array'),
    required_features_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(required_features_json) AND json_type(required_features_json)='array'),
    retention_deadline REAL,
    created_at REAL NOT NULL
) STRICT;
CREATE TRIGGER messages_immutable BEFORE UPDATE ON messages BEGIN SELECT RAISE(ABORT,'immutable message; create a new version or delete'); END;

CREATE TABLE assistant_runs (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    member_id TEXT NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    authorization_version INTEGER NOT NULL DEFAULT 1,
    subscriber_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','unavailable','failed','draining','cancelled')),
    tool_calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    finished_at REAL,
    deleted_at REAL,
    error_code TEXT
) STRICT;
CREATE UNIQUE INDEX assistant_runs_active_member ON assistant_runs(member_id) WHERE status IN ('queued','running','draining');

CREATE TABLE web_usage (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    member_id TEXT REFERENCES members(id) ON DELETE CASCADE,
    run_id TEXT REFERENCES assistant_runs(id) ON DELETE SET NULL,
    kind TEXT NOT NULL,
    units REAL NOT NULL CHECK(units>=0),
    occurred_at REAL NOT NULL
) STRICT;
CREATE INDEX web_usage_member_time ON web_usage(member_id,kind,occurred_at);

CREATE TABLE publications (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    source_post_key TEXT NOT NULL,
    ticker TEXT NOT NULL,
    content_version TEXT NOT NULL,
    feature TEXT NOT NULL CHECK(feature IN ('feed','setups')),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    source_lineage_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_lineage_json) AND json_type(source_lineage_json)='array'),
    field_dependencies_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(field_dependencies_json) AND json_type(field_dependencies_json)='array'),
    required_features_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(required_features_json) AND json_type(required_features_json)='array'),
    retention_deadline REAL,
    observed_at REAL,
    published_at REAL NOT NULL,
    retracted_at REAL,
    UNIQUE(source_post_key,ticker,content_version)
) STRICT;

CREATE TRIGGER publications_immutable_content BEFORE UPDATE OF content_json,content_version,source_lineage_json,field_dependencies_json,required_features_json,retention_deadline ON publications BEGIN SELECT RAISE(ABORT,'immutable publication; create a new version or delete'); END;

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
    changed_at REAL NOT NULL,
    UNIQUE(card_id,content_version,operation)
) STRICT;

CREATE TRIGGER publication_changes_immutable BEFORE UPDATE ON publication_changes BEGIN SELECT RAISE(ABORT,'immutable publication change; create a new version or delete'); END;

CREATE TABLE source_checkpoints (
    source_id TEXT PRIMARY KEY,
    last_id TEXT,
    last_observed_at REAL,
    reconciliation_cursor TEXT,
    updated_at REAL NOT NULL
) STRICT;

CREATE TABLE assets (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    result_id TEXT NOT NULL REFERENCES market_results(id) ON DELETE CASCADE,
    content_version INTEGER NOT NULL DEFAULT 1,
    content_type TEXT NOT NULL CHECK(content_type='image/png'),
    content BLOB NOT NULL,
    source_lineage_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_lineage_json) AND json_type(source_lineage_json)='array'),
    field_dependencies_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(field_dependencies_json) AND json_type(field_dependencies_json)='array'),
    required_features_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(required_features_json) AND json_type(required_features_json)='array'),
    retention_deadline REAL,
    created_at REAL NOT NULL
) STRICT;
CREATE TRIGGER assets_immutable BEFORE UPDATE ON assets BEGIN SELECT RAISE(ABORT,'immutable asset; create a new version or delete'); END;

CREATE TABLE worker_heartbeat (
    worker_id TEXT PRIMARY KEY,
    observed_at REAL NOT NULL,
    state TEXT NOT NULL,
    work_version INTEGER NOT NULL DEFAULT 1
) STRICT;

-- Private grant/account references are web-policy state, never public responses.
CREATE TABLE source_permissions (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    source_id TEXT NOT NULL,
    product_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    private_grant_ref TEXT,
    private_account_ref TEXT,
    policy_version TEXT NOT NULL,
    audience TEXT NOT NULL,
    display_raw INTEGER NOT NULL DEFAULT 0 CHECK(display_raw IN (0,1)),
    display_derived INTEGER NOT NULL DEFAULT 0 CHECK(display_derived IN (0,1)),
    retain INTEGER NOT NULL DEFAULT 0 CHECK(retain IN (0,1)),
    model_input INTEGER NOT NULL DEFAULT 0 CHECK(model_input IN (0,1)),
    status TEXT NOT NULL DEFAULT 'unverified' CHECK(status IN ('allowed','denied','unverified')),
    attribution TEXT,
    delay_seconds REAL,
    effective_at REAL,
    expires_at REAL,
    review_at REAL,
    retention_deadline REAL,
    terms_url TEXT,
    evidence_ref TEXT,
    UNIQUE(source_id,product_id,policy_version)
) STRICT;

-- Only a restricted local broker may expose reserve/finish operations to bots.
CREATE TABLE provider_quota_policy (
    scope_id TEXT PRIMARY KEY,
    policy_version TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1)),
    window_seconds REAL NOT NULL CHECK(window_seconds>0),
    verified_limit REAL NOT NULL CHECK(verified_limit>=0),
    bot_reserved REAL NOT NULL CHECK(bot_reserved>=0),
    dashboard_allocated REAL NOT NULL CHECK(dashboard_allocated>=0),
    safety_margin REAL NOT NULL CHECK(safety_margin>=0),
    max_concurrency INTEGER,
    effective_at REAL NOT NULL,
    expires_at REAL,
    CHECK(bot_reserved+dashboard_allocated+safety_margin<=verified_limit)
) STRICT;

CREATE TABLE provider_admissions (
    id TEXT PRIMARY KEY CHECK(length(id)=36 AND substr(id,9,1)='-' AND substr(id,14,1)='-' AND substr(id,19,1)='-' AND substr(id,24,1)='-' AND length(replace(id,'-',''))=32 AND replace(id,'-','') NOT GLOB '*[^0-9a-f]*'),
    attempt_id TEXT NOT NULL,
    scope_id TEXT NOT NULL REFERENCES provider_quota_policy(scope_id),
    caller TEXT NOT NULL CHECK(caller IN ('bot','dashboard')),
    endpoint TEXT NOT NULL,
    units REAL NOT NULL CHECK(units>0),
    admitted_at REAL NOT NULL,
    window_start REAL NOT NULL,
    finished_at REAL,
    outcome TEXT,
    retry_after REAL,
    uncertain INTEGER NOT NULL DEFAULT 1 CHECK(uncertain IN (0,1)),
    UNIQUE(attempt_id,scope_id)
) STRICT;
CREATE INDEX provider_admissions_scope_time ON provider_admissions(scope_id,admitted_at);

CREATE TABLE provider_cooldowns (
    scope_id TEXT PRIMARY KEY REFERENCES provider_quota_policy(scope_id) ON DELETE CASCADE,
    not_before REAL NOT NULL,
    updated_at REAL NOT NULL
) STRICT;
