from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import asdict, dataclass
from typing import Iterable, Optional

from sqlalchemy.orm import Session

from .config import settings
from .customer_client import (
    CustomerRecord,
    customer_api_configured,
    eligible_for_campaign,
    fetch_customers,
)
from .models import (
    AuditLog,
    AutomationEvent,
    AutomationRun,
    Campaign,
    SmsMessage,
    User,
)
from .sms_client import generate_base_user_id, send_sms


CAMPAIGN_TYPES = ("loan_ending", "delinquent")


@dataclass
class AutomationSummary:
    campaign_type: str
    ok: bool
    dry_run: bool
    fetched: int = 0
    eligible: int = 0
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class _TemplateValues(dict):
    def __missing__(self, key: str) -> str:
        return ""


def render_customer_message(record: CustomerRecord, campaign_type: str) -> str:
    template = (
        settings.loan_ending_template
        if campaign_type == "loan_ending"
        else settings.delinquent_template
    )
    values = _TemplateValues(
        name=record.name or "cliente",
        customer_id=record.customer_id,
        loan_id=record.loan_id or "",
        loan_end_date=record.loan_end_date.isoformat() if record.loan_end_date else "",
        days_past_due=(
            str(record.days_past_due)
            if record.days_past_due is not None
            else ""
        ),
    )
    return template.format_map(values).strip()


def build_event_key(record: CustomerRecord, campaign_type: str) -> str:
    if campaign_type == "loan_ending":
        episode = (
            record.loan_end_date.isoformat()
            if record.loan_end_date
            else (record.loan_id or "sin-fecha")
        )
    else:
        episode = (
            record.delinquency_start_date.isoformat()
            if record.delinquency_start_date
            else (record.loan_id or "mora-actual")
        )
    source = "|".join(
        [
            campaign_type,
            record.customer_id,
            record.loan_id or "",
            episode,
        ]
    )
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
    return f"{campaign_type}:{digest}"


def automation_preflight(db: Session) -> list[str]:
    errors: list[str] = []
    if not settings.sms_api_user or not settings.sms_api_password:
        errors.append("Faltan SMS_API_USER / SMS_API_PASSWORD.")
    for campaign_type in CAMPAIGN_TYPES:
        if not customer_api_configured(campaign_type):
            errors.append(f"Falta el endpoint de clientes para {campaign_type}.")
    if not settings.database_url and not settings.allow_ephemeral_automation:
        errors.append(
            "La automatización requiere DATABASE_URL persistente. "
            "SQLite en App Platform puede reiniciarse y provocar duplicados."
        )
    user = (
        db.query(User)
        .filter(
            User.username == settings.automation_username,
            User.is_active == True,  # noqa: E712
        )
        .first()
    )
    if not user:
        errors.append(
            f"No existe el usuario activo AUTOMATION_USERNAME={settings.automation_username}."
        )
    return errors


def _run_key(campaign_type: str, run_date: dt.date) -> str:
    return f"{campaign_type}:{run_date.isoformat()}"


def _campaign_label(campaign_type: str, run_date: dt.date) -> str:
    label = "Préstamos por finalizar" if campaign_type == "loan_ending" else "Morosos"
    return f"Automática · {label} · {run_date.isoformat()}"


def _eligible_records(
    records: Iterable[CustomerRecord],
    campaign_type: str,
    today: dt.date,
) -> tuple[list[CustomerRecord], int]:
    eligible: list[CustomerRecord] = []
    skipped = 0
    for record in records:
        ok, _reason = eligible_for_campaign(record, campaign_type, today=today)
        if ok:
            eligible.append(record)
        else:
            skipped += 1
    return eligible, skipped


def preview_campaign(campaign_type: str) -> AutomationSummary:
    api_result = fetch_customers(campaign_type)
    if not api_result.ok:
        return AutomationSummary(
            campaign_type=campaign_type,
            ok=False,
            dry_run=True,
            error=api_result.error,
        )
    eligible, skipped = _eligible_records(
        api_result.records,
        campaign_type,
        dt.date.today(),
    )
    return AutomationSummary(
        campaign_type=campaign_type,
        ok=True,
        dry_run=True,
        fetched=len(api_result.records),
        eligible=len(eligible),
        skipped=skipped,
    )


