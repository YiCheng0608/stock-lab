-- Synthetic pre-head regression fixture, not a production or full historical schema.
-- This is the smallest fixed 0004 slice needed to exercise 0005's NewsItem
-- temporal contract while retaining representative related rows and FKs.
PRAGMA foreign_keys = ON;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);

CREATE TABLE ingestion_runs (
    id INTEGER NOT NULL PRIMARY KEY,
    run_type VARCHAR(40) NOT NULL,
    source VARCHAR(120) NOT NULL,
    run_date DATE NOT NULL,
    status VARCHAR(30) NOT NULL,
    records INTEGER NOT NULL,
    error TEXT,
    request_key VARCHAR(180),
    data_as_of VARCHAR(80),
    metadata_json JSON NOT NULL DEFAULT '{}',
    started_at DATETIME NOT NULL,
    finished_at DATETIME,
    updated_at DATETIME NOT NULL
);

CREATE TABLE raw_payloads (
    id INTEGER NOT NULL PRIMARY KEY,
    ingestion_run_id INTEGER,
    source VARCHAR(120) NOT NULL,
    endpoint VARCHAR(500) NOT NULL,
    payload_path VARCHAR(800),
    sha256 VARCHAR(64),
    data_as_of VARCHAR(80),
    collected_at DATETIME NOT NULL,
    FOREIGN KEY(ingestion_run_id) REFERENCES ingestion_runs(id)
);

CREATE TABLE instruments (
    id INTEGER NOT NULL PRIMARY KEY,
    market VARCHAR(20) NOT NULL,
    exchange VARCHAR(20) NOT NULL DEFAULT 'TWSE',
    symbol VARCHAR(30) NOT NULL,
    name VARCHAR(120) NOT NULL,
    instrument_type VARCHAR(20) NOT NULL,
    etf_category VARCHAR(30),
    industry VARCHAR(120),
    listing_date DATE,
    is_watchlisted BOOLEAN NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    created_at DATETIME NOT NULL,
    CONSTRAINT uq_instrument_exchange_symbol UNIQUE (exchange, symbol)
);

CREATE INDEX ix_instruments_exchange ON instruments(exchange);
CREATE INDEX ix_instruments_symbol ON instruments(symbol);

CREATE TABLE events (
    id INTEGER NOT NULL PRIMARY KEY,
    instrument_id INTEGER,
    event_date DATE NOT NULL,
    event_type VARCHAR(40) NOT NULL,
    title VARCHAR(300) NOT NULL,
    description TEXT,
    details_json JSON NOT NULL DEFAULT '{}',
    source VARCHAR(120) NOT NULL,
    endpoint VARCHAR(500),
    raw_payload_id INTEGER,
    data_as_of VARCHAR(80),
    collected_at DATETIME NOT NULL,
    CONSTRAINT uq_event_identity UNIQUE (instrument_id, event_date, event_type, title),
    FOREIGN KEY(instrument_id) REFERENCES instruments(id),
    FOREIGN KEY(raw_payload_id) REFERENCES raw_payloads(id)
);

CREATE INDEX ix_event_instrument_date ON events(instrument_id, event_date);

CREATE TABLE news_items (
    id INTEGER NOT NULL PRIMARY KEY,
    canonical_key VARCHAR(300) NOT NULL,
    dedupe_cluster_id VARCHAR(160),
    category VARCHAR(30) NOT NULL DEFAULT 'taiwan',
    source_kind VARCHAR(40) NOT NULL DEFAULT 'official_disclosure',
    source_name VARCHAR(120) NOT NULL,
    source_url VARCHAR(800),
    source_url_kind VARCHAR(20) NOT NULL DEFAULT 'none',
    source_item_id VARCHAR(180),
    title VARCHAR(300) NOT NULL,
    summary TEXT,
    language VARCHAR(20) NOT NULL DEFAULT 'zh-Hant',
    published_at DATETIME,
    event_at DATETIME,
    collected_at DATETIME NOT NULL,
    symbols_json JSON NOT NULL DEFAULT '[]',
    theme_ids_json JSON NOT NULL DEFAULT '[]',
    impact_scope VARCHAR(30) NOT NULL DEFAULT 'instrument',
    impact_direction VARCHAR(30) NOT NULL DEFAULT 'unknown',
    impact_rationale TEXT,
    impact_method VARCHAR(120) NOT NULL DEFAULT 'default_unknown',
    confidence VARCHAR(20) NOT NULL DEFAULT 'unknown',
    raw_payload_id INTEGER,
    event_id INTEGER,
    content_hash VARCHAR(64),
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    supersedes_id INTEGER,
    CONSTRAINT uq_news_canonical_key UNIQUE (canonical_key),
    FOREIGN KEY(raw_payload_id) REFERENCES raw_payloads(id),
    FOREIGN KEY(event_id) REFERENCES events(id),
    FOREIGN KEY(supersedes_id) REFERENCES news_items(id)
);

