from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
from urllib.parse import urljoin

import requests
from dateutil import parser as date_parser

from .config import settings


ENDPOINT_DEFAULTS = {
    "eligible": "/sms/eligible",
    "loan_ending": "/sms/loan-ending",
    "delinquent": "/sms/delinquent",
}

LIST_KEYS = ("data", "results", "items", "customers", "clientes", "records")
CUSTOMER_ID_KEYS = ("customer_id", "cliente_id", "id_cliente", "id")
NAME_KEYS = ("name", "nombre", "customer_name", "nombre_cliente")
PHONE_KEYS = ("phone", "mobile", "msisdn", "telefono", "teléfono", "celular")
SMS_ALLOWED_KEYS = (
    "sms_allowed",
    "sms_eligible",
    "eligible_for_sms",
    "puede_recibir_sms",
    "sms_autorizado",
    "acepta_sms",
)
OPT_OUT_KEYS = ("sms_opt_out", "opt_out", "no_sms", "bloqueo_sms")
LOAN_ID_KEYS = ("loan_id", "prestamo_id", "id_prestamo", "numero_prestamo")
LOAN_END_KEYS = (
    "loan_end_date",
    "maturity_date",
    "fecha_fin_prestamo",
    "fecha_vencimiento",
)
DAYS_PAST_DUE_KEYS = ("days_past_due", "overdue_days", "dias_mora", "días_mora")
DELINQUENCY_START_KEYS = (
    "delinquency_start_date",
    "past_due_since",
    "fecha_inicio_mora",
    "fecha_mora",
)


@dataclass
class CustomerRecord:
    customer_id: str
    name: str
    phone: str
    sms_allowed: bool
    eligibility_explicit: bool
    loan_id: Optional[str] = None
    loan_end_date: Optional[dt.date] = None
    days_past_due: Optional[int] = None
    delinquency_start_date: Optional[dt.date] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class CustomerApiResult:
    ok: bool
    records: list[CustomerRecord] = field(default_factory=list)
    http_status: int = 0
    error: Optional[str] = None


def _first(record: dict[str, Any], keys: Iterable[str]) -> Any:
    lowered = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _as_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "y", "si", "sí", "allowed", "eligible"}:
            return True
        if normalized in {"0", "false", "no", "n", "blocked", "ineligible"}:
            return False
    return None


def _as_date(value: Any) -> Optional[dt.date]:
    if value in (None, ""):
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return date_parser.parse(str(value)).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _as_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def normalize_customer(record: dict[str, Any]) -> CustomerRecord:
    customer_id = str(_first(record, CUSTOMER_ID_KEYS) or "").strip()
    name = str(_first(record, NAME_KEYS) or "cliente").strip() or "cliente"
    phone = str(_first(record, PHONE_KEYS) or "").strip()

    allowed_value = _as_bool(_first(record, SMS_ALLOWED_KEYS))
    opt_out_value = _as_bool(_first(record, OPT_OUT_KEYS))
    eligibility_explicit = allowed_value is not None
    sms_allowed = allowed_value is True and opt_out_value is not True

    return CustomerRecord(
        customer_id=customer_id,
        name=name,
        phone=phone,
        sms_allowed=sms_allowed,
        eligibility_explicit=eligibility_explicit,
        loan_id=str(_first(record, LOAN_ID_KEYS) or "").strip() or None,
        loan_end_date=_as_date(_first(record, LOAN_END_KEYS)),
        days_past_due=_as_int(_first(record, DAYS_PAST_DUE_KEYS)),
        delinquency_start_date=_as_date(_first(record, DELINQUENCY_START_KEYS)),
        raw=record,
    )


def _extract_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []

    for key in LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            nested = _extract_rows(value)
            if nested:
                return nested
    return []


def endpoint_for(kind: str) -> str:
    explicit = {
        "eligible": settings.customer_api_eligible_url,
        "loan_ending": settings.customer_api_loan_ending_url,
        "delinquent": settings.customer_api_delinquent_url,
    }.get(kind, "")
    if explicit:
        if explicit.startswith(("http://", "https://")):
            return explicit
        if settings.customer_api_base_url:
            return urljoin(settings.customer_api_base_url + "/", explicit.lstrip("/"))
        return ""
    if settings.customer_api_base_url and kind in ENDPOINT_DEFAULTS:
        return urljoin(
            settings.customer_api_base_url + "/",
            ENDPOINT_DEFAULTS[kind].lstrip("/"),
        )
    return ""


