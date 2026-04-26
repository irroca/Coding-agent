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
from typing import Any, ClassVar

from pydantic import BaseModel

from coding_agent.core.errors import ToolValidationError
from coding_agent.core.types import ToolResult, ToolSchema


@dataclass
class ToolContext:
    """Runtime context passed to every tool invocation."""

    workspace: Path
    session_id: str = ""
    allowed_paths: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PermissionRequest:
    """Declares what a tool call intends to do, so the permission engine can decide."""

    tool: str
    action: str  # "file_read" | "file_write" | "bash" | "network"
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


def all_schemas() -> list[ToolSchema]:
    return [cls.schema() for cls in _TOOL_REGISTRY.values()]


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

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
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
