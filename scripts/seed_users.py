"""Seed users into the DB.

Usage:
  python scripts/seed_users.py --users seed_users.example.json

This script is optional; the app can also seed on startup using SEED_USERS_JSON env var.
"""

from __future__ import annotations

import argparse
import json

from src.db import get_session, init_db
from src.models import User
from src.security import hash_password


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--users", required=True, help="Path to JSON list of users.")
    args = ap.parse_args()

    init_db()

    with open(args.users, "r", encoding="utf-8") as f:
        users = json.load(f)
    if not isinstance(users, list):
        raise SystemExit("Users file must be a JSON list.")

    with get_session() as db:
        for u in users:
            username = str(u.get("username", "")).strip().lower()
            password = str(u.get("password", "")).strip()
            if not username or not password:
                continue
            if db.query(User).filter(User.username == username).first():
                print(f"Skipping existing user: {username}")
                continue
            db.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    department=str(u.get("department", "General")).strip(),
                    role=str(u.get("role", "user")).strip().lower(),
                    is_active=True,
                )
            )
        db.commit()
    print("Done.")


if __name__ == "__main__":
    main()
