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


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


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

    # --- Customer / loan API ---
    customer_api_base_url: str = os.getenv("CUSTOMER_API_BASE_URL", "").strip().rstrip("/")
    customer_api_eligible_url: str = os.getenv("CUSTOMER_API_ELIGIBLE_URL", "").strip()
    customer_api_loan_ending_url: str = os.getenv("CUSTOMER_API_LOAN_ENDING_URL", "").strip()
    customer_api_delinquent_url: str = os.getenv("CUSTOMER_API_DELINQUENT_URL", "").strip()
    customer_api_token: str = os.getenv("CUSTOMER_API_TOKEN", "").strip()
    customer_api_key: str = os.getenv("CUSTOMER_API_KEY", "").strip()
    customer_api_key_header: str = os.getenv("CUSTOMER_API_KEY_HEADER", "X-API-Key").strip()
    customer_api_headers_json: str = os.getenv("CUSTOMER_API_HEADERS_JSON", "").strip()
    customer_api_timeout_s: int = _int_env("CUSTOMER_API_TIMEOUT_S", 30)
    customer_api_verify_ssl: bool = _bool_env("CUSTOMER_API_VERIFY_SSL", True)

    # --- Automated campaigns ---
    auto_sms_enabled: bool = _bool_env("AUTO_SMS_ENABLED", False)
    allow_ephemeral_automation: bool = _bool_env("ALLOW_EPHEMERAL_AUTOMATION", False)
    automation_timezone: str = os.getenv("AUTOMATION_TIMEZONE", "America/Santo_Domingo").strip()
    automation_hour: int = min(23, max(0, _int_env("AUTOMATION_HOUR", 9)))
    automation_poll_seconds: int = max(60, _int_env("AUTOMATION_POLL_SECONDS", 300))
    automation_username: str = os.getenv("AUTOMATION_USERNAME", "admin").strip().lower()
    loan_ending_days: int = max(0, _int_env("LOAN_ENDING_DAYS", 30))
    delinquent_min_days: int = max(1, _int_env("DELINQUENT_MIN_DAYS", 1))
    loan_ending_template: str = os.getenv(
        "LOAN_ENDING_SMS_TEMPLATE",
        (
            "Hola {name}, tu préstamo está próximo a finalizar. "
            "Tenemos opciones para ti. Contáctanos en Banco Fihogar."
        ),
    ).strip()
    delinquent_template: str = os.getenv(
        "DELINQUENT_SMS_TEMPLATE",
        (
            "Hola {name}, tienes un pago pendiente con Banco Fihogar. "
            "Por favor contáctanos para regularizar tu préstamo."
        ),
    ).strip()

    # --- Behavior ---
    auto_seed_users: bool = _bool_env("AUTO_SEED_USERS", True)
    seed_users_json: str = os.getenv("SEED_USERS_JSON", "").strip()


settings = Settings()
