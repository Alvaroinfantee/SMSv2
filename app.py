from __future__ import annotations

import datetime as dt
import json
from io import BytesIO
from typing import Optional

import pandas as pd
import streamlit as st
from sqlalchemy import func

from src.automation import automation_preflight, preview_campaign
from src.auth import get_current_user, logout, render_login
from src.config import settings
from src.customer_client import customer_to_row, fetch_customers
from src.db import get_session, init_db
from src.excel_utils import build_messages_from_df, guess_message_column, guess_phone_column, load_excel
from src.models import AuditLog, AutomationEvent, AutomationRun, Campaign, SmsMessage, User
from src.security import hash_password
from src.sms_client import generate_base_user_id, query_mt_status_by_user_id, send_sms
from src.status_utils import normalize_state, status_badge


# --- App init ---
init_db()

st.set_page_config(
    page_title=settings.app_name,
    page_icon="📲",
    layout="wide",
)

# Small CSS tweaks
st.markdown(
    """<style>
    .stTextInput input { font-size: 0.95rem; }
    .stTextArea textarea { font-size: 0.95rem; }
    </style>""",
    unsafe_allow_html=True,
)


def _fmt_dt(d: Optional[dt.datetime]) -> str:
    if not d:
        return ""
    if d.tzinfo is None:
        return d.isoformat(sep=" ", timespec="seconds")
    return d.astimezone(dt.timezone.utc).isoformat(sep=" ", timespec="seconds").replace("+00:00", "Z")


def _require_provider_config() -> bool:
    missing = []
    if not settings.sms_api_user:
        missing.append("SMS_API_USER")
    if not settings.sms_api_password:
        missing.append("SMS_API_PASSWORD")

    if missing:
        st.error(f"Faltan variables de entorno para la API SMS: {', '.join(missing)}")
        st.info("Configúralas en DigitalOcean (App -> Settings -> Environment Variables) o en tu .env local.")
        return False
    return True


def _campaign_summary(db, campaign_id: int) -> pd.DataFrame:
    q = (
        db.query(SmsMessage.status, func.count(SmsMessage.id))
        .filter(SmsMessage.campaign_id == campaign_id)
        .group_by(SmsMessage.status)
        .all()
    )
    df = pd.DataFrame(q, columns=["status", "count"]).sort_values("count", ascending=False)
    return df


def _messages_df(db, campaign_id: int, user: User) -> pd.DataFrame:
    q = db.query(SmsMessage).filter(SmsMessage.campaign_id == campaign_id)
    if user.role != "admin":
        q = q.filter(SmsMessage.owner_user_id == user.id)
    rows = q.order_by(SmsMessage.id.asc()).all()

    data = []
    for m in rows:
        pretty = status_badge(m.status)
        prov = None
        if m.provider_state_code or m.provider_state_text:
            prov = f"{m.provider_state_code or ''} {m.provider_state_text or ''}".strip()
        data.append(
            {
                "id": m.id,
                "fecha": _fmt_dt(m.created_at),
                "dst": m.dst,
                "src": m.src or "",
                "mensaje": m.txt,
                "estado": pretty,
                "estado_proveedor": prov or "",
                "user_id": m.provider_user_id_full,
                "http": m.send_http_status,
                "api_code": m.send_api_code,
                "api_status": m.send_api_status,
                "error": (m.send_error or "")[:200],
                "ultima_consulta": _fmt_dt(m.last_status_check_at),
            }
        )
    return pd.DataFrame(data)


