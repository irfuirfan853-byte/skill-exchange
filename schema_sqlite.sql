-- ============================================================
--  SKILL EXCHANGE — SQLite Database Schema
--  Zero setup — no MySQL server needed.
--  Run: python setup_sqlite.py
-- ============================================================

-- 1. USERS
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name       TEXT    NOT NULL,
    email           TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    bio             TEXT,
    location        TEXT,
    avatar_path     TEXT,
    last_seen       TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_name ON users(full_name);

-- 2. SKILLS
CREATE TABLE IF NOT EXISTS skills (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    category    TEXT    NOT NULL DEFAULT 'Other',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- 3. USER_SKILLS
CREATE TABLE IF NOT EXISTS user_skills (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL,
    skill_id          INTEGER NOT NULL,
    proficiency       TEXT    NOT NULL DEFAULT 'intermediate'
                      CHECK(proficiency IN ('beginner','intermediate','advanced','expert')),
    years_experience  REAL    NOT NULL DEFAULT 0.0,
    can_teach         INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, skill_id),
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_us_skill ON user_skills(skill_id);

-- 3b. CONNECTION_REQUESTS
CREATE TABLE IF NOT EXISTS connection_requests (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id  INTEGER NOT NULL,
    to_user_id    INTEGER NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'pending'
                  CHECK(status IN ('pending','accepted','declined')),
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    responded_at  TEXT,
    UNIQUE(from_user_id, to_user_id),
    FOREIGN KEY (from_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (to_user_id)   REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_cr_to ON connection_requests(to_user_id, status);

-- 4. EXCHANGES
CREATE TABLE IF NOT EXISTS exchanges (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    initiator_id          INTEGER NOT NULL,
    partner_id            INTEGER NOT NULL,
    message               TEXT,
    learning_period_weeks INTEGER NOT NULL DEFAULT 4,
    status                TEXT    NOT NULL DEFAULT 'pending'
                          CHECK(status IN ('pending','active','completed','cancelled')),
    start_date            TEXT,
    end_date              TEXT,
    created_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at            TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (initiator_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (partner_id)   REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_ex_initiator ON exchanges(initiator_id);
CREATE INDEX IF NOT EXISTS idx_ex_partner   ON exchanges(partner_id);
CREATE INDEX IF NOT EXISTS idx_ex_status    ON exchanges(status);

-- 5. EXCHANGE_SKILLS
CREATE TABLE IF NOT EXISTS exchange_skills (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id      INTEGER NOT NULL,
    teacher_id       INTEGER NOT NULL,
    learner_id       INTEGER NOT NULL,
    skill_id         INTEGER NOT NULL,
    progress_percent INTEGER NOT NULL DEFAULT 0 CHECK(progress_percent >= 0 AND progress_percent <= 100),
    status           TEXT    NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed')),
    completed_at     TEXT,
    UNIQUE(exchange_id, skill_id),
    FOREIGN KEY (exchange_id) REFERENCES exchanges(id) ON DELETE CASCADE,
    FOREIGN KEY (teacher_id)  REFERENCES users(id)     ON DELETE CASCADE,
    FOREIGN KEY (learner_id)  REFERENCES users(id)     ON DELETE CASCADE,
    FOREIGN KEY (skill_id)    REFERENCES skills(id)    ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_es_learner ON exchange_skills(learner_id);
CREATE INDEX IF NOT EXISTS idx_es_teacher ON exchange_skills(teacher_id);

-- 6. EXCHANGE_MESSAGES
CREATE TABLE IF NOT EXISTS exchange_messages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id      INTEGER NOT NULL,
    sender_id        INTEGER NOT NULL,
    message_type     TEXT    NOT NULL DEFAULT 'text'
                     CHECK(message_type IN ('text','file','youtube')),
    content          TEXT,
    file_path        TEXT,
    file_name        TEXT,
    youtube_url      TEXT,
    is_read          INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (exchange_id) REFERENCES exchanges(id) ON DELETE CASCADE,
    FOREIGN KEY (sender_id)   REFERENCES users(id)     ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_msg_exchange ON exchange_messages(exchange_id, created_at);
CREATE INDEX IF NOT EXISTS idx_msg_sender   ON exchange_messages(sender_id);

-- 7. CALLS
CREATE TABLE IF NOT EXISTS calls (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id       INTEGER NOT NULL,
    caller_id         INTEGER NOT NULL,
    callee_id         INTEGER NOT NULL,
    call_type         TEXT    NOT NULL CHECK(call_type IN ('voice','video')),
    started_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    ended_at          TEXT,
    duration_seconds  INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (exchange_id) REFERENCES exchanges(id) ON DELETE CASCADE,
    FOREIGN KEY (caller_id)   REFERENCES users(id)     ON DELETE CASCADE,
    FOREIGN KEY (callee_id)   REFERENCES users(id)     ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_calls_exchange ON calls(exchange_id);

-- 7b. CALL_SIGNALS
CREATE TABLE IF NOT EXISTS call_signals (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    exchange_id  INTEGER NOT NULL,
    sender_id    INTEGER NOT NULL,
    msg_type     TEXT    NOT NULL CHECK(msg_type IN ('offer','answer','candidate')),
    payload      TEXT    NOT NULL,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (exchange_id) REFERENCES exchanges(id) ON DELETE CASCADE,
    FOREIGN KEY (sender_id)   REFERENCES users(id)     ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sig_room ON call_signals(exchange_id, id);

-- 8. CERTIFICATES
CREATE TABLE IF NOT EXISTS certificates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,
    skill_id        INTEGER NOT NULL,
    exchange_id     INTEGER,
    cert_code       TEXT    NOT NULL UNIQUE,
    file_path       TEXT,
    issued_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (user_id)     REFERENCES users(id)       ON DELETE CASCADE,
    FOREIGN KEY (skill_id)    REFERENCES skills(id)      ON DELETE CASCADE,
    FOREIGN KEY (exchange_id) REFERENCES exchanges(id)    ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_cert_user ON certificates(user_id);
