-- ============================================================
--  SKILL EXCHANGE — MySQL Database Schema
--  Run this ONCE to create the database and all tables:
--      mysql -u root -p < schema.sql
--  It is safe to run again (tables are dropped first).
-- ============================================================

-- Wipes any previous/leftover schema and starts fresh.
-- Only run this on a database you don't need to keep!
DROP DATABASE IF EXISTS skill_exchange;
CREATE DATABASE skill_exchange
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE skill_exchange;

-- ------------------------------------------------------------
-- 1. USERS — everyone who signs up
-- ------------------------------------------------------------
CREATE TABLE users (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    full_name       VARCHAR(100)  NOT NULL,
    email           VARCHAR(190)  NOT NULL UNIQUE,
    password_hash   VARCHAR(255)  NOT NULL,           -- Werkzeug pbkdf2 hash
    bio             TEXT          NULL,               -- short "about me"
    location        VARCHAR(120)  NULL,
    avatar_path     VARCHAR(255)  NULL,               -- uploaded profile picture
    last_seen       DATETIME      NULL,               -- online/offline presence
    created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                  ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_users_name (full_name)   -- speeds up profile search (LIKE)
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 2. SKILLS — the global catalog shown in every dropdown
--    (name is unique; seeded by seed_skills.sql)
-- ------------------------------------------------------------
CREATE TABLE skills (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,   -- UNIQUE also serves as the search index
    category    VARCHAR(60)  NOT NULL DEFAULT 'Other',
    created_at  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 3. USER_SKILLS — what each user knows / can teach
-- ------------------------------------------------------------
CREATE TABLE user_skills (
    id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id           INT UNSIGNED NOT NULL,
    skill_id          INT UNSIGNED NOT NULL,
    proficiency       ENUM('beginner','intermediate','advanced','expert')
                      NOT NULL DEFAULT 'intermediate',
    years_experience  DECIMAL(3,1) NOT NULL DEFAULT 0.0,
    can_teach         TINYINT(1)   NOT NULL DEFAULT 1,   -- 1 = willing to teach this skill
    created_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_skill (user_id, skill_id),
    KEY idx_skill (skill_id),
    CONSTRAINT fk_us_user  FOREIGN KEY (user_id)  REFERENCES users (id)  ON DELETE CASCADE,
    CONSTRAINT fk_us_skill FOREIGN KEY (skill_id) REFERENCES skills (id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 3b. CONNECTION_REQUESTS — the "Connect" button flow between members
-- ------------------------------------------------------------
CREATE TABLE connection_requests (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    from_user_id  INT UNSIGNED NOT NULL,               -- who sent the request
    to_user_id    INT UNSIGNED NOT NULL,               -- who receives it
    status        ENUM('pending','accepted','declined') NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    responded_at  TIMESTAMP NULL,
    UNIQUE KEY uq_pair (from_user_id, to_user_id),
    KEY idx_to_user (to_user_id, status),
    CONSTRAINT fk_cr_from FOREIGN KEY (from_user_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_cr_to   FOREIGN KEY (to_user_id)   REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 4. EXCHANGES — a give-and-take pairing between two people.
--    Person A teaches skill X to B, while B teaches skill Y to A.
-- ------------------------------------------------------------
CREATE TABLE exchanges (
    id                    INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    initiator_id          INT UNSIGNED NOT NULL,        -- who created the exchange request
    partner_id            INT UNSIGNED NOT NULL,        -- the other person
    message               TEXT          NULL,           -- "I want to learn X, I can teach Y"
    learning_period_weeks INT UNSIGNED NOT NULL DEFAULT 4,
    status                ENUM('pending','active','completed','cancelled')
                          NOT NULL DEFAULT 'pending',
    start_date            DATE          NULL,
    end_date              DATE          NULL,
    created_at            TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at            TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
                                         ON UPDATE CURRENT_TIMESTAMP,
    KEY idx_initiator (initiator_id),
    KEY idx_partner (partner_id),
    KEY idx_status (status),
    CONSTRAINT fk_ex_initiator FOREIGN KEY (initiator_id) REFERENCES users (id) ON DELETE CASCADE,
    CONSTRAINT fk_ex_partner   FOREIGN KEY (partner_id)   REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 5. EXCHANGE_SKILLS — one row per direction of an exchange.
--    Tracks who teaches what to whom, and the learner's progress %.
--    This powers the dashboard: "learning" vs "teaching" progress.
-- ------------------------------------------------------------
CREATE TABLE exchange_skills (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    exchange_id      INT UNSIGNED NOT NULL,
    teacher_id       INT UNSIGNED NOT NULL,             -- the one teaching
    learner_id       INT UNSIGNED NOT NULL,             -- the one learning
    skill_id         INT UNSIGNED NOT NULL,
    progress_percent TINYINT UNSIGNED NOT NULL DEFAULT 0 CHECK (progress_percent <= 100),
    status           ENUM('active','completed') NOT NULL DEFAULT 'active',
    completed_at     TIMESTAMP NULL,
    UNIQUE KEY uq_exchange_skill (exchange_id, skill_id),
    KEY idx_learner (learner_id),
    KEY idx_teacher (teacher_id),
    CONSTRAINT fk_es_exchange FOREIGN KEY (exchange_id) REFERENCES exchanges (id) ON DELETE CASCADE,
    CONSTRAINT fk_es_teacher  FOREIGN KEY (teacher_id)  REFERENCES users (id)     ON DELETE CASCADE,
    CONSTRAINT fk_es_learner  FOREIGN KEY (learner_id)  REFERENCES users (id)     ON DELETE CASCADE,
    CONSTRAINT fk_es_skill    FOREIGN KEY (skill_id)    REFERENCES skills (id)    ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 6. EXCHANGE_MESSAGES — chat, file sharing & YouTube references
-- ------------------------------------------------------------
CREATE TABLE exchange_messages (
    id               INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    exchange_id      INT UNSIGNED NOT NULL,
    sender_id        INT UNSIGNED NOT NULL,
    message_type     ENUM('text','file','youtube') NOT NULL DEFAULT 'text',
    content          TEXT          NULL,                -- chat text
    file_path        VARCHAR(255)  NULL,               -- uploaded file (stored in app)
    file_name        VARCHAR(255)  NULL,               -- original file name for download
    youtube_url      VARCHAR(500)  NULL,               -- shared YouTube reference
    is_read          TINYINT(1)    NOT NULL DEFAULT 0,
    created_at       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_exchange_time (exchange_id, created_at),   -- chat history reads in time order
    KEY idx_sender (sender_id),
    CONSTRAINT fk_msg_exchange FOREIGN KEY (exchange_id) REFERENCES exchanges (id) ON DELETE CASCADE,
    CONSTRAINT fk_msg_sender   FOREIGN KEY (sender_id)   REFERENCES users (id)     ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 7. CALLS — history of voice / video calls inside an exchange
-- ------------------------------------------------------------
CREATE TABLE calls (
    id                INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    exchange_id       INT UNSIGNED NOT NULL,
    caller_id         INT UNSIGNED NOT NULL,
    callee_id         INT UNSIGNED NOT NULL,
    call_type         ENUM('voice','video') NOT NULL,
    started_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at          TIMESTAMP NULL,
    duration_seconds  INT UNSIGNED NOT NULL DEFAULT 0,
    KEY idx_exchange (exchange_id),
    KEY idx_caller (caller_id),
    CONSTRAINT fk_call_exchange FOREIGN KEY (exchange_id) REFERENCES exchanges (id) ON DELETE CASCADE,
    CONSTRAINT fk_call_caller   FOREIGN KEY (caller_id)   REFERENCES users (id)     ON DELETE CASCADE,
    CONSTRAINT fk_call_callee   FOREIGN KEY (callee_id)   REFERENCES users (id)     ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 7b. CALL_SIGNALS — WebRTC signaling (offer/answer/ICE) per exchange room
-- ------------------------------------------------------------
CREATE TABLE call_signals (
    id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    exchange_id  INT UNSIGNED NOT NULL,                -- room = the exchange
    sender_id    INT UNSIGNED NOT NULL,
    msg_type     ENUM('offer','answer','candidate') NOT NULL,
    payload      TEXT NOT NULL,                        -- JSON: {sdp} or {candidate}
    created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_sig_room (exchange_id, id),
    CONSTRAINT fk_sig_exchange FOREIGN KEY (exchange_id) REFERENCES exchanges (id) ON DELETE CASCADE,
    CONSTRAINT fk_sig_sender   FOREIGN KEY (sender_id)   REFERENCES users (id)     ON DELETE CASCADE
) ENGINE=InnoDB;

-- ------------------------------------------------------------
-- 8. CERTIFICATES — issued when a learner completes a skill.
--    Shown on the profile as proof of the known skill.
-- ------------------------------------------------------------
CREATE TABLE certificates (
    id              INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id         INT UNSIGNED NOT NULL,
    skill_id        INT UNSIGNED NOT NULL,
    exchange_id     INT UNSIGNED NULL,                  -- which exchange it came from
    cert_code       VARCHAR(40)  NOT NULL UNIQUE,       -- e.g. SE-2026-XXXXXX
    file_path       VARCHAR(255) NULL,                  -- uploaded certificate image/PDF
    issued_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    KEY idx_user (user_id),
    CONSTRAINT fk_cert_user     FOREIGN KEY (user_id)     REFERENCES users (id)   ON DELETE CASCADE,
    CONSTRAINT fk_cert_skill    FOREIGN KEY (skill_id)    REFERENCES skills (id)  ON DELETE CASCADE,
    CONSTRAINT fk_cert_exchange FOREIGN KEY (exchange_id) REFERENCES exchanges (id) ON DELETE SET NULL
) ENGINE=InnoDB;
