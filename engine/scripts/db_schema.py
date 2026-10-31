from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS modules (
    module_id TEXT PRIMARY KEY,
    module_no INTEGER NOT NULL UNIQUE,
    category TEXT NOT NULL,
    module_name TEXT NOT NULL,
    official_title TEXT,
    official_url TEXT,
    requires_login TEXT NOT NULL DEFAULT 'UNKNOWN',
    core_points TEXT,
    common_question_types TEXT,
    retrieval_path TEXT,
    key_fields TEXT,
    common_traps TEXT,
    sample_question_ids TEXT,
    dynamicity TEXT NOT NULL DEFAULT 'SEMI_DYNAMIC'
        CHECK (dynamicity IN ('STATIC', 'SEMI_DYNAMIC', 'DYNAMIC')),
    browser_automation TEXT,
    manual_method TEXT,
    source_notes TEXT,
    last_synced_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platforms (
    platform_id TEXT PRIMARY KEY,
    platform_name TEXT NOT NULL,
    official_url TEXT,
    login_required TEXT NOT NULL DEFAULT 'UNKNOWN',
    route TEXT,
    allowed_automation TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_id TEXT PRIMARY KEY,
    source_priority INTEGER NOT NULL DEFAULT 7,
    source_type TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    source_date TEXT,
    access_status TEXT NOT NULL DEFAULT 'UNKNOWN',
    access_notes TEXT,
    raw_path TEXT,
    sha256 TEXT,
    url_hash TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id TEXT PRIMARY KEY,
    year TEXT,
    track TEXT,
    source_type TEXT,
    category TEXT,
    module_id TEXT,
    module_name TEXT,
    question_type TEXT,
    question_text TEXT NOT NULL,
    option_a TEXT,
    option_b TEXT,
    option_c TEXT,
    option_d TEXT,
    -- Three answer tiers that must never be conflated:
    --   standard_answer    INDEPENDENT : independently verified against an
    --                                   authoritative official source
    --   mock_key           MOCK_KEY    : the answer key shipped with the three
    --                                   2026 simulation sets (P0 for
    --                                   original-question matching only)
    --   provisional_answer PROVISIONAL: derived by this project itself
    standard_answer TEXT,
    mock_key TEXT,
    provisional_answer TEXT,
    answer_explanation TEXT,
    official_platform TEXT,
    official_url TEXT,
    retrieval_path TEXT,
    retrieval_query TEXT,
    retrieval_fields TEXT,
    retrieval_filters TEXT,
    question_stability TEXT NOT NULL DEFAULT 'SEMI_DYNAMIC'
        CHECK (question_stability IN ('STATIC', 'SEMI_DYNAMIC', 'DYNAMIC')),
    current_observed_value TEXT,
    observed_at TEXT,
    confidence TEXT NOT NULL DEFAULT 'LOW',
    source_priority INTEGER NOT NULL DEFAULT 7,
    verification_status TEXT NOT NULL DEFAULT 'UNVERIFIED'
        CHECK (verification_status IN (
            'OFFICIAL_ANSWER',
            'VERIFIED_OFFICIAL',
            'VERIFIED_PRIMARY',
            'MOCK_KEY',
            'PROVISIONAL',
            'NEEDS_HUMAN',
            'UNVERIFIED'
        )),
    verified_at TEXT,
    notes TEXT,
    normalized_question TEXT NOT NULL,
    question_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (module_id) REFERENCES modules(module_id)
);

CREATE TABLE IF NOT EXISTS raw_records (
    record_id TEXT PRIMARY KEY,
    source_id TEXT,
    source_row_no INTEGER,
    question_id TEXT,
    source_url TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_id) REFERENCES sources(source_id),
    FOREIGN KEY (question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS question_sources (
    question_id TEXT NOT NULL,
    source_id TEXT,
    raw_record_id TEXT,
    relation_type TEXT NOT NULL DEFAULT 'source_record',
    is_primary INTEGER NOT NULL DEFAULT 0,
    source_url TEXT,
    source_answer TEXT,
    source_explanation TEXT,
    source_date TEXT,
    notes TEXT,
    PRIMARY KEY (question_id, source_id, raw_record_id),
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
    FOREIGN KEY (source_id) REFERENCES sources(source_id),
    FOREIGN KEY (raw_record_id) REFERENCES raw_records(record_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id TEXT,
    attempt_id TEXT,
    source_id TEXT,
    evidence_type TEXT NOT NULL,
    url TEXT,
    captured_at TEXT NOT NULL,
    local_path TEXT,
    page_or_locator TEXT,
    key_text TEXT,
    observed_value TEXT,
    notes TEXT,
    FOREIGN KEY (question_id) REFERENCES questions(id),
    FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    track TEXT,
    expected_count INTEGER,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    started_at TEXT NOT NULL,
    completed_at TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id TEXT PRIMARY KEY,
    session_id TEXT,
    question_id TEXT,
    raw_question_text TEXT NOT NULL,
    raw_options_json TEXT,
    provisional_answer TEXT,
    final_answer TEXT,
    confidence TEXT NOT NULL DEFAULT 'LOW',
    retrieval_path TEXT,
    retrieval_query TEXT,
    retrieval_fields TEXT,
    retrieval_filters TEXT,
    verification_status TEXT NOT NULL DEFAULT 'PROVISIONAL',
    result TEXT CHECK (result IN ('CORRECT', 'INCORRECT', 'UNRESOLVED')),
    error_reason TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
    FOREIGN KEY (question_id) REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS answer_reconciliations (
    reconciliation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id TEXT,
    question_id TEXT,
    provisional_answer TEXT,
    standard_answer TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN ('CORRECT', 'INCORRECT', 'UNRESOLVED')),
    error_reason TEXT,
    reconciled_at TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (attempt_id) REFERENCES attempts(attempt_id),
    FOREIGN KEY (question_id) REFERENCES questions(id)
);

-- Platform routing: answers "where do I go to check this question?" so a new
-- question never needs a fresh search for its entry point.
CREATE TABLE IF NOT EXISTS question_routes (
    question_id TEXT NOT NULL,
    platform_key TEXT NOT NULL,
    official_platform TEXT,
    official_url TEXT,
    deep_link TEXT,
    retrieval_recipe TEXT,
    manual_recipe TEXT,
    requires_login TEXT NOT NULL DEFAULT 'UNKNOWN',
    manual_only INTEGER NOT NULL DEFAULT 0,
    route_source TEXT NOT NULL DEFAULT 'official_urls',
    route_confidence TEXT NOT NULL DEFAULT 'LOW',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (question_id, platform_key),
    FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_routes_question ON question_routes(question_id);
CREATE INDEX IF NOT EXISTS idx_routes_platform ON question_routes(platform_key);
CREATE INDEX IF NOT EXISTS idx_questions_hash ON questions(question_hash);
CREATE INDEX IF NOT EXISTS idx_questions_normalized ON questions(normalized_question);
CREATE INDEX IF NOT EXISTS idx_questions_module ON questions(module_id);
CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(verification_status);
CREATE INDEX IF NOT EXISTS idx_questions_priority ON questions(source_priority);
CREATE INDEX IF NOT EXISTS idx_raw_question ON raw_records(question_id);
CREATE INDEX IF NOT EXISTS idx_attempt_session ON attempts(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_question ON evidence(question_id);
"""


FTS_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS questions_fts USING fts5(
    id UNINDEXED,
    question_text,
    option_text,
    tokenize = 'unicode61'
);

CREATE TRIGGER IF NOT EXISTS questions_fts_ai AFTER INSERT ON questions BEGIN
    INSERT INTO questions_fts(id, question_text, option_text)
    VALUES (
        new.id,
        new.question_text,
        trim(coalesce(new.option_a, '') || ' ' || coalesce(new.option_b, '') || ' ' ||
             coalesce(new.option_c, '') || ' ' || coalesce(new.option_d, ''))
    );
END;

CREATE TRIGGER IF NOT EXISTS questions_fts_au AFTER UPDATE OF question_text, option_a, option_b, option_c, option_d ON questions BEGIN
    DELETE FROM questions_fts WHERE id = old.id;
    INSERT INTO questions_fts(id, question_text, option_text)
    VALUES (
        new.id,
        new.question_text,
        trim(coalesce(new.option_a, '') || ' ' || coalesce(new.option_b, '') || ' ' ||
             coalesce(new.option_c, '') || ' ' || coalesce(new.option_d, ''))
    );
END;

CREATE TRIGGER IF NOT EXISTS questions_fts_ad AFTER DELETE ON questions BEGIN
    DELETE FROM questions_fts WHERE id = old.id;
END;
"""


def connect_db(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    try:
        conn.executescript(FTS_SCHEMA_SQL)
    except sqlite3.OperationalError:
        # Some system SQLite builds omit FTS5. Core matching still works via
        # the normal hash/normalized indexes; preflight reports this clearly.
        pass
    conn.commit()


def fts_available(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='questions_fts'"
    ).fetchone())


def rebuild_fts(conn: sqlite3.Connection) -> bool:
    if not fts_available(conn):
        return False
    conn.execute("DELETE FROM questions_fts")
    conn.execute(
        """
        INSERT INTO questions_fts(id, question_text, option_text)
        SELECT id, question_text,
               trim(coalesce(option_a, '') || ' ' || coalesce(option_b, '') || ' ' ||
                    coalesce(option_c, '') || ' ' || coalesce(option_d, ''))
        FROM questions
        """
    )
    return True
