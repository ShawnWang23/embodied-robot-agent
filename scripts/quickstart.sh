#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
workspace_dir="$(cd -- "${script_dir}/.." && pwd)"
cd "${workspace_dir}"

mode="${1:-agent}"
uv sync --extra dev

case "${mode}" in
  demo)
    uv run robot-agent demo --database data/tasks.db
    ;;
  agent)
    uv run robot-agent agent-demo "去实验室门口检查是否有人" \
      --planner rule --database data/agent_tasks.db
    ;;
  api)
    uv run robot-agent-api
    ;;
  test)
    uv run pytest -q --cov=robot_agent --cov-branch --cov-report=term-missing
    ;;
  *)
    echo "Usage: $0 [demo|agent|api|test]" >&2
    exit 2
    ;;
esac

