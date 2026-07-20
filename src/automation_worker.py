from __future__ import annotations

import datetime as dt
import signal
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .automation import run_all_campaigns
from .config import settings
from .db import get_session, init_db


_running = True


def _stop(_signum, _frame) -> None:
    global _running
    _running = False


def _timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.automation_timezone)
    except ZoneInfoNotFoundError:
        print(
            f"[automation] Zona inválida: {settings.automation_timezone}; usando UTC.",
            flush=True,
        )
        return ZoneInfo("UTC")


def main() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    init_db()

    zone = _timezone()
    last_successful_date: dt.date | None = None
    print(
        (
            "[automation] Worker iniciado. "
            f"enabled={settings.auto_sms_enabled} "
            f"timezone={zone.key} hour={settings.automation_hour:02d}:00"
        ),
        flush=True,
    )

    while _running:
        now = dt.datetime.now(zone)
        should_run = (
            settings.auto_sms_enabled
            and now.hour >= settings.automation_hour
            and last_successful_date != now.date()
        )
        if should_run:
            with get_session() as db:
                summaries = run_all_campaigns(db)
            for summary in summaries:
                print(f"[automation] {summary.to_dict()}", flush=True)
            if summaries and all(summary.ok for summary in summaries):
                last_successful_date = now.date()

        time.sleep(settings.automation_poll_seconds)

    print("[automation] Worker detenido.", flush=True)


if __name__ == "__main__":
    main()
