from typing import Any, Literal

from pydantic import BaseModel, Field


EventType = Literal[
    "run_started",
    "prompt_built",
    "user_message",
    "model_call_started",
    "model_retry",
    "model_call_failed",
    "context_compacted",
    "background_task_started",
    "background_task_finished",
    "background_task_notification",
    "mcp_tool_discovered",
    "mcp_tool_called",
    "skill_loaded",
    "subagent_started",
    "subagent_finished",
    "assistant_message",
    "tool_use",
    "permission_check",
    "tool_result",
    "task_created",
    "task_updated",
    "task_completed",
    "todo_updated",
    "todo_reminder",
    "final",
    "run_finished",
]


class RunRequest(BaseModel):
    task: str = Field(..., min_length=1)


class RunEvent(BaseModel):
    id: str
    run_id: str
    type: EventType
    timestamp: str
    content: str | None = None
    tool: str | None = None
    input: dict[str, Any] | None = None
    output: str | None = None
    result: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None


class RunResponse(BaseModel):
    run_id: str
    answer: str
    events: list[RunEvent]

