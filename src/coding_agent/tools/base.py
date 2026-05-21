"""Tool base class, registry, and automatic JSON Schema generation.

Every tool is a subclass of ``Tool``. Registration is automatic via
``__init_subclass__``: importing the module is enough to make the tool
discoverable. The registry exposes schemas for the LLM and a dispatch
method for the orchestrator.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

from coding_agent.core.errors import ToolValidationError
from coding_agent.core.types import ToolResult, ToolSchema

if TYPE_CHECKING:
    from coding_agent.core.config import Config
    from coding_agent.providers.base import LLMProvider


@dataclass
class ToolContext:
    """Runtime context passed to every tool invocation.

    Most tools only need ``workspace``. ``provider`` / ``config`` are populated
    by the agent loop and are required by tools that spawn sub-agents (e.g.
    ``task``). ``is_subagent`` is True when this context belongs to a sub-agent;
    the ``task`` tool refuses to fire in that case to keep recursion bounded.
    """

    workspace: Path
    session_id: str = ""
    allowed_paths: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    provider: LLMProvider | None = None
    config: Config | None = None
    is_subagent: bool = False


@dataclass
class PermissionRequest:
    """Declares what a tool call intends to do, so the permission engine can decide."""

    tool: str
    action: str  # "file_read" | "file_write" | "bash"
    summary: str
    path: str | None = None
    command: str | None = None
    diff: str | None = None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_TOOL_REGISTRY: dict[str, type[Tool]] = {}


def get_tool(name: str) -> type[Tool] | None:
    return _TOOL_REGISTRY.get(name)


def all_tools() -> dict[str, type[Tool]]:
    return dict(_TOOL_REGISTRY)


def all_schemas(allowed: set[str] | None = None) -> list[ToolSchema]:
    """Return tool schemas, optionally filtered by name allow-list.

    Used by sub-agents to expose a restricted tool surface.
    """
    if allowed is None:
        return [cls.schema() for cls in _TOOL_REGISTRY.values()]
    return [cls.schema() for name, cls in _TOOL_REGISTRY.items() if name in allowed]


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class Tool(ABC):
    """Abstract base for all agent tools.

    Subclasses MUST define:
      - ``name: ClassVar[str]``
      - ``description: ClassVar[str]``
      - ``Params`` — a pydantic BaseModel describing accepted arguments
      - ``run()`` — async execution logic

    Subclasses MAY override:
      - ``permission_request()`` — default returns a generic "ask" request
    """

    name: ClassVar[str]
    description: ClassVar[str]
    Params: ClassVar[type[BaseModel]]

    _skip_registration: ClassVar[bool] = False
    """Set in a subclass to opt out of auto-registration."""

    def __init_subclass__(cls, *, register: bool = True, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if not register:
            cls._skip_registration = True
            return
        if cls.__dict__.get("_skip_registration"):
            return
        # Inherit the opt-out from parents that asked to skip registration.
        if any(getattr(b, "_skip_registration", False) for b in cls.__mro__[1:]):
            return
        if inspect.isabstract(cls):
            return
        if not hasattr(cls, "name") or not hasattr(cls, "Params"):
            return
        _TOOL_REGISTRY[cls.name] = cls

    @classmethod
    def schema(cls) -> ToolSchema:
        json_schema = cls.Params.model_json_schema()
        json_schema.pop("title", None)
        return ToolSchema(
            name=cls.name,
            description=cls.description,
            parameters=json_schema,
        )

    def validate_params(self, raw: dict[str, Any]) -> BaseModel:
        try:
            return self.Params.model_validate(raw)
        except Exception as e:
            raise ToolValidationError(
                f"Invalid arguments for tool '{self.name}': {e}"
            ) from e

    @abstractmethod
    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        ...

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        return PermissionRequest(
            tool=self.name,
            action="ask",
            summary=f"Run tool '{self.name}'",
        )
