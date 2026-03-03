from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Iterable, Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base, User
from .security import hash_password


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    if settings.database_url:
        url = settings.database_url
        # Heroku-style URLs may come as postgres://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        return create_engine(url, pool_pre_ping=True)
    # SQLite
    sqlite_path = settings.sqlite_path
    # Ensure directory exists
    os.makedirs(os.path.dirname(sqlite_path) or ".", exist_ok=True)
    return create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), autocommit=False, autoflush=False, expire_on_commit=False)


def get_session() -> Session:
    return get_session_factory()()


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)

    if not settings.auto_seed_users:
        return

    # Seed users only if DB is empty
    with get_session() as db:
        has_any_user = db.query(User).limit(1).first() is not None
        if has_any_user:
            return

        if settings.seed_users_json:
            try:
                users = json.loads(settings.seed_users_json)
                if not isinstance(users, list):
                    raise ValueError("SEED_USERS_JSON must be a JSON list.")
            except Exception as e:
                raise RuntimeError(f"Invalid SEED_USERS_JSON: {e}") from e
            _seed_users(db, users)
            db.commit()
            return

        # Safe-ish defaults for first run (CHANGE THESE ASAP)
        defaults = [
            {"username": "admin", "password": "admin", "department": "Admin", "role": "admin"},
            {"username": "vladimir", "password": "vladimir", "department": "Negocios", "role": "user"},
            {"username": "lisaura", "password": "lisaura", "department": "Legal", "role": "user"},
        ]
        _seed_users(db, defaults)
        db.commit()


def _seed_users(db: Session, users: Iterable[dict]) -> None:
    for u in users:
        username = str(u.get("username", "")).strip().lower()
        password = str(u.get("password", "")).strip()
        department = str(u.get("department", "General")).strip()
        role = str(u.get("role", "user")).strip().lower()

        if not username or not password:
            continue

        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                department=department,
                role=role,
                is_active=True,
            )
        )