def page_send(db, user: User) -> None:
    st.header("📤 Enviar SMS")

    if not _require_provider_config():
        st.stop()

    tabs = st.tabs(["Individual", "Masivo (Excel)"])

    with tabs[0]:
        st.subheader("Enviar un SMS")
        col1, col2 = st.columns([2, 1], vertical_alignment="top")
        with col1:
            dst = st.text_input("Destino (formato internacional, ej: +34600000000)")
            txt = st.text_area("Mensaje", height=160, placeholder="Escribe tu mensaje...")
        with col2:
            src = st.text_input("Remitente (opcional)", value=settings.default_sender)
            request_dr = st.checkbox("Solicitar acuse de entrega (Delivery Receipt)", value=False)
            schedule = st.text_input("Programar envío (opcional, formato YYYYMMDDhhmm±ZZzz)", value="")
            st.caption("Si no programas, se envía inmediatamente.")

        if st.button("Enviar SMS", type="primary", disabled=not (dst.strip() and txt.strip())):
            campaign = Campaign(
                owner_user_id=user.id,
                name=f"Individual {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                mode="single",
                sender=src.strip() or None,
                request_delivery_receipt=request_dr,
                scheduled_at=None,
            )
            db.add(campaign)
            db.commit()
            base_id = generate_base_user_id(prefix=user.username)
            full_id = f"{base_id}:{dst.strip()}"
            msg = SmsMessage(
                campaign_id=campaign.id,
                owner_user_id=user.id,
                dst=dst.strip(),
                txt=txt.strip(),
                src=src.strip() or None,
                provider_user_id_base=base_id,
                provider_user_id_full=full_id,
                status="created",
            )
            db.add(msg)
            db.commit()
            res = send_sms(
                dst=msg.dst,
                txt=msg.txt,
                src=msg.src,
                user_id_base=base_id,
                request_delivery_receipt=request_dr,
                schedule=schedule.strip() or None,
            )
            msg.send_http_status = res.http_status
            msg.send_api_code = res.api_code
            msg.send_api_status = res.api_status
            msg.send_error = res.error
            msg.status = "submitted" if res.ok else "failed"
            db.commit()
            if res.ok:
                st.success(f"Solicitud enviada. user_id: `{full_id}`")
            else:
                st.error(f"No se pudo enviar: {res.error}")

    with tabs[1]:
        st.subheader("Carga masiva desde Excel")
        st.caption(f"Límite recomendado: {settings.max_bulk_rows} filas.")
        c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
        with c1:
            campaign_name = st.text_input("Nombre de campaña", value=f"Campaña {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}")
        with c2:
            src_bulk = st.text_input("Remitente (opcional)", value=settings.default_sender, key="src_bulk")
        with c3:
            request_dr_bulk = st.checkbox("Delivery Receipt", value=False, key="dr_bulk")
        up = st.file_uploader("Sube tu Excel (.xlsx)", type=["xlsx"])
        if up:
            try:
                df = load_excel(up.getvalue())
            except Exception as e:
                st.error(f"No se pudo leer el Excel: {e}")
                st.stop()
            st.write("Vista previa del archivo:")
            st.dataframe(df.head(20), use_container_width=True)
            cols = list(df.columns)
            phone_guess = guess_phone_column(cols)
            msg_guess = guess_message_column(cols)
            mode = st.radio(
                "Modo",
                options=["Masivo (un texto para todos)", "Personalizado (texto por fila)"],
                index=0 if msg_guess is None else 1,
                horizontal=True,
            )
            phone_col = st.selectbox("Columna de teléfono", options=cols, index=cols.index(phone_guess) if phone_guess in cols else 0)
            message_col = None
            bulk_message = None
            if mode.startswith("Personalizado"):
                message_col = st.selectbox(
                    "Columna de mensaje",
                    options=["(selecciona)"] + cols,
                    index=(1 + cols.index(msg_guess)) if msg_guess in cols else 0,
                )
                if message_col == "(selecciona)":
                    message_col = None
            else:
                bulk_message = st.text_area("Mensaje masivo", height=120)
            items = build_messages_from_df(df, phone_col=phone_col, message_col=message_col, bulk_message=bulk_message)
            total = len(items)
            bad_phone = sum(1 for it in items if it.phone_error)
            bad_msg = sum(1 for it in items if it.message_error)
            st.write("Validación:")
            st.info(f"Filas: {total} • Teléfonos con error: {bad_phone} • Mensajes con error: {bad_msg}")
            preview_df = pd.DataFrame(
                [
                    {
                        "row": it.row_index,
                        "phone": it.phone,
                        "phone_error": it.phone_error or "",
                        "message": it.message[:80],
                        "message_error": it.message_error or "",
                    }
                    for it in items[:50]
                ]
            )
            st.dataframe(preview_df, use_container_width=True)
            if total > settings.max_bulk_rows:
                st.warning(f"El archivo tiene {total} filas y supera MAX_BULK_ROWS={settings.max_bulk_rows}.")
            can_send = total > 0 and total <= settings.max_bulk_rows and bad_phone == 0 and bad_msg == 0
            if st.button("Enviar campaña", type="primary", disabled=not can_send):
                campaign = Campaign(
                    owner_user_id=user.id,
                    name=campaign_name.strip() or "Campaña",
                    mode="bulk",
                    sender=src_bulk.strip() or None,
                    request_delivery_receipt=request_dr_bulk,
                    scheduled_at=None,
                )
                db.add(campaign)
                db.commit()
                progress = st.progress(0)
                status_ph = st.empty()
                ok_count = 0
                fail_count = 0
                for idx, it in enumerate(items, start=1):
                    base_id = generate_base_user_id(prefix=user.username)
                    full_id = f"{base_id}:{it.phone}"
                    msg = SmsMessage(
                        campaign_id=campaign.id,
                        owner_user_id=user.id,
                        dst=it.phone,
                        txt=it.message,
                        src=src_bulk.strip() or None,
                        provider_user_id_base=base_id,
                        provider_user_id_full=full_id,
                        status="created",
                    )
                    db.add(msg)
                    db.commit()
                    res = send_sms(
                        dst=msg.dst,
                        txt=msg.txt,
                        src=msg.src,
                        user_id_base=base_id,
                        request_delivery_receipt=request_dr_bulk,
                    )
                    msg.send_http_status = res.http_status
                    msg.send_api_code = res.api_code
                    msg.send_api_status = res.api_status
                    msg.send_error = res.error
                    msg.status = "submitted" if res.ok else "failed"
                    db.commit()
                    if res.ok:
                        ok_count += 1
                    else:
                        fail_count += 1
                    progress.progress(idx / total)
                    status_ph.write(f"Enviando {idx}/{total} • OK: {ok_count} • Fallos: {fail_count}")
                st.success(f"Campaña enviada. OK: {ok_count} • Fallos: {fail_count} • Campaña ID: {campaign.id}")


