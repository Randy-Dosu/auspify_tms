"""SQLite access layer.

One connection per request (stored on Flask's ``g``), foreign keys enforced,
explicit transactions available for multi-statement writes.

Security notes:
  * ``PRAGMA foreign_keys = ON`` so FK constraints actually apply (SQLite
    silently ignores them otherwise).
  * Every query in this project uses ``?`` placeholders - never string
    formatting - so values are always bound, never executed.
"""

import sqlite3
from contextlib import contextmanager

from flask import current_app, g


def _connect(path: str) -> sqlite3.Connection:
    """Open a configured connection."""
    conn = sqlite3.connect(
        path,
        timeout=10,
        isolation_level=None,  # autocommit; transactions are explicit below
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_db() -> sqlite3.Connection:
    """Return the request-scoped connection, opening it on first use."""
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exc=None) -> None:
    """Close the request-scoped connection (registered as teardown)."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transaction():
    """Explicit write transaction: commit on success, roll back on error.

    Used for multi-statement work such as grading an attempt, so the score and
    the answers can never be saved half-way.
    """
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except Exception:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def init_db(app) -> None:
    """Create tables/indexes if they do not exist yet (idempotent)."""
    with app.app_context():
        db = get_db()
        with app.open_resource("schema.sql") as f:
            db.executescript(f.read().decode("utf-8"))
        # Housekeeping: drop expired blocklist rows.
        db.execute("DELETE FROM token_blocklist WHERE expires_at < datetime('now')")


def init_app(app) -> None:
    """Wire the DB helpers into the app."""
    app.teardown_appcontext(close_db)
    init_db(app)
