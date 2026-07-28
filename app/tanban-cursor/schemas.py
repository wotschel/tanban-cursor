from datetime import datetime

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str = "ok"
    service: str = "tanban-cursor"
    app_env: str


class TanbanWebhookAck(BaseModel):
    status: str
    delivery_id: str
    duplicate: bool = False


class CursorAgentRunOut(BaseModel):
    id: int
    board_public_id: str | None = None
    card_public_id: str | None = None
    title: str | None = None
    mode: str | None = None
    cursor_agent_id: str | None = None
    cursor_run_id: str | None = None
    status: str
    error: str | None = None
    source_delivery_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CursorAgentRunDetailOut(CursorAgentRunOut):
    prompt: str | None = None
    result_text: str | None = None
    content_hash: str | None = None


class StartAgentRequest(BaseModel):
    prompt: str = Field(min_length=1)
    board_public_id: str | None = None
    card_public_id: str | None = None
