from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base
from utc_datetime import UTCDateTime, utc_now


class InboundWebhookEvent(Base):
    """Idempotent record of TanBan webhook deliveries."""

    __tablename__ = "inbound_webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    delivery_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    board_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    object_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    process_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    received_at: Mapped[object] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    processed_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class CursorAgentRun(Base):
    """Maps a TanBan card (or other object) to a Cursor agent run."""

    __tablename__ = "cursor_agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    board_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    card_public_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    mode: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    cursor_agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    cursor_run_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_delivery_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, nullable=False, default=utc_now)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, nullable=False, default=utc_now, onupdate=utc_now)
