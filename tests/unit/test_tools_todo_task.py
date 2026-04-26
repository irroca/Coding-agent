"""Tests for todo_write and task tools."""

from __future__ import annotations

from pathlib import Path

from coding_agent.tools.base import ToolContext
from coding_agent.tools.task import TaskParams, TaskTool
from coding_agent.tools.todo_write import TodoItem, TodoWriteParams, TodoWriteTool


def _ctx(ws: Path) -> ToolContext:
    return ToolContext(workspace=ws)


# ── TodoWrite ───────────────────────────────────────────────────────────


async def test_todo_write_basic(tmp_path: Path) -> None:
    tool = TodoWriteTool()
    params = TodoWriteParams(todos=[
        TodoItem(content="Read the file", status="completed"),
        TodoItem(content="Fix the bug", status="in_progress"),
        TodoItem(content="Run tests", status="pending"),
    ])
    result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "3 items" in result.content
    assert "Read the file" in result.content
    assert "Fix the bug" in result.content


async def test_todo_write_empty(tmp_path: Path) -> None:
    tool = TodoWriteTool()
    params = TodoWriteParams(todos=[])
    result = await tool.run(params, _ctx(tmp_path))
    assert result.ok
    assert "0 items" in result.content


async def test_todo_write_invalid_status(tmp_path: Path) -> None:
    tool = TodoWriteTool()
    params = TodoWriteParams(todos=[
        TodoItem(content="bad", status="done"),
    ])
    result = await tool.run(params, _ctx(tmp_path))
    assert not result.ok
    assert "Invalid status" in result.content


async def test_todo_write_stores_in_metadata(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    tool = TodoWriteTool()
    params = TodoWriteParams(todos=[
        TodoItem(content="Task A", status="pending"),
    ])
    await tool.run(params, ctx)
    assert "todos" in ctx.metadata
    assert ctx.metadata["todos"][0]["content"] == "Task A"


async def test_todo_write_permission_is_read(tmp_path: Path) -> None:
    tool = TodoWriteTool()
    params = TodoWriteParams(todos=[])
    perm = tool.permission_request(params)
    assert perm.action == "file_read"


# ── Task ────────────────────────────────────────────────────────────────


async def test_task_returns_not_available(tmp_path: Path) -> None:
    tool = TaskTool()
    params = TaskParams(description="Search for X", prompt="Find all uses of X")
    result = await tool.run(params, _ctx(tmp_path))
    assert not result.ok
    assert "not yet available" in result.content


async def test_task_permission_request(tmp_path: Path) -> None:
    tool = TaskTool()
    params = TaskParams(description="Do stuff", prompt="Do things")
    perm = tool.permission_request(params)
    assert perm.action == "ask"
    assert "Do stuff" in perm.summary
