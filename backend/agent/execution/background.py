from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agent.errors import ToolError
from agent.model.client import ModelClient, ModelConfig
from agent.execution.subagents import SubagentConfig, run_subagent


@dataclass
class BackgroundJob:
    id: str
    description: str
    status: str
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    result: str | None = None
    error: str | None = None
    notified: bool = False
    logs: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result_chars": len(self.result or ""),
            "error": self.error,
            "log_count": len(self.logs),
        }

    def detail(self) -> dict[str, Any]:
        detail = self.summary()
        detail["result"] = self.result
        detail["logs"] = self.logs[-20:]
        return detail


class BackgroundTaskManager:
    def __init__(
        self,
        *,
        model_config: ModelConfig,
        subagent_config: SubagentConfig,
        max_workers: int = 2,
    ) -> None:
        self.model_config = model_config
        self.subagent_config = subagent_config
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="background-agent")
        self.lock = threading.Lock()
        self.next_id = 1
        self.jobs: dict[str, BackgroundJob] = {}
        self.futures: dict[str, Future[None]] = {}

    def start(self, *, description: str, parent_context: dict[str, Any]) -> dict[str, Any]:
        description = description.strip()
        if not description:
            raise ToolError("description is required")

        with self.lock:
            job_id = f"bg-{self.next_id:03d}"
            self.next_id += 1
            job = BackgroundJob(
                id=job_id,
                description=description,
                status="queued",
                created_at=_now(),
            )
            self.jobs[job_id] = job
            future = self.executor.submit(self._run_job, job_id, description, parent_context)
            self.futures[job_id] = future
            return job.summary()

    def list(self) -> list[dict[str, Any]]:
        self.refresh()
        with self.lock:
            return [job.summary() for job in self.jobs.values()]

    def get(self, job_id: str) -> dict[str, Any]:
        self.refresh()
        with self.lock:
            job = self.jobs.get(job_id.strip())
            if job is None:
                raise ToolError(f"background task not found: {job_id}")
            return job.detail()

    def collect_notifications(self) -> list[dict[str, Any]]:
        self.refresh()
        notifications: list[dict[str, Any]] = []
        with self.lock:
            for job in self.jobs.values():
                if job.notified or job.status not in {"success", "failure"}:
                    continue
                job.notified = True
                notifications.append(job.detail())
        return notifications

    def refresh(self) -> None:
        for job_id, future in list(self.futures.items()):
            if future.done():
                with self.lock:
                    self.futures.pop(job_id, None)

    def _run_job(self, job_id: str, description: str, parent_context: dict[str, Any]) -> None:
        def job_log(event_type: str, **payload: Any) -> None:
            with self.lock:
                job = self.jobs[job_id]
                job.logs.append(
                    {
                        "type": event_type,
                        "timestamp": _now(),
                        "payload": payload,
                    }
                )

        with self.lock:
            job = self.jobs[job_id]
            job.status = "running"
            job.started_at = _now()

        model_client = ModelClient(self.model_config, job_log)
        try:
            result = run_subagent(
                description=description,
                subagent_id=job_id,
                config=self.subagent_config,
                model_client=model_client,
                parent_log=job_log,
                parent_context=parent_context,
            )
            with self.lock:
                job = self.jobs[job_id]
                job.status = "success"
                job.result = result
                job.finished_at = _now()
        except Exception as exc:
            with self.lock:
                job = self.jobs[job_id]
                job.status = "failure"
                job.error = str(exc)
                job.finished_at = _now()


class BackgroundTaskTools:
    def __init__(self, manager: BackgroundTaskManager, parent_context_provider: Any) -> None:
        self.manager = manager
        self.parent_context_provider = parent_context_provider

    def start(self, arguments: dict[str, Any]) -> str:
        job = self.manager.start(
            description=str(arguments.get("description", "")),
            parent_context=self.parent_context_provider(),
        )
        return json.dumps({"background_task": job}, ensure_ascii=False)

    def list(self, arguments: dict[str, Any]) -> str:
        return json.dumps({"background_tasks": self.manager.list()}, ensure_ascii=False)

    def get(self, arguments: dict[str, Any]) -> str:
        job = self.manager.get(str(arguments.get("id", "")))
        return json.dumps({"background_task": job}, ensure_ascii=False)


class BackgroundNotificationHook:
    def __init__(self, manager: BackgroundTaskManager) -> None:
        self.manager = manager

    def __call__(self, context: Any) -> Any:
        if context.messages is None or context.log is None:
            return None
        notifications = self.manager.collect_notifications()
        if not notifications:
            return None

        content = "\n\n".join(_notification_text(item) for item in notifications)
        context.messages.append({"role": "user", "content": content})
        for item in notifications:
            context.log(
                "background_task_finished",
                result=item.get("status"),
                reason=item.get("error"),
                metadata={"turn": context.turn, "background_task": item},
            )
            context.log(
                "background_task_notification",
                content=_notification_text(item),
                result=item.get("status"),
                metadata={"turn": context.turn, "background_task": item},
            )
        return None


def _notification_text(job: dict[str, Any]) -> str:
    return (
        "<background_task_notification>\n"
        f"id: {job.get('id')}\n"
        f"status: {job.get('status')}\n"
        f"description: {job.get('description')}\n"
        f"result: {job.get('result') or job.get('error') or ''}\n"
        "</background_task_notification>"
    )


def _now() -> str:
    return datetime.now().astimezone().isoformat()

