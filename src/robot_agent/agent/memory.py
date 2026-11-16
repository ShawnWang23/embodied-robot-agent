"""Persistent LangGraph checkpoint lifecycle for the local service."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

os.environ.setdefault("LANGGRAPH_STRICT_MSGPACK", "true")

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver  # noqa: E402


@asynccontextmanager
async def open_sqlite_checkpointer(path: str | Path) -> AsyncIterator[Any]:
    """Open, migrate, and reliably close one async SQLite checkpointer."""

    resolved = Path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    async with AsyncSqliteSaver.from_conn_string(str(resolved)) as saver:
        await saver.setup()
        yield saver

