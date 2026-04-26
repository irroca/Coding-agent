#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

echo "=== Coding Agent Evaluation ==="
echo ""

if [ "${1:-}" = "--list" ]; then
    exec uv run python -m coding_agent.evals.cli --list
fi

exec uv run python -m coding_agent.evals.cli "$@"