def customer_api_configured(kind: Optional[str] = None) -> bool:
    if kind:
        return bool(endpoint_for(kind))
    return any(endpoint_for(candidate) for candidate in ENDPOINT_DEFAULTS)


def fetch_customers(kind: str) -> CustomerApiResult:
    url = endpoint_for(kind)
    if not url:
        return CustomerApiResult(
            ok=False,
            error=(
                "Falta configurar CUSTOMER_API_BASE_URL o la URL específica "
                f"para {kind}."
            ),
        )

    headers: dict[str, str] = {"Accept": "application/json"}
    if settings.customer_api_token:
        headers["Authorization"] = f"Bearer {settings.customer_api_token}"
    if settings.customer_api_key:
        headers[settings.customer_api_key_header or "X-API-Key"] = settings.customer_api_key
    if settings.customer_api_headers_json:
        try:
            extra_headers = json.loads(settings.customer_api_headers_json)
            if not isinstance(extra_headers, dict):
                raise ValueError("debe ser un objeto JSON")
            headers.update({str(key): str(value) for key, value in extra_headers.items()})
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return CustomerApiResult(
                ok=False,
                error=f"CUSTOMER_API_HEADERS_JSON inválido: {exc}",
            )

    params: dict[str, Any] = {}
    if kind == "loan_ending":
        params["days"] = settings.loan_ending_days
    elif kind == "delinquent":
        params["min_days"] = settings.delinquent_min_days

    try:
        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=settings.customer_api_timeout_s,
            verify=settings.customer_api_verify_ssl,
        )
    except requests.RequestException as exc:
        return CustomerApiResult(ok=False, error=str(exc))

    if not response.ok:
        return CustomerApiResult(
            ok=False,
            http_status=response.status_code,
            error=f"API de clientes respondió HTTP {response.status_code}: {response.text[:300]}",
        )

    try:
        payload = response.json()
    except ValueError:
        return CustomerApiResult(
            ok=False,
            http_status=response.status_code,
            error="La API de clientes no devolvió JSON válido.",
        )

    rows = _extract_rows(payload)
    records = [normalize_customer(row) for row in rows]
    return CustomerApiResult(
        ok=True,
        records=records,
        http_status=response.status_code,
    )


def eligible_for_campaign(
    record: CustomerRecord,
    kind: str,
    *,
    today: Optional[dt.date] = None,
) -> tuple[bool, str]:
    if not record.eligibility_explicit:
        return False, "La API no confirmó permiso SMS."
    if not record.sms_allowed:
        return False, "Cliente no autorizado para SMS u opt-out activo."
    if not record.customer_id:
        return False, "Falta customer_id."
    if not record.phone:
        return False, "Falta teléfono."

    today = today or dt.date.today()
    if kind == "loan_ending":
        if not record.loan_end_date:
            return False, "Falta fecha de finalización del préstamo."
        days_remaining = (record.loan_end_date - today).days
        if days_remaining < 0 or days_remaining > settings.loan_ending_days:
            return False, "Préstamo fuera de la ventana configurada."
    elif kind == "delinquent":
        if record.days_past_due is None:
            return False, "Faltan días de mora."
        if record.days_past_due < settings.delinquent_min_days:
            return False, "Mora por debajo del mínimo configurado."

    return True, "Elegible"


def customer_to_row(record: CustomerRecord, kind: str) -> dict[str, Any]:
    eligible, reason = eligible_for_campaign(record, kind)
    return {
        "customer_id": record.customer_id,
        "nombre": record.name,
        "telefono": record.phone,
        "sms_autorizado": record.sms_allowed,
        "elegible": eligible,
        "motivo": reason,
        "prestamo_id": record.loan_id or "",
        "fecha_fin_prestamo": record.loan_end_date.isoformat() if record.loan_end_date else "",
        "dias_mora": record.days_past_due,
        "inicio_mora": (
            record.delinquency_start_date.isoformat()
            if record.delinquency_start_date
            else ""
        ),
    }
