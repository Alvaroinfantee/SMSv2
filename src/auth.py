from __future__ import annotations

from typing import Optional, Tuple

import streamlit as st
from sqlalchemy.orm import Session

from .config import settings
from .models import AuditLog, User
from .security import verify_password


def get_client_ip() -> Optional[str]:
    """Best-effort client IP detection behind proxies.

    We do NOT use IP allowlists in this simplified version (you mentioned you'll
    restrict access at the network/VPC level), but keeping IP in audit logs can
    still be useful.
    """
    headers = {}
    try:
        # Streamlit >= ~1.30
        headers = dict(st.context.headers)  # type: ignore[attr-defined]
    except Exception:
        pass

    if not headers:
        try:
            # Streamlit internal API (may change)
            from streamlit.web.server.websocket_headers import _get_websocket_headers  # type: ignore

            headers = _get_websocket_headers() or {}
        except Exception:
            headers = {}

    def _get(h: str) -> Optional[str]:
        for k in (h, h.lower(), h.upper()):
            if k in headers:
                v = headers.get(k)
                if v:
                    return str(v)
        return None

    xff = _get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()

    xri = _get("X-Real-IP")
    if xri:
        return xri.strip()

    return None


def log_audit(db: Session, action: str, detail: str | None = None, user_id: int | None = None) -> None:
    ip = get_client_ip()
    db.add(AuditLog(user_id=user_id, action=action, detail=detail, ip=ip))
    db.commit()


def get_current_user(db: Session) -> Optional[User]:
    uid = st.session_state.get("auth_user_id")
    if not uid:
        return None
    return db.query(User).filter(User.id == int(uid), User.is_active == True).first()  # noqa: E712


def logout(db: Session) -> None:
    u = get_current_user(db)
    if u:
        log_audit(db, "logout", user_id=u.id)
    st.session_state.pop("auth_user_id", None)
    st.session_state.pop("auth_username", None)
    st.session_state.pop("auth_role", None)
    st.session_state.pop("auth_department", None)


def _attempt_login(db: Session, username: str, password: str) -> Tuple[bool, str]:
    username = username.strip().lower()
    user = db.query(User).filter(User.username == username, User.is_active == True).first()  # noqa: E712
    if not user:
        return False, "Usuario no existe o está desactivado."

    if not password or not verify_password(password, user.password_hash):
        return False, "Credenciales inválidas."

    # success
    st.session_state["auth_user_id"] = user.id
    st.session_state["auth_username"] = user.username
    st.session_state["auth_role"] = user.role
    st.session_state["auth_department"] = user.department

    log_audit(db, "login", user_id=user.id)
    return True, "OK"


def render_login(db: Session) -> None:
    st.title(settings.app_name)
    st.subheader("Iniciar sesión")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Usuario", value=st.session_state.get("auth_username", ""))
        password = st.text_input("Contraseña", type="password")
        submitted = st.form_submit_button("Entrar")

    if submitted:
        ok, msg = _attempt_login(db, username, password)
        if ok:
            st.success("Sesión iniciada.")
            st.rerun()
        else:
            st.error(msg)

    st.info(
        "Si es el primer arranque y no existe ningún usuario en la base de datos, "
        "se crean usuarios por defecto (admin/vladimir/lisaura). Cambia esas contraseñas de inmediato."
    )
