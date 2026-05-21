"""Eval task definition and loader."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EvalAssertion:
    """A single assertion to check after the agent finishes."""

    type: str  # "file_exists" | "file_contains" | "file_not_contains" | "file_equals" | "command_output"
    path: str = ""
    content: str = ""
    pattern: str = ""
    command: str = ""
    expected: str = ""

    def describe(self) -> str:
        if self.type == "file_exists":
            return f"File exists: {self.path}"
        if self.type == "file_contains":
            return f"File {self.path} contains '{self.content[:40]}'"
        if self.type == "file_not_contains":
            return f"File {self.path} does not contain '{self.content[:40]}'"
        if self.type == "file_equals":
            return f"File {self.path} equals expected content"
        if self.type == "command_output":
            return f"Command '{self.command}' outputs '{self.expected[:40]}'"
        return f"{self.type}: {self.path or self.command}"


@dataclass
class EvalTask:
    """One evaluation task the agent should solve."""

    id: str
    name: str
    description: str
    prompt: str
    setup_commands: list[str] = field(default_factory=list)
    assertions: list[EvalAssertion] = field(default_factory=list)
    timeout_seconds: int = 120
    max_iterations: int = 15

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalTask:
        assertions = [EvalAssertion(**a) for a in data.pop("assertions", [])]
        return cls(**data, assertions=assertions)

    @classmethod
    def load_all(cls, tasks_dir: Path) -> list[EvalTask]:
        tasks = []
        for f in sorted(tasks_dir.glob("*.json")):
            data = json.loads(f.read_text(encoding="utf-8"))
            tasks.append(cls.from_dict(data))
        return tasks
