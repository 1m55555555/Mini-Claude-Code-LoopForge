from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.errors import ToolError


TASK_STATUSES = {"pending", "in_progress", "blocked", "completed", "cancelled"}


@dataclass(frozen=True)
class TaskRecord:
    id: str
    title: str
    status: str
    blocked_by: list[str]
    owner: str | None
    notes: str
    created_at: str
    updated_at: str

    def model_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "blocked_by": self.blocked_by,
            "owner": self.owner,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class TaskStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        *,
        title: str,
        status: str = "pending",
        blocked_by: list[str] | None = None,
        owner: str | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        title = title.strip()
        if not title:
            raise ToolError("title is required")
        status = _normalize_status(status)
        now = _now()
        task = TaskRecord(
            id=f"task-{uuid4().hex[:8]}",
            title=title,
            status=status,
            blocked_by=_normalize_blocked_by(blocked_by),
            owner=owner.strip() if isinstance(owner, str) and owner.strip() else None,
            notes=notes.strip(),
            created_at=now,
            updated_at=now,
        )
        tasks = self._read()
        tasks.append(task.model_dump())
        self._write(tasks)
        return task.model_dump()

    def list(self, *, status: str | None = None) -> list[dict[str, Any]]:
        tasks = self._read()
        if status:
            normalized = _normalize_status(status)
            tasks = [task for task in tasks if task.get("status") == normalized]
        return sorted(tasks, key=lambda task: str(task.get("updated_at", "")), reverse=True)

    def get(self, task_id: str) -> dict[str, Any]:
        task_id = task_id.strip()
        for task in self._read():
            if task.get("id") == task_id:
                return task
        raise ToolError(f"task not found: {task_id}")

    def update(
        self,
        *,
        task_id: str,
        title: str | None = None,
        status: str | None = None,
        blocked_by: list[str] | None = None,
        owner: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        task_id = task_id.strip()
        tasks = self._read()
        for index, task in enumerate(tasks):
            if task.get("id") != task_id:
                continue
            updated = dict(task)
            if title is not None:
                title = title.strip()
                if not title:
                    raise ToolError("title cannot be empty")
                updated["title"] = title
            if status is not None:
                updated["status"] = _normalize_status(status)
            if blocked_by is not None:
                updated["blocked_by"] = _normalize_blocked_by(blocked_by)
            if owner is not None:
                updated["owner"] = owner.strip() or None
            if notes is not None:
                updated["notes"] = notes.strip()
            updated["updated_at"] = _now()
            tasks[index] = updated
            self._write(tasks)
            return updated
        raise ToolError(f"task not found: {task_id}")

    def counts(self) -> dict[str, int]:
        counts = {status: 0 for status in sorted(TASK_STATUSES)}
        for task in self._read():
            status = str(task.get("status", "pending"))
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ToolError(f"task store is corrupted: {exc}") from exc
        if not isinstance(raw, list):
            raise ToolError("task store must be a list")
        return [task for task in raw if isinstance(task, dict)]

    def _write(self, tasks: list[dict[str, Any]]) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            temp.replace(self.path)
        except PermissionError:
            self.path.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                temp.unlink()
            except OSError:
                pass


class TaskStoreTools:
    def __init__(self, store: TaskStore) -> None:
        self.store = store

    def create(self, arguments: dict[str, Any]) -> str:
        task = self.store.create(
            title=str(arguments.get("title", "")),
            status=str(arguments.get("status", "pending")),
            blocked_by=arguments.get("blocked_by"),
            owner=_optional_string(arguments.get("owner")),
            notes=str(arguments.get("notes", "")),
        )
        return json.dumps({"task": task, "counts": self.store.counts()}, ensure_ascii=False)

    def list(self, arguments: dict[str, Any]) -> str:
        status = _optional_string(arguments.get("status"))
        return json.dumps({"tasks": self.store.list(status=status), "counts": self.store.counts()}, ensure_ascii=False)

    def get(self, arguments: dict[str, Any]) -> str:
        task = self.store.get(str(arguments.get("id", "")))
        return json.dumps({"task": task, "counts": self.store.counts()}, ensure_ascii=False)

    def update(self, arguments: dict[str, Any]) -> str:
        task = self.store.update(
            task_id=str(arguments.get("id", "")),
            title=_optional_string(arguments.get("title")),
            status=_optional_string(arguments.get("status")),
            blocked_by=arguments.get("blocked_by") if "blocked_by" in arguments else None,
            owner=_optional_string(arguments.get("owner")) if "owner" in arguments else None,
            notes=_optional_string(arguments.get("notes")) if "notes" in arguments else None,
        )
        return json.dumps({"task": task, "counts": self.store.counts()}, ensure_ascii=False)


def _normalize_status(status: str) -> str:
    status = status.strip()
    if status not in TASK_STATUSES:
        raise ToolError(f"invalid task status: {status}")
    return status


def _normalize_blocked_by(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ToolError("blocked_by must be a list")
    return [str(item).strip() for item in value if str(item).strip()]


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _now() -> str:
    return datetime.now().astimezone().isoformat()

