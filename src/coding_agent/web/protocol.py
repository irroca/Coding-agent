"""WebSocket message protocol — single source of truth for browser ⇄ backend.

Every message on the WebSocket is JSON of the form ``{"type": "...", ...}``.
The discriminator field ``type`` selects the schema. We use pydantic
``Field(discriminator="type")`` unions for round-trip parsing.

Frontend mirrors these shapes manually in ``frontend/src/types.ts``. Keep them
in sync or regenerate with ``datamodel-code-generator`` (future work).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from coding_agent.core.types import Role, ToolCall, ToolResult, Usage

# ─── Server → Client ────────────────────────────────────────────────────


class TextDeltaEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["text_delta"] = "text_delta"
    text: str


class ToolStartEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["tool_start"] = "tool_start"
    tool_call: ToolCall


class ToolResultEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["tool_result"] = "tool_result"
    tool_result: ToolResult


class UsageEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["usage"] = "usage"
    usage: Usage


class TurnEndEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["turn_end"] = "turn_end"
    finish_reason: str | None = None


class ErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["error"] = "error"
    error: str


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["confirm_request"] = "confirm_request"
    request_id: str
    tool_name: str
    summary: str
    diff_preview: str | None = None


class SessionMessageSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Role
    content: str = ""
    reasoning_content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    created_at: datetime


class SessionState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["session_state"] = "session_state"
    session_id: str
    workspace: str
    provider: str
    model: str
    messages: list[SessionMessageSnapshot]
    usage: Usage
    created_at: datetime
    auto_approved: list[str] = Field(default_factory=list)


class SessionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    created_at: datetime
    title: str
    """First user message, truncated. Empty for new sessions."""
    message_count: int


class SessionList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["session_list"] = "session_list"
    sessions: list[SessionSummary]


class WorkspaceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    last_used: datetime | None = None


class WorkspaceList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["workspace_list"] = "workspace_list"
    current: str
    recent: list[WorkspaceInfo]


class Ack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["ack"] = "ack"
    of: str
    """The client message ``type`` this ack is for."""
    detail: dict[str, Any] = Field(default_factory=dict)


class ServerError(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["server_error"] = "server_error"
    message: str
    recoverable: bool = True


ServerMessage = Annotated[
    TextDeltaEvent | ToolStartEvent | ToolResultEvent | UsageEvent | TurnEndEvent | ErrorEvent | ConfirmRequest | SessionState | SessionList | WorkspaceList | Ack | ServerError,
    Field(discriminator="type"),
]


# ─── Client → Server ────────────────────────────────────────────────────


class Submit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["submit"] = "submit"
    text: str


class Cancel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["cancel"] = "cancel"


class ConfirmResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["confirm_response"] = "confirm_response"
    request_id: str
    approved: bool
    always: bool = False


class AttachSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["attach_session"] = "attach_session"
    session_id: str | None = None
    """``None`` means start a fresh session."""
    workspace: str | None = None
    """``None`` keeps the runner's current workspace."""


class DeleteSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["delete_session"] = "delete_session"
    session_id: str


class ListSessions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["list_sessions"] = "list_sessions"


class ListWorkspaces(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["list_workspaces"] = "list_workspaces"


ClientMessage = Annotated[
    Submit | Cancel | ConfirmResponse | AttachSession | DeleteSession | ListSessions | ListWorkspaces,
    Field(discriminator="type"),
]


class _ClientEnvelope(BaseModel):
    """Wrapper used only by ``parse_client_message`` to drive discriminator."""

    model_config = ConfigDict(extra="forbid")
    msg: ClientMessage


def parse_client_message(raw: dict[str, Any]) -> ClientMessage:
    """Parse a JSON dict into the matching ClientMessage variant."""
    return _ClientEnvelope.model_validate({"msg": raw}).msg
