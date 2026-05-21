"""CLI entry point for running evaluations."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from coding_agent.evals.runner import export_json_report, print_report, run_all_tasks
from coding_agent.evals.task import EvalTask


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Coding Agent evaluations")
    parser.add_argument(
        "--tasks-dir",
        type=Path,
        default=Path(__file__).parent / "tasks",
        help="Directory containing task JSON files",
    )
    parser.add_argument(
        "--provider",
        default="deepseek",
        help="Provider name (default: deepseek)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key (defaults to env var)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override provider base URL (e.g. http://localhost:23333/api/openai/v1)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the model name (e.g. claude-haiku-4.5)",
    )
    parser.add_argument(
        "--task",
        default=None,
        help="Run a specific task by ID (e.g. '01-create-file')",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional path to write a machine-readable JSON report",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_tasks",
        help="List available tasks and exit",
    )
    args = parser.parse_args()

    tasks = EvalTask.load_all(args.tasks_dir)

    if args.list_tasks:
        print(f"\nAvailable eval tasks ({len(tasks)}):\n")
        for t in tasks:
            print(f"  {t.id}: {t.name}")
            print(f"    {t.description}")
            print(f"    Assertions: {len(t.assertions)}, Max iterations: {t.max_iterations}")
            print()
        return

    if args.task:
        tasks = [t for t in tasks if t.id == args.task]
        if not tasks:
            print(f"Task '{args.task}' not found.", file=sys.stderr)
            sys.exit(1)

    print(
        f"Running {len(tasks)} eval task(s) with provider '{args.provider}'"
        f"{f' model={args.model}' if args.model else ''}..."
    )
    results = asyncio.run(
        run_all_tasks(
            tasks,
            provider_name=args.provider,
            api_key=args.api_key,
            base_url=args.base_url,
            model=args.model,
        )
    )
    print_report(results)

    if args.report:
        export_json_report(results, args.report)
        print(f"  JSON report written to {args.report}")

    if not all(r.passed for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