def run_campaign(
    db: Session,
    campaign_type: str,
    *,
    run_date: Optional[dt.date] = None,
) -> AutomationSummary:
    if campaign_type not in CAMPAIGN_TYPES:
        return AutomationSummary(
            campaign_type=campaign_type,
            ok=False,
            dry_run=False,
            error="Tipo de campaña no soportado.",
        )

    run_date = run_date or dt.date.today()
    run_key = _run_key(campaign_type, run_date)
    previous = db.query(AutomationRun).filter(AutomationRun.run_key == run_key).first()
    if previous and previous.status in {"completed", "running"}:
        return AutomationSummary(
            campaign_type=campaign_type,
            ok=True,
            dry_run=False,
            skipped=previous.skipped_count + previous.eligible_count,
            error="La campaña automática de hoy ya fue procesada.",
        )

    run = previous or AutomationRun(
        run_key=run_key,
        campaign_type=campaign_type,
        status="running",
    )
    if not previous:
        db.add(run)
    else:
        run.status = "running"
        run.error = None
    db.commit()

    summary = AutomationSummary(
        campaign_type=campaign_type,
        ok=False,
        dry_run=False,
    )
    try:
        api_result = fetch_customers(campaign_type)
        if not api_result.ok:
            raise RuntimeError(api_result.error or "No se pudo consultar la API de clientes.")

        summary.fetched = len(api_result.records)
        eligible, summary.skipped = _eligible_records(
            api_result.records,
            campaign_type,
            run_date,
        )
        summary.eligible = len(eligible)

        owner = (
            db.query(User)
            .filter(
                User.username == settings.automation_username,
                User.is_active == True,  # noqa: E712
            )
            .first()
        )
        if not owner:
            raise RuntimeError(
                f"Usuario de automatización no disponible: {settings.automation_username}"
            )

        pending: list[tuple[CustomerRecord, str]] = []
        for record in eligible:
            event_key = build_event_key(record, campaign_type)
            existing = (
                db.query(AutomationEvent)
                .filter(AutomationEvent.event_key == event_key)
                .first()
            )
            if existing:
                summary.skipped += 1
                continue
            pending.append((record, event_key))

        campaign: Optional[Campaign] = None
        if pending:
            campaign = Campaign(
                owner_user_id=owner.id,
                name=_campaign_label(campaign_type, run_date),
                mode=f"auto_{campaign_type}",
                sender=settings.default_sender or None,
                request_delivery_receipt=False,
                scheduled_at=None,
            )
            db.add(campaign)
            db.commit()

        for record, event_key in pending:
            message_text = render_customer_message(record, campaign_type)
            event = AutomationEvent(
                event_key=event_key,
                campaign_type=campaign_type,
                customer_id=record.customer_id,
                loan_id=record.loan_id,
                phone=record.phone,
                status="created",
                campaign_id=campaign.id if campaign else None,
            )
            db.add(event)
            db.commit()

            base_id = generate_base_user_id(prefix=f"AUTO{campaign_type[:2]}")
            full_id = f"{base_id}:{record.phone}"
            message = SmsMessage(
                campaign_id=campaign.id,
                owner_user_id=owner.id,
                dst=record.phone,
                txt=message_text,
                src=settings.default_sender or None,
                provider_user_id_base=base_id,
                provider_user_id_full=full_id,
                status="created",
            )
            db.add(message)
            db.commit()
            event.message_id = message.id
            db.commit()

            result = send_sms(
                dst=message.dst,
                txt=message.txt,
                src=message.src,
                user_id_base=base_id,
                request_delivery_receipt=False,
            )
            message.send_http_status = result.http_status
            message.send_api_code = result.api_code
            message.send_api_status = result.api_status
            message.send_error = result.error
            message.status = "submitted" if result.ok else "failed"
            event.status = "submitted" if result.ok else "failed"
            event.reason = result.error
            if result.ok:
                summary.sent += 1
            else:
                summary.failed += 1
            db.commit()

        summary.ok = summary.failed == 0
        run.status = "completed" if summary.ok else "completed_with_errors"
    except Exception as exc:
        summary.error = str(exc)
        db.rollback()
        run = db.query(AutomationRun).filter(AutomationRun.run_key == run_key).first()
        if not run:
            run = AutomationRun(
                run_key=run_key,
                campaign_type=campaign_type,
            )
            db.add(run)
        run.status = "failed"
        run.error = summary.error
    finally:
        run.fetched_count = summary.fetched
        run.eligible_count = summary.eligible
        run.sent_count = summary.sent
        run.failed_count = summary.failed
        run.skipped_count = summary.skipped
        run.finished_at = dt.datetime.now(dt.timezone.utc)
        db.commit()

    db.add(
        AuditLog(
            user_id=None,
            action=f"automation_{campaign_type}",
            detail=str(summary.to_dict()),
            ip=None,
        )
    )
    db.commit()
    return summary


def run_all_campaigns(db: Session) -> list[AutomationSummary]:
    preflight_errors = automation_preflight(db)
    if preflight_errors:
        error = " ".join(preflight_errors)
        return [
            AutomationSummary(
                campaign_type=campaign_type,
                ok=False,
                dry_run=False,
                error=error,
            )
            for campaign_type in CAMPAIGN_TYPES
        ]
    return [run_campaign(db, campaign_type) for campaign_type in CAMPAIGN_TYPES]
