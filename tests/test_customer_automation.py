from __future__ import annotations

import datetime as dt
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.automation import build_event_key, render_customer_message, run_campaign
from src.customer_client import eligible_for_campaign, normalize_customer
from src.models import AutomationRun, Base


class CustomerEligibilityTests(unittest.TestCase):
    def test_missing_sms_permission_fails_closed(self) -> None:
        record = normalize_customer(
            {
                "customer_id": "C-1",
                "name": "Ana",
                "phone": "+18095550101",
            }
        )
        eligible, reason = eligible_for_campaign(record, "eligible")
        self.assertFalse(eligible)
        self.assertIn("no confirmó", reason)

    def test_opt_out_overrides_sms_permission(self) -> None:
        record = normalize_customer(
            {
                "id_cliente": "C-2",
                "nombre": "Luis",
                "celular": "+18095550102",
                "puede_recibir_sms": "sí",
                "no_sms": True,
            }
        )
        eligible, _reason = eligible_for_campaign(record, "eligible")
        self.assertFalse(eligible)

    def test_loan_ending_window_and_delinquency_threshold(self) -> None:
        today = dt.date(2026, 7, 20)
        ending = normalize_customer(
            {
                "cliente_id": "C-3",
                "telefono": "+18095550103",
                "sms_autorizado": True,
                "fecha_fin_prestamo": "2026-07-30",
            }
        )
        eligible, _reason = eligible_for_campaign(
            ending,
            "loan_ending",
            today=today,
        )
        self.assertTrue(eligible)

        delinquent = normalize_customer(
            {
                "cliente_id": "C-4",
                "telefono": "+18095550104",
                "sms_autorizado": True,
                "dias_mora": 5,
            }
        )
        eligible, _reason = eligible_for_campaign(
            delinquent,
            "delinquent",
            today=today,
        )
        self.assertTrue(eligible)


class AutomationSafetyTests(unittest.TestCase):
    def test_event_key_is_stable_for_same_loan_episode(self) -> None:
        record = normalize_customer(
            {
                "customer_id": "C-5",
                "loan_id": "P-99",
                "phone": "+18095550105",
                "sms_allowed": True,
                "loan_end_date": "2026-08-01",
            }
        )
        first = build_event_key(record, "loan_ending")
        second = build_event_key(record, "loan_ending")
        self.assertEqual(first, second)
        self.assertNotIn(record.phone, first)

    def test_template_renders_without_exposing_missing_values(self) -> None:
        record = normalize_customer(
            {
                "customer_id": "C-6",
                "name": "María",
                "phone": "+18095550106",
                "sms_allowed": True,
            }
        )
        message = render_customer_message(record, "delinquent")
        self.assertIn("María", message)
        self.assertNotIn("{", message)

    def test_api_failure_marks_run_failed_instead_of_running_forever(self) -> None:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            summary = run_campaign(
                db,
                "loan_ending",
                run_date=dt.date(2026, 7, 20),
            )
            run = db.query(AutomationRun).one()
            self.assertFalse(summary.ok)
            self.assertEqual(run.status, "failed")


if __name__ == "__main__":
    unittest.main()
