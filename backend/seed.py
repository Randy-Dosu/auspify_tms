"""Seed the database with one admin, one teacher and three students.

Passwords come from the environment (backend/.env) - they are never written
into this file. If a password is missing, a random one is generated and
printed once so the account is still usable.

Run:  cd backend && .venv/bin/python seed.py
"""

import os
import secrets
import sys

from app import create_app
from app.db import get_db
from app.security import hash_password, to_iso, utcnow

# (full_name, email_env, email_default, password_env, role)
ACCOUNTS = [
    ("System Administrator", "SEED_ADMIN_EMAIL", "admin@auspify.test", "SEED_ADMIN_PASSWORD", "admin"),
    ("Grace Mensah", "SEED_TEACHER_EMAIL", "teacher@auspify.test", "SEED_TEACHER_PASSWORD", "teacher"),
    ("Kofi Boateng", "SEED_STUDENT1_EMAIL", "student1@auspify.test", "SEED_STUDENT_PASSWORD", "student"),
    ("Ama Owusu", "SEED_STUDENT2_EMAIL", "student2@auspify.test", "SEED_STUDENT_PASSWORD", "student"),
    ("Yaw Darko", "SEED_STUDENT3_EMAIL", "student3@auspify.test", "SEED_STUDENT_PASSWORD", "student"),
]


def upsert_user(db, full_name: str, email: str, password: str, role: str) -> str:
    """Create the account, or reset its password/role if it already exists."""
    email = email.strip().lower()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        db.execute(
            "UPDATE users SET full_name = ?, password_hash = ?, role = ?, is_active = 1,"
            " failed_login_attempts = 0, locked_until = NULL WHERE id = ?",
            (full_name, hash_password(password), role, existing["id"]),
        )
        return "updated"
    db.execute(
        """
        INSERT INTO users (full_name, email, password_hash, role, is_active, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (full_name, email, hash_password(password), role, to_iso(utcnow())),
    )
    return "created"


def main() -> int:
    app = create_app()
    if app.config["ENV_NAME"] == "production" and os.environ.get("ALLOW_PROD_SEED") != "1":
        print("Refusing to seed a production database (set ALLOW_PROD_SEED=1 to override).")
        return 1

    generated = []
    with app.app_context():
        db = get_db()
        print(f"Seeding {len(ACCOUNTS)} accounts into {app.config['DATABASE_PATH']}\n")
        for full_name, email_env, email_default, password_env, role in ACCOUNTS:
            email = os.environ.get(email_env, email_default)
            password = os.environ.get(password_env)
            if not password:
                password = secrets.token_urlsafe(9)
                generated.append((email, password))
            action = upsert_user(db, full_name, email, password, role)
            print(f"  {action:8s} {role:7s} {email}")

    print("\nDone.")
    if generated:
        print("\nGenerated passwords (store them now, they are not saved in plain text):")
        for email, password in generated:
            print(f"  {email}: {password}")
    else:
        print("Passwords were read from the environment (SEED_* variables in backend/.env).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
