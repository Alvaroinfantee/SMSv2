from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


# Based on Lleida.net Messages API "State filter possible values"
# Numeric codes are used in MT responses (e.g., <state code="3">Sent</state>).
STATE_CODE_TO_LABEL = {
    1: "New",
    2: "Pending",
    3: "Sent",
    4: "Delivered",
    5: "Buffered",
    6: "Failed",
    7: "Invalid",
    8: "Cancelled",
    9: "Scheduled",
    10: "Expired",
    11: "Deleted",
    12: "Undeliverable",
    13: "Unknown",
    14: "Received",
    15: "Notified",
    16: "Waiting",
    17: "Processed",
    18: "Processing",
}


FINAL_CODES = {4, 6, 7, 8, 10, 11, 12}
PENDING_CODES = {1, 2, 5, 9, 16, 18, 17}
SENT_CODES = {3, 15}
UNKNOWN_CODES = {13}


def normalize_state(code: Optional[int], text: Optional[str]) -> Tuple[str, str]:
    """Return (normalized_status, pretty_label)."""
    if code is None:
        return "unknown", text or "Unknown"

    label = text or STATE_CODE_TO_LABEL.get(code, f"Code {code}")

    if code in FINAL_CODES:
        if code == 4:
            return "delivered", label
        return "failed", label
    if code in SENT_CODES:
        return "sent", label
    if code in PENDING_CODES:
        return "pending", label
    return "unknown", label


def status_badge(status: str) -> str:
    return {
        "created": "🟦 created",
        "submitted": "🟦 submitted",
        "pending": "🟨 pending",
        "sent": "🟩 sent",
        "delivered": "✅ delivered",
        "failed": "⛔ failed",
        "unknown": "❓ unknown",
    }.get(status, status)
