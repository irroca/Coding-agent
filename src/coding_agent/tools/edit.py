"""Edit tool — precise string replacement in files."""

from __future__ import annotations

import difflib
from typing import ClassVar

from pydantic import BaseModel, Field

from coding_agent.core.types import ToolResult
from coding_agent.security.path_guard import resolve_and_validate
from coding_agent.tools.base import PermissionRequest, Tool, ToolContext


class EditParams(BaseModel):
    file_path: str = Field(description="Absolute or workspace-relative path to the file to edit.")
    old_string: str = Field(description="The exact text to find and replace.")
    new_string: str = Field(description="The replacement text.")
    replace_all: bool = Field(
        default=False,
        description="If true, replace all occurrences. Otherwise the match must be unique.",
    )


class EditTool(Tool):
    name: ClassVar[str] = "edit"
    description: ClassVar[str] = (
        "Perform exact string replacement in a file. The old_string must appear "
        "in the file. By default the match must be unique; set replace_all=true "
        "to replace every occurrence."
    )
    Params: ClassVar[type[BaseModel]] = EditParams

    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        assert isinstance(params, EditParams)
        path = resolve_and_validate(params.file_path, ctx.workspace, must_exist=True)

        old_content = path.read_text(encoding="utf-8", errors="replace")

        if params.old_string == params.new_string:
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content="old_string and new_string are identical — nothing to do.",
            )

        count = old_content.count(params.old_string)
        if count == 0:
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=f"old_string not found in {path}.",
            )

        if not params.replace_all and count > 1:
            return ToolResult(
                call_id="", tool=self.name, ok=False,
                content=(
                    f"old_string appears {count} times in {path}. "
                    "Provide more context to make it unique, or set replace_all=true."
                ),
            )

        if params.replace_all:
            new_content = old_content.replace(params.old_string, params.new_string)
        else:
            new_content = old_content.replace(params.old_string, params.new_string, 1)

        path.write_text(new_content, encoding="utf-8")

        diff = "".join(
            difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
            )
        )

        replaced = count if params.replace_all else 1
        return ToolResult(
            call_id="", tool=self.name, ok=True,
            content=f"Replaced {replaced} occurrence(s) in {path}\n{diff}",
            metadata={"path": str(path), "replacements": replaced},
        )

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        assert isinstance(params, EditParams)
        return PermissionRequest(
            tool=self.name,
            action="file_write",
            summary=f"Edit file: {params.file_path}",
            path=params.file_path,
        )

    def generate_diff(self, params: EditParams, ctx: ToolContext) -> str | None:
        path = resolve_and_validate(params.file_path, ctx.workspace, must_exist=True)
        old = path.read_text(encoding="utf-8", errors="replace")
        if params.old_string not in old:
            return None
        if params.replace_all:
            new = old.replace(params.old_string, params.new_string)
        else:
            new = old.replace(params.old_string, params.new_string, 1)
        return "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
            )
        )
