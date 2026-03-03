from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import pandas as pd


PHONE_COL_CANDIDATES = [
    "phone",
    "telefono",
    "teléfono",
    "msisdn",
    "movil",
    "móvil",
    "celular",
    "mobile",
    "numero",
    "número",
    "dst",
    "to",
]

MESSAGE_COL_CANDIDATES = [
    "message",
    "mensaje",
    "txt",
    "texto",
    "text",
    "body",
]


def guess_phone_column(columns: list[str]) -> Optional[str]:
    lower = {c.lower(): c for c in columns}
    for cand in PHONE_COL_CANDIDATES:
        if cand in lower:
            return lower[cand]
    return None


def guess_message_column(columns: list[str]) -> Optional[str]:
    lower = {c.lower(): c for c in columns}
    for cand in MESSAGE_COL_CANDIDATES:
        if cand in lower:
            return lower[cand]
    return None


_phone_cleanup = re.compile(r"[\s\-\(\)\.]+")


def normalize_phone(value: object) -> str:
    """Normalize a phone number best-effort.

    - Keeps leading '+'
    - Removes spaces, hyphens, parentheses, dots
    - Converts leading '00' to '+'
    """
    s = "" if value is None else str(value).strip()
    s = _phone_cleanup.sub("", s)

    # If Excel interprets as float/int, it may come like '34600000000.0'
    if s.endswith(".0"):
        s = s[:-2]

    if s.startswith("00"):
        s = "+" + s[2:]
    elif s and not s.startswith("+"):
        s = "+" + s
    return s


def validate_phone(phone: str) -> Optional[str]:
    if not phone:
        return "Vacío"
    if phone.startswith("+"):
        digits = phone[1:]
    else:
        digits = phone
    if not digits.isdigit():
        return "Debe contener solo dígitos (y opcional '+')"
    if len(digits) < 8:
        return "Demasiado corto"
    if len(digits) > 18:
        return "Demasiado largo"
    return None


@dataclass
class RowMessage:
    row_index: int
    phone: str
    message: str
    phone_error: Optional[str] = None
    message_error: Optional[str] = None


def load_excel(file_bytes: bytes) -> pd.DataFrame:
    df = pd.read_excel(file_bytes, engine="openpyxl")
    # make columns strings
    df.columns = [str(c).strip() for c in df.columns]
    return df


def build_messages_from_df(
    df: pd.DataFrame,
    phone_col: str,
    message_col: Optional[str],
    bulk_message: Optional[str],
) -> list[RowMessage]:
    items: list[RowMessage] = []

    for i, row in df.iterrows():
        phone_raw = row.get(phone_col)
        phone = normalize_phone(phone_raw)
        phone_err = validate_phone(phone)

        if message_col:
            msg_raw = row.get(message_col)
            msg = "" if msg_raw is None else str(msg_raw)
        else:
            msg = bulk_message or ""

        msg = str(msg).strip()
        msg_err = None
        if not msg:
            msg_err = "Mensaje vacío"
        # Note: SMS length limits depend on encoding; we don't hard-fail here.

        items.append(RowMessage(row_index=int(i), phone=phone, message=msg, phone_error=phone_err, message_error=msg_err))
    return items
