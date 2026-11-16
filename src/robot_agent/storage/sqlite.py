"""Simple SQLite task snapshot repository for the first Phase 1 increment."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from robot_agent.core.models import EventLevel, EventType, Task, TaskEvent, TaskStatus


class SQLiteTaskRepository:
    """Persist each Task as validated JSON while keeping a queryable status."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_events_task_id_id
                ON task_events (task_id, id)
                """
            )

    def save(self, task: Task) -> None:
        payload = task.model_dump_json()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (id, status, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (task.id, task.status.value, payload, task.updated_at.isoformat()),
            )

    def get(self, task_id: str) -> Task | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()

        if row is None:
            return None
        return Task.model_validate_json(row["payload"])

    def list_tasks(
        self,
        *,
        statuses: set[TaskStatus] | None = None,
    ) -> list[Task]:
        query = "SELECT payload FROM tasks"
        parameters: tuple[str, ...] = ()
        if statuses:
            ordered = sorted(status.value for status in statuses)
            placeholders = ", ".join("?" for _ in ordered)
            query += f" WHERE status IN ({placeholders})"
            parameters = tuple(ordered)
        query += " ORDER BY updated_at"
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [Task.model_validate_json(row["payload"]) for row in rows]

    def add_event(self, event: TaskEvent) -> TaskEvent:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO task_events (
                    task_id, event_type, level, message, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.task_id,
                    event.event_type.value,
                    event.level.value,
                    event.message,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.created_at.isoformat(),
                ),
            )
            event_id = cursor.lastrowid
        return event.model_copy(update={"id": event_id})

    def list_events(self, task_id: str) -> list[TaskEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, task_id, event_type, level, message, payload, created_at
                FROM task_events
                WHERE task_id = ?
                ORDER BY id
                """,
                (task_id,),
            ).fetchall()

        return [
            TaskEvent(
                id=row["id"],
                task_id=row["task_id"],
                event_type=EventType(row["event_type"]),
                level=EventLevel(row["level"]),
                message=row["message"],
                payload=json.loads(row["payload"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

