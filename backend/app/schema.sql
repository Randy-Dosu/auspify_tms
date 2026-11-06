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
