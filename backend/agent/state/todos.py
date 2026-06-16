import json
from dataclasses import dataclass
from typing import Any

from agent.errors import ToolError
from agent.policy.hooks import HookContext, HookResult


@dataclass(frozen=True)
class TodoItem:
    content: str
    status: str

    def model_dump(self) -> dict[str, str]:
        return {"content": self.content, "status": self.status}


class TodoState:
    def __init__(self) -> None:
        self.items: list[TodoItem] = []
        self.last_updated_turn: int | None = None

    def update(self, raw_items: Any, turn: int) -> list[dict[str, str]]:
        if not isinstance(raw_items, list):
            raise ToolError("todos must be a list")

        normalized: list[TodoItem] = []
        for item in raw_items:
            if not isinstance(item, dict):
                raise ToolError("todo item must be an object")
            content = str(item.get("content", "")).strip()
            status = str(item.get("status", "")).strip()
            if not content or status not in {"pending", "in_progress", "completed"}:
                raise ToolError("todo item requires content and valid status")
            normalized.append(TodoItem(content=content, status=status))

        self.items = normalized
        self.last_updated_turn = turn
        return self.as_dicts()

    def as_dicts(self) -> list[dict[str, str]]:
        return [item.model_dump() for item in self.items]

    def counts(self) -> dict[str, int]:
        counts = {"pending": 0, "in_progress": 0, "completed": 0}
        for item in self.items:
            counts[item.status] += 1
        return counts


class TodoWriteHandler:
    def __init__(self, state: TodoState, turn_provider: Any) -> None:
        self.state = state
        self.turn_provider = turn_provider

    def __call__(self, arguments: dict[str, Any]) -> str:
        todos = self.state.update(arguments.get("todos"), self.turn_provider())
        return json.dumps({"todos": todos}, ensure_ascii=False)


class TodoReminderHook:
    def __init__(self, state: TodoState, remind_after_turn: int = 3) -> None:
        self.state = state
        self.remind_after_turn = remind_after_turn
        self.sent = False

    def __call__(self, context: HookContext) -> HookResult | None:
        if self.sent:
            return None
        if context.turn is None or context.turn < self.remind_after_turn:
            return None
        if self.state.last_updated_turn is not None:
            return None
        if context.messages is None or context.log is None:
            return None

        content = (
            "system reminder: this appears to be a multi-step task. "
            "If planning is useful, call todo_write with pending / in_progress / completed items."
        )
        context.messages.append({"role": "user", "content": content})
        context.log(
            "todo_reminder",
            content=content,
            metadata={"turn": context.turn, "hook": "TodoReminderHook"},
        )
        self.sent = True
        return HookResult(result="allow", metadata={"hook": "TodoReminderHook"})
