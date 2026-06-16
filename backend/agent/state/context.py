from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContextConfig:
    compact_after_chars: int = 12000
    keep_recent_messages: int = 10
    max_summary_chars: int = 3000
    max_tool_output_chars: int = 600


@dataclass(frozen=True)
class ContextSnapshot:
    before_messages: int
    after_messages: int
    before_chars: int
    after_chars: int
    compacted_messages: int
    summary_chars: int
    reason: str
    preserved: dict[str, Any]


class ContextManager:
    def __init__(self, config: ContextConfig) -> None:
        self.config = config
        self.compaction_count = 0

    def maybe_compact(
        self,
        *,
        messages: list[dict[str, Any]],
        task: str,
        todos: list[dict[str, str]],
        turn: int,
    ) -> ContextSnapshot | None:
        before_chars = _messages_chars(messages)
        if before_chars < self.config.compact_after_chars:
            return None
        if len(messages) <= self.config.keep_recent_messages + 2:
            return None

        system_message = messages[0] if messages and messages[0].get("role") == "system" else None
        recent = _recent_safe_suffix(messages, self.config.keep_recent_messages)
        recent_ids = {id(message) for message in recent}
        dropped = [
            message
            for message in messages[1:]
            if id(message) not in recent_ids
        ]
        if not dropped:
            return None

        self.compaction_count += 1
        summary, preserved = self._build_summary(
            task=task,
            todos=todos,
            turn=turn,
            dropped=dropped,
        )
        summary_message = {
            "role": "system",
            "content": summary,
        }
        compacted = ([system_message] if system_message is not None else []) + [summary_message] + recent
        messages[:] = compacted

        after_chars = _messages_chars(messages)
        return ContextSnapshot(
            before_messages=len(dropped) + len(recent) + (1 if system_message is not None else 0),
            after_messages=len(messages),
            before_chars=before_chars,
            after_chars=after_chars,
            compacted_messages=len(dropped),
            summary_chars=len(summary),
            reason=f"context exceeded {self.config.compact_after_chars} chars before turn {turn}",
            preserved=preserved,
        )

    def _build_summary(
        self,
        *,
        task: str,
        todos: list[dict[str, str]],
        turn: int,
        dropped: list[dict[str, Any]],
    ) -> tuple[str, dict[str, Any]]:
        tool_calls: list[dict[str, str]] = []
        assistant_notes: list[str] = []
        user_notes: list[str] = []

        for message in dropped:
            role = str(message.get("role", ""))
            content = _string_content(message.get("content"))
            if role == "user" and content:
                user_notes.append(_truncate(content, 500))
            elif role == "assistant":
                calls = message.get("tool_calls") or []
                if calls:
                    for call in calls:
                        function = call.get("function", {}) if isinstance(call, dict) else {}
                        tool_calls.append(
                            {
                                "tool": str(function.get("name", "unknown")),
                                "arguments": _truncate(str(function.get("arguments", "")), 300),
                            }
                        )
                if content:
                    assistant_notes.append(_truncate(content, 500))
            elif role == "tool":
                tool_calls.append(
                    {
                        "tool": "tool_result",
                        "output": _truncate(content, self.config.max_tool_output_chars),
                    }
                )

        preserved = {
            "task": task,
            "turn": turn,
            "todos": todos,
            "user_notes": user_notes[-4:],
            "assistant_notes": assistant_notes[-4:],
            "tool_trace": tool_calls[-10:],
        }
        summary = (
            "Harness context compaction summary.\n"
            "The older conversation was compressed to protect the agent from forgetting the goal.\n"
            "Use this summary as prior context, but prefer recent messages when details conflict.\n\n"
            f"{json.dumps(preserved, ensure_ascii=False, indent=2)}"
        )
        return _truncate(summary, self.config.max_summary_chars), preserved


def _recent_safe_suffix(messages: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    recent = list(messages[-limit:])
    while recent and recent[0].get("role") == "tool":
        recent.pop(0)
    return recent


def _messages_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(_string_content(message.get("content"))) + len(str(message.get("tool_calls", ""))) for message in messages)


def _string_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."

