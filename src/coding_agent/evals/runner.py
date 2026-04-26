"""Eval runner — executes tasks and checks assertions."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from coding_agent.evals.task import EvalAssertion, EvalTask


@dataclass
class AssertionResult:
    assertion: EvalAssertion
    passed: bool
    detail: str = ""


@dataclass
class TaskResult:
    task: EvalTask
    passed: bool
    assertion_results: list[AssertionResult] = field(default_factory=list)
    error: str | None = None
    duration_seconds: float = 0.0


def check_assertion(assertion: EvalAssertion, workspace: Path) -> AssertionResult:
    """Check a single assertion against the workspace state."""
    try:
        if assertion.type == "file_exists":
            target = workspace / assertion.path
            ok = target.exists()
            return AssertionResult(assertion, ok, "" if ok else f"Not found: {target}")

        if assertion.type == "file_contains":
            target = workspace / assertion.path
            if not target.exists():
                return AssertionResult(assertion, False, f"File not found: {target}")
            text = target.read_text(encoding="utf-8", errors="replace")
            ok = assertion.content in text
            return AssertionResult(assertion, ok, "" if ok else f"'{assertion.content[:60]}' not in file")

        if assertion.type == "file_not_contains":
            target = workspace / assertion.path
            if not target.exists():
                return AssertionResult(assertion, True, "File not found (vacuously true)")
            text = target.read_text(encoding="utf-8", errors="replace")
            ok = assertion.content not in text
            return AssertionResult(assertion, ok, "" if ok else f"'{assertion.content[:60]}' found in file")

        if assertion.type == "file_equals":
            target = workspace / assertion.path
            if not target.exists():
                return AssertionResult(assertion, False, f"File not found: {target}")
            text = target.read_text(encoding="utf-8").strip()
            ok = text == assertion.content.strip()
            return AssertionResult(assertion, ok, "" if ok else "Content mismatch")

        if assertion.type == "command_output":
            result = subprocess.run(
                assertion.command, shell=True, capture_output=True,
                text=True, cwd=workspace, timeout=30,
            )
            output = result.stdout.strip()
            ok = assertion.expected in output
            return AssertionResult(
                assertion, ok,
                "" if ok else f"Expected '{assertion.expected}' in output, got: {output[:200]}",
            )

        return AssertionResult(assertion, False, f"Unknown assertion type: {assertion.type}")

    except Exception as e:
        return AssertionResult(assertion, False, f"Error: {e}")


async def run_task_with_agent(
    task: EvalTask,
    provider_name: str = "deepseek",
    api_key: str | None = None,
) -> TaskResult:
    """Run a single eval task using the real agent loop."""
    import time

    from coding_agent.agent.loop import Agent
    from coding_agent.core.config import AgentConfig, Config, PermissionsConfig, ProviderConfig
    from coding_agent.core.session import Session
    from coding_agent.providers.registry import create_provider

    workspace = Path(tempfile.mkdtemp(prefix=f"eval_{task.id}_"))
    start = time.monotonic()

    try:
        for cmd in task.setup_commands:
            subprocess.run(cmd, shell=True, cwd=workspace, check=True, timeout=30)

        key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        if not key:
            return TaskResult(task, False, error="No API key configured")

        config = Config(
            provider=provider_name,
            workspace=workspace,
            providers={provider_name: ProviderConfig(api_key=key)},
            permissions=PermissionsConfig(
                file_read="allow", file_write="allow", bash="allow",
            ),
            agent=AgentConfig(max_iterations=task.max_iterations),
        )

        provider = create_provider(config)
        session = Session(workspace=str(workspace), provider=provider_name, model=provider.model)
        agent = Agent(provider, config, session)

        async for _ in agent.run(task.prompt):
            pass

        assertion_results = [check_assertion(a, workspace) for a in task.assertions]
        all_passed = all(r.passed for r in assertion_results)

        return TaskResult(
            task, all_passed, assertion_results,
            duration_seconds=time.monotonic() - start,
        )

    except Exception as e:
        return TaskResult(
            task, False, error=str(e),
            duration_seconds=time.monotonic() - start,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


async def run_all_tasks(
    tasks: list[EvalTask],
    provider_name: str = "deepseek",
    api_key: str | None = None,
) -> list[TaskResult]:
    """Run all eval tasks sequentially and return results."""
    results = []
    for task in tasks:
        result = await run_task_with_agent(task, provider_name, api_key)
        results.append(result)
    return results


def print_report(results: list[TaskResult]) -> None:
    """Print a summary report of eval results."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"\n{'='*60}")
    print("  Evaluation Report")
    print(f"{'='*60}")
    print(f"  Total: {total}  Passed: {passed}  Failed: {failed}")
    print(f"  Pass rate: {passed/total*100:.0f}%" if total else "  No tasks")
    print(f"{'='*60}\n")

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.task.id}: {r.task.name} ({r.duration_seconds:.1f}s)")
        if r.error:
            print(f"         Error: {r.error}")
        for ar in r.assertion_results:
            if not ar.passed:
                print(f"         FAIL: {ar.assertion.describe()}")
                if ar.detail:
                    print(f"               {ar.detail}")
    print()