def page_history(db, user: User) -> None:
    st.header("📊 Historial y estados")
    q = db.query(Campaign)
    if user.role != "admin":
        q = q.filter(Campaign.owner_user_id == user.id)
    campaigns = q.order_by(Campaign.created_at.desc()).limit(200).all()
    if not campaigns:
        st.info("Aún no hay campañas para mostrar.")
        return
    options = {f"[{c.id}] {c.name} — {_fmt_dt(c.created_at)}": c.id for c in campaigns}
    label = st.selectbox("Selecciona una campaña", options=list(options.keys()))
    campaign_id = options[label]
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if not campaign:
        st.error("Campaña no encontrada.")
        return
    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        st.metric("Campaña ID", campaign.id)
        st.caption(f"Modo: {campaign.mode}")
    with col2:
        st.metric("Delivery Receipt", "Sí" if campaign.request_delivery_receipt else "No")
        st.caption(f"Remitente: {campaign.sender or '(vacío)'}")
    with col3:
        st.caption(f"Creada: {_fmt_dt(campaign.created_at)}")
        st.caption(f"Última sincronización: {_fmt_dt(campaign.last_sync_at)}")
    summary_df = _campaign_summary(db, campaign.id)
    if not summary_df.empty:
        st.dataframe(summary_df, use_container_width=True)
    st.divider()
    a1, a2, a3 = st.columns([1, 1, 2], vertical_alignment="center")
    with a1:
        only_pending = st.checkbox("Actualizar solo pendientes / desconocidos", value=True)
    with a2:
        do_sync = st.button("🔄 Actualizar estados desde la API")
    if do_sync:
        if not _require_provider_config():
            st.stop()
        qmsg = db.query(SmsMessage).filter(SmsMessage.campaign_id == campaign.id)
        if user.role != "admin":
            qmsg = qmsg.filter(SmsMessage.owner_user_id == user.id)
        if only_pending:
            qmsg = qmsg.filter(SmsMessage.status.in_(["submitted", "pending", "unknown", "created"]))
        msgs = qmsg.order_by(SmsMessage.id.asc()).all()
        if not msgs:
            st.info("No hay mensajes para actualizar con esos filtros.")
        else:
            prog = st.progress(0)
            ph = st.empty()
            updated = 0
            for i, m in enumerate(msgs, start=1):
                st_res = query_mt_status_by_user_id(m.provider_user_id_full)
                m.last_status_check_at = dt.datetime.now(dt.timezone.utc)
                if st_res.found:
                    m.provider_state_code = st_res.state_code
                    m.provider_state_text = st_res.state_text
                    norm, _label = normalize_state(st_res.state_code, st_res.state_text)
                    m.status = norm
                    updated += 1
                elif m.status in {"submitted", "created"}:
                    m.status = "unknown"
                db.commit()
                prog.progress(i / len(msgs))
                ph.write(f"Actualizando {i}/{len(msgs)} • actualizados: {updated}")
            campaign.last_sync_at = dt.datetime.now(dt.timezone.utc)
            db.commit()
            st.success(f"Actualización completada. Mensajes consultados: {len(msgs)}")
    st.divider()
    df = _messages_df(db, campaign.id, user)
    st.dataframe(df, use_container_width=True, height=520)
    b1, b2, b3 = st.columns([1, 1, 2], vertical_alignment="center")
    with b1:
        st.download_button(
            "⬇️ Exportar CSV",
            data=df.to_csv(index=False).encode("utf-8"),
            file_name=f"campaign_{campaign.id}_messages.csv",
            mime="text/csv",
        )
    with b2:
        bio = BytesIO()
        with pd.ExcelWriter(bio, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="messages", index=False)
        st.download_button(
            "⬇️ Exportar Excel",
            data=bio.getvalue(),
            file_name=f"campaign_{campaign.id}_messages.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    if user.role == "admin":
        st.divider()
        if st.button("🗑️ Eliminar campaña (admin)", type="secondary"):
            db.delete(campaign)
            db.commit()
            st.success("Campaña eliminada.")
            st.rerun()


def _render_customer_query(kind: str, title: str, help_text: str) -> None:
    st.subheader(title)
    st.caption(help_text)
    state_key = f"customer_api_result_{kind}"
    if st.button("Consultar API", key=f"query_{kind}", type="primary"):
        with st.spinner("Consultando clientes..."):
            result = fetch_customers(kind)
        if result.ok:
            rows = [customer_to_row(record, kind) for record in result.records]
            st.session_state[state_key] = {"ok": True, "rows": rows, "http_status": result.http_status}
        else:
            st.session_state[state_key] = {"ok": False, "error": result.error or "No se pudo consultar la API."}
    state = st.session_state.get(state_key)
    if not state:
        st.info("Pulsa **Consultar API** para cargar la información actual.")
        return
    if not state.get("ok"):
        st.error(state.get("error", "No se pudo consultar la API."))
        return
    df = pd.DataFrame(state.get("rows", []))
    if df.empty:
        st.warning("La API respondió correctamente, pero no devolvió clientes.")
        return
    total = len(df)
    eligible = int(df["elegible"].fillna(False).sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("Consultados", total)
    c2.metric("Elegibles", eligible)
    c3.metric("No elegibles", total - eligible)
    st.dataframe(df, use_container_width=True, height=480)
    st.download_button(
        "⬇️ Exportar consulta (CSV)",
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=f"clientes_sms_{kind}_{dt.date.today().isoformat()}.csv",
        mime="text/csv",
        key=f"download_{kind}",
    )
    st.caption(
        "La app aplica una regla de seguridad: si la API no confirma expresamente "
        "el permiso para SMS, el cliente se marca como no elegible."
    )


def page_customer_automation(db, user: User) -> None:
    st.header("👥 Clientes SMS y automatización")
    st.write(
        "Consulta por API quién puede recibir SMS y revisa las campañas automáticas "
        "de préstamos por finalizar y clientes morosos."
    )
    tabs = st.tabs(["Elegibilidad SMS", "Préstamos por finalizar", "Morosos", "Automatización"])
    with tabs[0]:
        _render_customer_query(
            "eligible",
            "Clientes autorizados para SMS",
            "Consulta la autorización vigente directamente en la API de clientes.",
        )
    with tabs[1]:
        _render_customer_query(
            "loan_ending",
            "Clientes cuyo préstamo está por finalizar",
            f"Ventana configurada: próximos {settings.loan_ending_days} días. Solo se consideran clientes con permiso SMS confirmado.",
        )
        st.markdown("**Plantilla automática**")
        st.code(settings.loan_ending_template, language=None)
    with tabs[2]:
        _render_customer_query(
            "delinquent",
            "Clientes morosos",
            f"Mora mínima configurada: {settings.delinquent_min_days} día(s). Solo se consideran clientes con permiso SMS confirmado.",
        )
        st.markdown("**Plantilla automática**")
        st.code(settings.delinquent_template, language=None)
    with tabs[3]:
        c1, c2, c3 = st.columns(3)
        c1.metric("Envío automático", "Activo" if settings.auto_sms_enabled else "Desactivado")
        c2.metric("Hora diaria", f"{settings.automation_hour:02d}:00")
        c3.metric("Zona horaria", settings.automation_timezone)
        preflight_errors = automation_preflight(db)
        if settings.auto_sms_enabled and not preflight_errors:
            st.success("La automatización está lista. El worker ejecuta ambas campañas una vez al día y evita duplicados por cliente/episodio.")
        elif preflight_errors:
            st.warning("La automatización no enviará mensajes hasta resolver:")
            for error in preflight_errors:
                st.write(f"- {error}")
        else:
            st.info("La automatización está desplegada en modo seguro y desactivada. Actívala con `AUTO_SMS_ENABLED=true` después de configurar y validar la API.")
        st.caption("Para producción se requiere `DATABASE_URL` persistente. SQLite en App Platform no garantiza deduplicación después de un redeploy.")
        if user.role == "admin":
            if st.button("Simular campañas ahora (no envía SMS)"):
                with st.spinner("Consultando API y aplicando reglas..."):
                    previews = [preview_campaign("loan_ending"), preview_campaign("delinquent")]
                st.session_state["automation_previews"] = [preview.to_dict() for preview in previews]
            previews = st.session_state.get("automation_previews")
            if previews:
                st.dataframe(pd.DataFrame(previews), use_container_width=True)
        else:
            st.caption("La simulación y configuración están disponibles para administradores.")
        st.divider()
        st.subheader("Últimas ejecuciones")
        runs = db.query(AutomationRun).order_by(AutomationRun.started_at.desc()).limit(50).all()
        if runs:
            df_runs = pd.DataFrame(
                [
                    {
                        "fecha": _fmt_dt(run.started_at),
                        "tipo": run.campaign_type,
                        "estado": run.status,
                        "consultados": run.fetched_count,
                        "elegibles": run.eligible_count,
                        "enviados": run.sent_count,
                        "fallos": run.failed_count,
                        "omitidos": run.skipped_count,
                        "error": run.error or "",
                    }
                    for run in runs
                ]
            )
            st.dataframe(df_runs, use_container_width=True, height=320)
        else:
            st.info("Aún no hay ejecuciones automáticas.")
        if user.role == "admin" and st.checkbox("Mostrar eventos de deduplicación"):
            events = db.query(AutomationEvent).order_by(AutomationEvent.created_at.desc()).limit(200).all()
            df_events = pd.DataFrame(
                [
                    {
                        "fecha": _fmt_dt(event.created_at),
                        "tipo": event.campaign_type,
                        "cliente": event.customer_id,
                        "prestamo": event.loan_id or "",
                        "telefono": event.phone,
                        "estado": event.status,
                        "motivo": event.reason or "",
                    }
                    for event in events
                ]
            )
            st.dataframe(df_events, use_container_width=True, height=360)


def page_account(db, user: User) -> None:
    st.header("👤 Mi cuenta")
    st.write(
        {
            "username": user.username,
            "department": user.department,
            "role": user.role,
            "created_at": _fmt_dt(user.created_at),
        }
    )
    st.subheader("Cambiar contraseña")
    with st.form("change_pwd"):
        p1 = st.text_input("Nueva contraseña", type="password")
        p2 = st.text_input("Repetir nueva contraseña", type="password")
        ok = st.form_submit_button("Actualizar contraseña")
    if ok:
        if not p1 or len(p1) < 8:
            st.error("Usa una contraseña de al menos 8 caracteres.")
        elif p1 != p2:
            st.error("Las contraseñas no coinciden.")
        else:
            user.password_hash = hash_password(p1)
            db.commit()
            st.success("Contraseña actualizada.")


def page_admin(db, user: User) -> None:
    st.header("🛠️ Administración")
    if user.role != "admin":
        st.error("No tienes permisos para ver esta sección.")
        return
    st.subheader("Usuarios")
    users = db.query(User).order_by(User.created_at.desc()).all()
    df_users = pd.DataFrame(
        [
            {
                "id": u.id,
                "username": u.username,
                "department": u.department,
                "role": u.role,
                "active": u.is_active,
                "created_at": _fmt_dt(u.created_at),
            }
            for u in users
        ]
    )
    st.dataframe(df_users, use_container_width=True, height=320)
    st.subheader("Logs de Conexión (Audit)")
    if st.checkbox("Mostrar logs de auditoría"):
        logs = (
            db.query(AuditLog, User.username)
            .outerjoin(User, AuditLog.user_id == User.id)
            .order_by(AuditLog.created_at.desc())
            .limit(500)
            .all()
        )
        data_logs = []
        for log, uname in logs:
            data_logs.append(
                {
                    "fecha": _fmt_dt(log.created_at),
                    "usuario": uname or f"ID {log.user_id}" if log.user_id else "anon",
                    "acción": log.action,
                    "detalle": log.detail or "",
                    "ip": log.ip or "",
                }
            )
        df_logs = pd.DataFrame(data_logs)
        st.dataframe(df_logs, use_container_width=True, height=400)
        st.download_button(
            "⬇️ Descargar Logs (CSV)",
            data=df_logs.to_csv(index=False).encode("utf-8"),
            file_name=f"audit_logs_{dt.datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
    st.markdown("### Crear usuario")
    with st.form("create_user"):
        c1, c2, c3 = st.columns(3)
        with c1:
            new_username = st.text_input("username (minúsculas)", value="")
            new_department = st.text_input("department", value="General")
        with c2:
            new_role = st.selectbox("role", options=["user", "admin"], index=0)
        with c3:
            new_password = st.text_input("password", type="password", value="")
            create = st.form_submit_button("Crear")
    if create:
        uname = new_username.strip().lower()
        if not uname or not new_password:
            st.error("Username y password son obligatorios.")
        elif db.query(User).filter(User.username == uname).first():
            st.error("Ya existe un usuario con ese username.")
        else:
            u = User(
                username=uname,
                password_hash=hash_password(new_password),
                department=new_department.strip() or "General",
                role=new_role,
                is_active=True,
            )
            db.add(u)
            db.commit()
            st.success("Usuario creado.")
            st.rerun()
    st.markdown("### Gestionar usuario existente")
    user_map = {f"[{u.id}] {u.username}": u.id for u in users}
    sel = st.selectbox("Selecciona usuario", options=list(user_map.keys()))
    sel_user = db.query(User).filter(User.id == user_map[sel]).first()
    if not sel_user:
        return
    with st.form("manage_user"):
        c1, c2, c3 = st.columns(3)
        with c1:
            dep = st.text_input("department", value=sel_user.department)
            role = st.selectbox("role", options=["user", "admin"], index=0 if sel_user.role == "user" else 1)
        with c2:
            active = st.checkbox("activo", value=sel_user.is_active)
        with c3:
            reset_pwd = st.text_input("reset password (opcional)", type="password", value="")
        save = st.form_submit_button("Guardar cambios")
    if save:
        sel_user.department = dep.strip() or "General"
        sel_user.role = role
        sel_user.is_active = bool(active)
        if reset_pwd:
            sel_user.password_hash = hash_password(reset_pwd)
        db.commit()
        st.success("Cambios guardados.")
        st.rerun()


def main():
    with get_session() as db:
        user = get_current_user(db)
        if not user:
            render_login(db)
            return
        st.sidebar.title("📲 FrontEnd SMS v2")
        st.sidebar.caption(f"Usuario: **{user.username}**  •  Área: **{user.department}**")
        st.sidebar.caption(f"Rol: `{user.role}`")
        page = st.sidebar.radio(
            "Menú",
            options=["Enviar", "Clientes SMS", "Historial", "Mi cuenta"]
            + (["Admin"] if user.role == "admin" else []),
            index=0,
        )
        if st.sidebar.button("Cerrar sesión"):
            logout(db)
            st.rerun()
        if page == "Enviar":
            page_send(db, user)
        elif page == "Clientes SMS":
            page_customer_automation(db, user)
        elif page == "Historial":
            page_history(db, user)
        elif page == "Mi cuenta":
            page_account(db, user)
        elif page == "Admin":
            page_admin(db, user)


if __name__ == "__main__":
    main()
