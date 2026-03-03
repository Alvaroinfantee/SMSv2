from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    # --- App ---
    app_name: str = os.getenv("APP_NAME", "FrontEnd SMS v2")

    # --- Database ---
    database_url: Optional[str] = os.getenv("DATABASE_URL")
    sqlite_path: str = os.getenv("SQLITE_PATH", "./data/app.db")

    # --- SMS API ---
    sms_api_url: str = os.getenv("SMS_API_URL", "https://api.lleida.net/sms/v2/").rstrip("/") + "/"
    sms_api_user: str = os.getenv("SMS_API_USER", "").strip()
    sms_api_password: str = os.getenv("SMS_API_PASSWORD", "").strip()

    # --- Limits ---
    max_bulk_rows: int = int(os.getenv("MAX_BULK_ROWS", "5000"))
    default_sender: str = os.getenv("DEFAULT_SENDER", "").strip()

    # --- Behavior ---
    auto_seed_users: bool = _bool_env("AUTO_SEED_USERS", True)
    seed_users_json: str = os.getenv("SEED_USERS_JSON", "").strip()


settings = Settings()
