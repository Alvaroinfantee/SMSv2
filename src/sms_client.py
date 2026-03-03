from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional

import requests

from .config import settings


class SmsApiError(RuntimeError):
    pass


@dataclass
class SendResult:
    ok: bool
    http_status: int
    api_code: Optional[int] = None
    api_status: Optional[str] = None
    raw: Optional[dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class MtStatus:
    found: bool
    state_code: Optional[int] = None
    state_text: Optional[str] = None
    mt_id: Optional[str] = None
    timestamp: Optional[int] = None
    raw_xml: Optional[str] = None
    error: Optional[str] = None


def generate_base_user_id(prefix: str = "") -> str:
    """Generate an alphanumeric user_id base for internal tracking."""
    p = "".join([c for c in prefix.upper() if c.isalnum()])[:6]
    u = uuid.uuid4().hex  # hex is alphanumeric
    return f"{p}{u}"[:32]  # keep it short


def send_sms(
    dst: str,
    txt: str,
    *,
    src: Optional[str],
    user_id_base: str,
    request_delivery_receipt: bool = False,
    schedule: Optional[str] = None,
    timeout_s: int = 30,
) -> SendResult:
    """Send an SMS using the configured API with user/password payload auth.

    Payload format:
    {
      "sms": {
        "user": "<api_user>",
        "password": "<api_password>",
        "dst": { "num": ["+34600000000"] },
        "txt": "Hello world"
      }
    }
    """
    if not settings.sms_api_user or not settings.sms_api_password:
        return SendResult(ok=False, http_status=0, error="Faltan credenciales (SMS_API_USER / SMS_API_PASSWORD).")

    url = settings.sms_api_url

    # Build payload with user/password in body and dst as array
    payload: dict[str, Any] = {
        "sms": {
            "user": settings.sms_api_user,
            "password": settings.sms_api_password,
            "dst": {
                "num": [dst],
            },
            "txt": txt,
        }
    }

    # Optional fields
    if src:
        payload["sms"]["src"] = src
    if request_delivery_receipt:
        payload["sms"]["delivery_receipt"] = "internalid"
    if schedule:
        payload["sms"]["schedule"] = schedule

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=timeout_s)
    except Exception as e:
        return SendResult(ok=False, http_status=0, error=str(e))

    # Handle problem+json errors (RFC7807 style) if present
    ct = (r.headers.get("Content-Type") or "").lower()
    if "application/problem+json" in ct:
        try:
            problem = r.json()
            detail = problem.get("detail") or problem.get("title") or "API error"
            return SendResult(ok=False, http_status=r.status_code, raw=problem, error=str(detail))
        except Exception:
            return SendResult(ok=False, http_status=r.status_code, error=r.text[:500])

    try:
        data = r.json()
    except Exception:
        return SendResult(ok=False, http_status=r.status_code, error=r.text[:500])

    api_code = data.get("code")
    api_status = data.get("status")
    ok = (r.status_code == 200) and (api_code == 200 or api_code == "200")

    err = None
    if not ok:
        err = f"HTTP {r.status_code} — code={api_code} status={api_status}"
    return SendResult(
        ok=ok,
        http_status=r.status_code,
        api_code=int(api_code) if api_code is not None else None,
        api_status=str(api_status) if api_status is not None else None,
        raw=data,
        error=err,
    )


def query_mt_status_by_user_id(
    provider_user_id_full: str,
    *,
    timeout_s: int = 30,
) -> MtStatus:
    """Query message delivery status.

    NOTE: Status query is not yet configured for the current API.
    This is a stub that returns 'not supported'.
    """
    return MtStatus(
        found=False,
        error="La consulta de estado no está configurada para esta API.",
    )
