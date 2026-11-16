[CmdletBinding()]
param(
    [ValidateSet("demo", "agent", "api", "test")]
    [string]$Mode = "agent",
    [switch]$SkipSync
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required. Install it from https://docs.astral.sh/uv/."
}

if (-not $SkipSync) {
    uv sync --extra dev
}

switch ($Mode) {
    "demo" {
        uv run robot-agent demo --database data/tasks.db
    }
    "agent" {
        uv run robot-agent agent-demo "去实验室门口检查是否有人" `
            --planner rule `
            --database data/agent_tasks.db
    }
    "api" {
        uv run robot-agent-api
    }
    "test" {
        uv run pytest -q --cov=robot_agent --cov-branch --cov-report=term-missing
    }
}

