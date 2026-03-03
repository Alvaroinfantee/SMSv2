from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    department: Mapped[str] = mapped_column(String(120), default="General")
    role: Mapped[str] = mapped_column(String(30), default="user")  # user|admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))

    campaigns: Mapped[list["Campaign"]] = relationship(back_populates="owner")


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    name: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(30))  # single|bulk
    sender: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    request_delivery_receipt: Mapped[bool] = mapped_column(Boolean, default=False)
    scheduled_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))
    last_sync_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped["User"] = relationship(back_populates="campaigns")
    messages: Mapped[list["SmsMessage"]] = relationship(back_populates="campaign", cascade="all, delete-orphan")


class SmsMessage(Base):
    __tablename__ = "sms_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    owner_user_id: Mapped[int] = mapped_column(Integer, index=True)

    dst: Mapped[str] = mapped_column(String(40), index=True)
    txt: Mapped[str] = mapped_column(Text)

    src: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    # Provider tracking
    provider_user_id_base: Mapped[str] = mapped_column(String(64), index=True)
    provider_user_id_full: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    # Sending (HTTP/API)
    send_http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    send_api_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    send_api_status: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    send_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Provider status (from Messages API)
    provider_state_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # numeric code from API, e.g. 3=Sent
    provider_state_text: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    # App status (normalized)
    status: Mapped[str] = mapped_column(String(30), default="created", index=True)  # created|submitted|pending|delivered|failed|sent|unknown
    last_status_check_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc), onupdate=lambda: dt.datetime.now(dt.timezone.utc))

    campaign: Mapped["Campaign"] = relationship(back_populates="messages")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=lambda: dt.datetime.now(dt.timezone.utc))


Index("ix_sms_owner_campaign", SmsMessage.owner_user_id, SmsMessage.campaign_id)
