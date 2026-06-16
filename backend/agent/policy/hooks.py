from dataclasses import dataclass
from typing import Any, Callable, Literal

from agent.policy.permissions import PermissionPolicy
from agent.observability.run_logger import RunLogger
from agent.tools.registry import ToolDefinition


HookEvent = Literal["UserPromptSubmit", "BeforeModelCall", "PreToolUse", "PostToolUse", "Stop"]


@dataclass(frozen=True)
class HookContext:
    run_id: str
    logger: RunLogger
    log: Callable[..., None] | None = None
    tool: ToolDefinition | None = None
    arguments: dict[str, Any] | None = None
    messages: list[dict[str, Any]] | None = None
    turn: int | None = None
    output: str | None = None
    result: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class HookResult:
    result: str = "allow"
    reason: str | None = None
    output: str | None = None
    metadata: dict[str, Any] | None = None


HookHandler = Callable[[HookContext], HookResult | None]


class HookManager:
    def __init__(self) -> None:
        self._handlers: dict[HookEvent, list[HookHandler]] = {
            "UserPromptSubmit": [],
            "BeforeModelCall": [],
            "PreToolUse": [],
            "PostToolUse": [],
            "Stop": [],
        }

    def register(self, event: HookEvent, handler: HookHandler) -> None:
        self._handlers[event].append(handler)

    def describe(self) -> dict[str, list[str]]:
        description: dict[str, list[str]] = {}
        for event, handlers in self._handlers.items():
            description[event] = [handler.__class__.__name__ for handler in handlers]
        return description

    def run(self, event: HookEvent, context: HookContext) -> list[HookResult]:
        results: list[HookResult] = []
        for handler in self._handlers[event]:
            result = handler(context)
            if result is not None:
                results.append(result)
        return results


class PermissionHook:
    def __init__(self, policy: PermissionPolicy) -> None:
        self.policy = policy

    def __call__(self, context: HookContext) -> HookResult:
        if context.tool is None:
            return HookResult(result="deny", reason="missing tool definition")

        permission = self.policy.check_tool(context.tool.permission, context.arguments or {})
        return HookResult(
            result=permission.result,
            reason=permission.reason,
            output=permission.reason,
            metadata={"hook": "PermissionHook"},
        )

