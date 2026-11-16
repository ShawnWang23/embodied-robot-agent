"""Export the FastAPI schema without starting Uvicorn or opening databases."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from robot_agent.api.server import app


def main() -> None:
    parser = argparse.ArgumentParser(description="Export Robot Agent OpenAPI JSON.")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/phase8/openapi.json"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(args.output.resolve())


if __name__ == "__main__":
    main()

