"""Tests for the tool base class, registry, and schema generation."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.tools.base import (
    Tool,
    ToolContext,
    all_schemas,
    all_tools,
    get_tool,
)


class _DummyParams(BaseModel):
    message: str = Field(description="A test message.")


class _DummyTool(Tool):
    name: ClassVar[str] = "_test_dummy"
    description: ClassVar[str] = "A test tool."
    Params: ClassVar[type[BaseModel]] = _DummyParams

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, _DummyParams)
        return ToolResult(call_id="", tool=self.name, ok=True, content=params.message)


def test_auto_registration() -> None:
    assert get_tool("_test_dummy") is _DummyTool
    assert "_test_dummy" in all_tools()


def test_schema_generation() -> None:
    schema = _DummyTool.schema()
    assert schema.name == "_test_dummy"
    assert schema.description == "A test tool."
    assert "message" in schema.parameters.get("properties", {})
    assert "title" not in schema.parameters


def test_validate_params_success() -> None:
    tool = _DummyTool()
    p = tool.validate_params({"message": "hi"})
    assert isinstance(p, _DummyParams)
    assert p.message == "hi"


def test_validate_params_failure() -> None:
    tool = _DummyTool()
    import pytest

    with pytest.raises(Exception, match="Invalid arguments"):
        tool.validate_params({"wrong_field": 1})


async def test_run_dummy() -> None:
    tool = _DummyTool()
    p = _DummyParams(message="hello")
    ctx = ToolContext(workspace=__import__("pathlib").Path("/tmp"))
    result = await tool.run(p, ctx)
    assert result.ok is True
    assert result.content == "hello"


def test_all_schemas_includes_builtins() -> None:
    import coding_agent.tools  # noqa: F401

    schemas = all_schemas()
    names = {s.name for s in schemas}
    assert "read" in names
    assert "write" in names
    assert "ls" in names
