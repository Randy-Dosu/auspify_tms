-- ---------------------------------------------------------------------------
-- Online Examination System - SQLite schema
--
-- Step 1: users + token blocklist
-- Later steps append exams/questions/options/attempts/answers.
--
-- Conventions:
--   * timestamps are UTC ISO-8601 strings ("2026-11-06T19:20:00+00:00")
--   * booleans are INTEGER 0/1 (SQLite has no boolean type)
--   * every foreign key is declared so PRAGMA foreign_keys=ON enforces it
-- ---------------------------------------------------------------------------

-- Users ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name               TEXT    NOT NULL,
    email                   TEXT    NOT NULL,             -- stored lower-cased
    password_hash           TEXT    NOT NULL,             -- bcrypt, never plain text
    role                    TEXT    NOT NULL
                              CHECK (role IN ('admin', 'teacher', 'student')),
    is_active               INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    failed_login_attempts   INTEGER NOT NULL DEFAULT 0,
    locked_until            TEXT,                          -- UTC ISO-8601 or NULL
    created_at              TEXT    NOT NULL
);

-- Unique index on email (also prevents duplicate registrations).
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users (email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users (role);

-- Revoked JWTs --------------------------------------------------------------
-- Logout inserts the token's jti here; every request checks it, so a token
-- cannot be replayed after logout even though JWTs are stateless.
CREATE TABLE IF NOT EXISTS token_blocklist (
    jti         TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    expires_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_blocklist_expires ON token_blocklist (expires_at);

-- Exams ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS exams (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    title            TEXT    NOT NULL,
    description      TEXT    NOT NULL DEFAULT '',
    subject          TEXT    NOT NULL DEFAULT '',
    duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0),
    total_marks      REAL    NOT NULL DEFAULT 0,   -- recomputed from questions
    pass_marks       REAL    NOT NULL DEFAULT 0,
    start_time       TEXT,                          -- UTC ISO-8601 or NULL (open)
    end_time         TEXT,                          -- UTC ISO-8601 or NULL (open)
    is_published     INTEGER NOT NULL DEFAULT 0 CHECK (is_published IN (0, 1)),
    allow_retakes    INTEGER NOT NULL DEFAULT 0 CHECK (allow_retakes IN (0, 1)),
    created_by       INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    created_at       TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exams_created_by ON exams (created_by);
CREATE INDEX IF NOT EXISTS idx_exams_published ON exams (is_published);

-- Questions -----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS questions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id        INTEGER NOT NULL REFERENCES exams (id) ON DELETE CASCADE,
    question_text  TEXT    NOT NULL,
    question_type  TEXT    NOT NULL
                     CHECK (question_type IN ('single_choice', 'multiple_choice', 'true_false')),
    marks          REAL    NOT NULL CHECK (marks > 0),
    negative_marks REAL    NOT NULL DEFAULT 0 CHECK (negative_marks >= 0),
    position       INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_questions_exam ON questions (exam_id);

-- Options -------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS options (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions (id) ON DELETE CASCADE,
    option_text TEXT    NOT NULL,
    is_correct  INTEGER NOT NULL DEFAULT 0 CHECK (is_correct IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_options_question ON options (question_id);

-- Attempts ------------------------------------------------------------------
-- One row per student per exam (unless the exam allows retakes, enforced in
-- the API layer inside a transaction).
CREATE TABLE IF NOT EXISTS attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    exam_id      INTEGER NOT NULL REFERENCES exams (id) ON DELETE CASCADE,
    student_id   INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    started_at   TEXT    NOT NULL,
    submitted_at TEXT,
    status       TEXT    NOT NULL DEFAULT 'in_progress'
                   CHECK (status IN ('in_progress', 'submitted', 'expired')),
    score        REAL,
    percentage   REAL,
    passed       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_attempts_exam ON attempts (exam_id);
CREATE INDEX IF NOT EXISTS idx_attempts_student ON attempts (student_id);
CREATE INDEX IF NOT EXISTS idx_attempts_exam_student ON attempts (exam_id, student_id);

-- Answers -------------------------------------------------------------------
-- selected_option_ids is a JSON array of option ids (1..6 entries).
CREATE TABLE IF NOT EXISTS answers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id          INTEGER NOT NULL REFERENCES attempts (id) ON DELETE CASCADE,
    question_id         INTEGER NOT NULL REFERENCES questions (id) ON DELETE CASCADE,
    selected_option_ids TEXT    NOT NULL DEFAULT '[]',
    is_correct          INTEGER,
    marks_awarded       REAL,
    UNIQUE (attempt_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_answers_attempt ON answers (attempt_id);
CREATE INDEX IF NOT EXISTS idx_answers_question ON answers (question_id);