CREATE INDEX ix_news_collected_id ON news_items(collected_at, id);
CREATE INDEX ix_news_published ON news_items(published_at);
CREATE INDEX ix_news_category ON news_items(category);
CREATE INDEX ix_news_source_kind ON news_items(source_kind);
CREATE INDEX ix_news_event ON news_items(event_id);

INSERT INTO alembic_version(version_num)
VALUES ('0004_product_news_themes');

INSERT INTO ingestion_runs(
    id, run_type, source, run_date, status, records, error, request_key,
    data_as_of, metadata_json, started_at, finished_at, updated_at
)
VALUES (
    1, 'event_fixture', 'synthetic_fixture', '2026-09-10', 'completed', 2,
    NULL, 'synthetic-migration-r10', '2026-09-10', '{"fixture":"synthetic"}',
    '2026-09-10 08:00:00', '2026-09-10 08:00:01', '2026-09-10 08:00:01'
);

INSERT INTO raw_payloads(
    id, ingestion_run_id, source, endpoint, payload_path, sha256, data_as_of, collected_at
)
VALUES (
    1, 1, 'synthetic_fixture', 'fixture://mops/events', NULL,
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    '2026-09-10', '2026-09-10 08:00:01'
);

INSERT INTO instruments(
    id, market, exchange, symbol, name, instrument_type, etf_category,
    industry, listing_date, is_watchlisted, status, created_at
)
VALUES (
    1, 'TW', 'TWSE', '2330', 'Synthetic Semiconductor', 'stock', NULL,
    'semiconductor', '1990-06-01', 1, 'active', '2026-09-10 08:00:00'
);

INSERT INTO events(
    id, instrument_id, event_date, event_type, title, description, details_json,
    source, endpoint, raw_payload_id, data_as_of, collected_at
)
VALUES (
    1, 1, '2026-09-09', 'material_information',
    'Synthetic dividend disclosure', 'Synthetic event row for migration regression',
    '{"fixture":"synthetic","amount":1.25}', 'synthetic_fixture',
    'fixture://mops/events/1', 1, '2026-09-09', '2026-09-10 08:00:01'
);

INSERT INTO news_items(
    id, canonical_key, dedupe_cluster_id, category, source_kind, source_name,
    source_url, source_url_kind, source_item_id, title, summary, language,
    published_at, event_at, collected_at, symbols_json, theme_ids_json,
    impact_scope, impact_direction, impact_rationale, impact_method, confidence,
    raw_payload_id, event_id, content_hash, status, supersedes_id
)
VALUES (
    1, 'synthetic:event:1:v1', 'synthetic-cluster-1', 'taiwan',
    'official_disclosure', 'synthetic_fixture', 'fixture://mops/events/1',
    'official', 'synthetic-event-1', 'Synthetic dividend disclosure',
    'Synthetic legacy news row linked to an Event.', 'zh-Hant',
    '2026-09-09 09:00:00', '2026-09-09 08:30:00', '2026-09-10 08:00:01',
    '["2330"]', '[]', 'instrument', 'unknown', 'fixture only',
    'synthetic_fixture', 'unknown', 1, 1,
    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
    'active', NULL
);

INSERT INTO news_items(
    id, canonical_key, dedupe_cluster_id, category, source_kind, source_name,
    source_url, source_url_kind, source_item_id, title, summary, language,
    published_at, event_at, collected_at, symbols_json, theme_ids_json,
    impact_scope, impact_direction, impact_rationale, impact_method, confidence,
    raw_payload_id, event_id, content_hash, status, supersedes_id
)
VALUES (
    2, 'synthetic:event:1:v2', 'synthetic-cluster-1', 'taiwan',
    'official_disclosure', 'synthetic_fixture', 'fixture://mops/events/1?revision=2',
    'official', 'synthetic-event-1-revision-2', 'Synthetic dividend disclosure revision',
    'Synthetic superseding news row.', 'zh-Hant',
    '2026-09-09 09:05:00', '2026-09-09 08:30:00', '2026-09-10 08:00:01',
    '["2330"]', '[]', 'instrument', 'unknown', 'fixture only revision',
    'synthetic_fixture', 'unknown', 1, 1,
    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
    'active', 1
);
