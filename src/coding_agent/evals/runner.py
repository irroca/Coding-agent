"""Eval runner — executes tasks with the real agent and checks assertions.

The runner spins up a fresh agent inside a throwaway temp directory, feeds it
the task prompt, and asserts the resulting workspace state.

In addition to the pass/fail verdict, every run captures:
  * iterations the agent used
  * tool-call count + per-tool histogram
  * prompt / completion / cached tokens
  * wall-clock duration

These metrics let us compare *quality* across changes (a fix that lands the
same pass rate with fewer tokens or fewer iterations is still a win).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from coding_agent.agent.loop import Agent, EventKind
from coding_agent.core.config import (
    AgentConfig,
    Config,
    PermissionsConfig,
    ProviderConfig,
)
from coding_agent.core.session import Session
from coding_agent.core.types import Usage
from coding_agent.evals.task import EvalAssertion, EvalTask
from coding_agent.providers.registry import build_provider


@dataclass
class AssertionResult:
    assertion: EvalAssertion
    passed: bool
    detail: str = ""


@dataclass
class TaskMetrics:
    iterations: int = 0
    tool_calls: int = 0
    tool_histogram: Counter[str] = field(default_factory=Counter)
    usage: Usage = field(default_factory=Usage)
    error_events: int = 0

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens

    @property
    def cache_hit_rate(self) -> float:
        if not self.usage.prompt_tokens:
            return 0.0
        return self.usage.cached_prompt_tokens / self.usage.prompt_tokens


@dataclass
class TaskResult:
    task: EvalTask
    passed: bool
    assertion_results: list[AssertionResult] = field(default_factory=list)
    error: str | None = None
    duration_seconds: float = 0.0
    metrics: TaskMetrics = field(default_factory=TaskMetrics)


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
            return AssertionResult(
                assertion, ok, "" if ok else f"'{assertion.content[:60]}' not in file"
            )

        if assertion.type == "file_not_contains":
            target = workspace / assertion.path
            if not target.exists():
                return AssertionResult(
                    assertion, True, "File not found (vacuously true)"
                )
            text = target.read_text(encoding="utf-8", errors="replace")
            ok = assertion.content not in text
            return AssertionResult(
                assertion, ok, "" if ok else f"'{assertion.content[:60]}' found in file"
            )

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


def _provider_env_key(name: str) -> str:
    return {
        "deepseek": "DEEPSEEK_API_KEY",
        "qwen": "DASHSCOPE_API_KEY",
        "moonshot": "MOONSHOT_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(name, f"{name.upper()}_API_KEY")


async def run_task_with_agent(
    task: EvalTask,
    *,
    provider_name: str = "deepseek",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> TaskResult:
    """Run a single eval task using the real agent loop.

    All non-None overrides are passed straight into ProviderConfig. This lets
    callers point at a local OpenAI-compat endpoint (e.g. Agent Maestro) without
    touching the environment.
    """
    workspace = Path(tempfile.mkdtemp(prefix=f"eval_{task.id}_"))
    start = time.monotonic()
    metrics = TaskMetrics()

    try:
        for cmd in task.setup_commands:
            subprocess.run(cmd, shell=True, cwd=workspace, check=True, timeout=30)

        key = api_key or os.getenv(_provider_env_key(provider_name)) or "local-no-auth"

        provider_cfg = ProviderConfig(api_key=key)
        if base_url:
            provider_cfg.base_url = base_url
        if model:
            provider_cfg.model = model

        config = Config(
            provider=provider_name,
            workspace=workspace,
            providers={provider_name: provider_cfg},
            permissions=PermissionsConfig(
                file_read="allow", file_write="allow", bash="allow",
            ),
            agent=AgentConfig(max_iterations=task.max_iterations),
        )

        provider = build_provider(config)
        session = Session(
            workspace=str(workspace),
            provider=provider_name,
            model=provider.model,
        )
        agent = Agent(provider, config, session)

        try:
            async for event in agent.run(task.prompt):
                if event.kind == EventKind.TOOL_START and event.tool_call:
                    metrics.tool_calls += 1
                    metrics.tool_histogram[event.tool_call.name] += 1
                elif event.kind == EventKind.USAGE and event.usage:
                    metrics.usage = Usage(
                        prompt_tokens=metrics.usage.prompt_tokens
                        + event.usage.prompt_tokens,
                        completion_tokens=metrics.usage.completion_tokens
                        + event.usage.completion_tokens,
                        cached_prompt_tokens=metrics.usage.cached_prompt_tokens
                        + event.usage.cached_prompt_tokens,
                    )
                elif event.kind == EventKind.ERROR:
                    metrics.error_events += 1
        finally:
            if hasattr(provider, "aclose"):
                await provider.aclose()

        metrics.iterations = sum(
            1 for m in session.messages if m.role.value == "assistant"
        )

        assertion_results = [check_assertion(a, workspace) for a in task.assertions]
        all_passed = all(r.passed for r in assertion_results) and metrics.error_events == 0

        return TaskResult(
            task,
            all_passed,
            assertion_results,
            duration_seconds=time.monotonic() - start,
            metrics=metrics,
        )

    except Exception as e:
        return TaskResult(
            task,
            False,
            error=str(e),
            duration_seconds=time.monotonic() - start,
            metrics=metrics,
        )
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


async def run_all_tasks(
    tasks: list[EvalTask],
    *,
    provider_name: str = "deepseek",
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
) -> list[TaskResult]:
    """Run all eval tasks sequentially and return results."""
    results = []
    for task in tasks:
        result = await run_task_with_agent(
            task,
            provider_name=provider_name,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        results.append(result)
    return results


def print_report(results: list[TaskResult]) -> None:
    """Print a summary report of eval results."""
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed

    print(f"\n{'='*72}")
    print("  Evaluation Report")
    print(f"{'='*72}")
    print(f"  Total: {total}  Passed: {passed}  Failed: {failed}")
    if total:
        print(f"  Pass rate: {passed / total * 100:.0f}%")

    total_usage = Usage()
    total_iters = 0
    total_tools = 0
    for r in results:
        total_usage = Usage(
            prompt_tokens=total_usage.prompt_tokens + r.metrics.usage.prompt_tokens,
            completion_tokens=total_usage.completion_tokens
            + r.metrics.usage.completion_tokens,
            cached_prompt_tokens=total_usage.cached_prompt_tokens
            + r.metrics.usage.cached_prompt_tokens,
        )
        total_iters += r.metrics.iterations
        total_tools += r.metrics.tool_calls

    print(
        f"  Tokens: prompt={total_usage.prompt_tokens:,}  "
        f"cached={total_usage.cached_prompt_tokens:,}  "
        f"completion={total_usage.completion_tokens:,}  "
        f"total={total_usage.total_tokens:,}"
    )
    if total_usage.prompt_tokens:
        print(
            f"  Cache hit rate: "
            f"{total_usage.cached_prompt_tokens / total_usage.prompt_tokens * 100:.1f}%"
        )
    print(f"  Iterations: {total_iters}  Tool calls: {total_tools}")
    print(f"{'='*72}\n")

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        m = r.metrics
        print(
            f"  [{status}] {r.task.id}: {r.task.name} "
            f"({r.duration_seconds:.1f}s, iters={m.iterations}, "
            f"tools={m.tool_calls}, tokens={m.total_tokens})"
        )
        if r.error:
            print(f"         Error: {r.error}")
        for ar in r.assertion_results:
            if not ar.passed:
                print(f"         FAIL: {ar.assertion.describe()}")
                if ar.detail:
                    print(f"               {ar.detail}")
    print()


def export_json_report(results: list[TaskResult], path: Path) -> None:
    """Write a machine-readable report for cross-run comparison."""
    import json

    payload = {
        "summary": {
            "total": len(results),
            "passed": sum(1 for r in results if r.passed),
        },
        "results": [
            {
                "task_id": r.task.id,
                "passed": r.passed,
                "error": r.error,
                "duration_seconds": r.duration_seconds,
                "metrics": {
                    "iterations": r.metrics.iterations,
                    "tool_calls": r.metrics.tool_calls,
                    "tool_histogram": dict(r.metrics.tool_histogram),
                    "prompt_tokens": r.metrics.usage.prompt_tokens,
                    "completion_tokens": r.metrics.usage.completion_tokens,
                    "cached_prompt_tokens": r.metrics.usage.cached_prompt_tokens,
                    "cache_hit_rate": r.metrics.cache_hit_rate,
                },
                "failed_assertions": [
                    {"describe": ar.assertion.describe(), "detail": ar.detail}
                    for ar in r.assertion_results
                    if not ar.passed
                ],
            }
            for r in results
        ],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
