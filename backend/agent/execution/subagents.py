import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent.errors import ToolError
from agent.policy.hooks import HookContext, HookManager, PermissionHook
from agent.model.client import ModelClient
from agent.policy.permissions import PermissionPolicy
from agent.model.prompt import PromptContext, assemble_system_prompt
from agent.skills import SkillRegistry
from agent.state.todos import TodoReminderHook, TodoState, TodoWriteHandler
from agent.tools.registry import ToolRegistry, ToolResult


@dataclass(frozen=True)
class SubagentConfig:
    workspace_dir: Path
    skills_dir: Path
    max_turns: int = 3
    timeout_seconds: float = 30.0
    max_tool_calls: int = 8
    max_result_chars: int = 4_000


class TaskHandler:
    def __init__(
        self,
        config: SubagentConfig,
        model_client: ModelClient,
        parent_log: Callable[..., None],
        parent_context_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self.config = config
        self.model_client = model_client
        self.parent_log = parent_log
        self.parent_context_provider = parent_context_provider
        self.next_id = 1

    def __call__(self, arguments: dict[str, Any]) -> ToolResult:
        description = str(arguments.get("description", "")).strip()
        if not description:
            raise ToolError("description is required")

        subagent_id = f"subagent-{self.next_id:03d}"
        self.next_id += 1
        self.parent_log(
            "subagent_started",
            metadata={"subagent_id": subagent_id, "description": description},
        )
        try:
            answer = run_subagent(
                description=description,
                subagent_id=subagent_id,
                config=self.config,
                model_client=self.model_client,
                parent_log=self.parent_log,
                parent_context=self.parent_context_provider(),
            )
        except Exception as exc:
            self.parent_log(
                "subagent_finished",
                result="failure",
                reason=str(exc),
                metadata={"subagent_id": subagent_id, "circuit_breaker": True},
            )
            raise

        if len(answer) > self.config.max_result_chars:
            answer = answer[: self.config.max_result_chars] + "\n\n[瀛?Agent 缁撴灉杩囬暱锛屽凡鎴柇銆俔"

        self.parent_log(
            "subagent_finished",
            result="success",
            metadata={
                "subagent_id": subagent_id,
                "summary_chars": len(answer),
                "max_result_chars": self.config.max_result_chars,
            },
        )
        return ToolResult(output=answer)


def run_subagent(
    *,
    description: str,
    subagent_id: str,
    config: SubagentConfig,
    model_client: ModelClient,
    parent_log: Callable[..., None],
    parent_context: dict[str, Any],
) -> str:
    current_turn = 0
    tool_call_count = 0
    started_at = time.monotonic()

    def current_turn_provider() -> int:
        return current_turn

    todo_state = TodoState()
    skills = SkillRegistry(config.skills_dir)
    tools = ToolRegistry(
        config.workspace_dir,
        todo_write_handler=TodoWriteHandler(todo_state, current_turn_provider),
        load_skill_handler=skills.load_skill,
        task_handler=None,
    )
    permissions = PermissionPolicy(config.workspace_dir)
    hooks = HookManager()
    hooks.register("PreToolUse", PermissionHook(permissions))
    hooks.register("BeforeModelCall", TodoReminderHook(todo_state))

    system_prompt = assemble_system_prompt(
        PromptContext(
            workspace_dir=config.workspace_dir.resolve(),
            max_turns=config.max_turns,
            tools=tools,
            hooks=hooks,
            skills=skills,
        )
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": _build_subagent_prompt(description, parent_context),
        },
    ]

    answer = ""
    for turn in range(1, config.max_turns + 1):
        _check_budget(config, started_at, tool_call_count)
        current_turn = turn
        hooks.run(
            "BeforeModelCall",
            HookContext(
                run_id=subagent_id,
                logger=None,  # type: ignore[arg-type]
                log=lambda event_type, **payload: _sub_log(parent_log, subagent_id, event_type, **payload),
                messages=messages,
                turn=turn,
            ),
        )
        completion = model_client.create_completion(
            messages=messages,
            tools=tools.openai_tools(),
            turn=turn,
            metadata={"subagent_id": subagent_id},
        )
        message = completion.choices[0].message
        tool_calls = list(message.tool_calls or [])
        content = message.content or ""
        messages.append(message.model_dump(exclude_none=True))

        _sub_log(
            parent_log,
            subagent_id,
            "assistant_message",
            content=content,
            metadata={"turn": turn, "subagent_id": subagent_id},
        )

        if not tool_calls:
            return content

        for call in tool_calls:
            tool_call_count += 1
            _check_budget(config, started_at, tool_call_count)
            tool_name = call.function.name
            raw_arguments = call.function.arguments or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError as exc:
                output = f"invalid tool arguments: {exc}"
                _sub_log(parent_log, subagent_id, "tool_use", tool=tool_name, input={"raw": raw_arguments})
                _sub_log(parent_log, subagent_id, "tool_result", tool=tool_name, output=output, result="error")
                messages.append(_tool_message(call.id, output))
                continue

            _sub_log(parent_log, subagent_id, "tool_use", tool=tool_name, input=arguments)
            try:
                tool = tools.get(tool_name)
            except ToolError as exc:
                output = str(exc)
                _sub_log(parent_log, subagent_id, "tool_result", tool=tool_name, output=output, result="denied")
                messages.append(_tool_message(call.id, output))
                continue

            permission = hooks.run(
                "PreToolUse",
                HookContext(
                    run_id=subagent_id,
                    logger=None,  # type: ignore[arg-type]
                    tool=tool,
                    arguments=arguments,
                ),
            )[-1]
            _sub_log(
                parent_log,
                subagent_id,
                "permission_check",
                tool=tool_name,
                result=permission.result,
                reason=permission.reason,
                metadata=permission.metadata,
            )
            if permission.result != "allow":
                output = permission.output or permission.reason or "permission denied"
                _sub_log(parent_log, subagent_id, "tool_result", tool=tool_name, output=output, result="denied")
                messages.append(_tool_message(call.id, output))
                continue

            try:
                result = tool.handler(arguments)
                output = result.output
                status = "success"
            except ToolError as exc:
                output = str(exc)
                status = "error"

            _sub_log(parent_log, subagent_id, "tool_result", tool=tool_name, output=output, result=status)
            messages.append(_tool_message(call.id, output))

    answer = f"Subagent reached max turns ({config.max_turns}); returning current summary."
    return answer


def _build_subagent_prompt(description: str, parent_context: dict[str, Any]) -> str:
    return "\n".join(
        [
            "You are an isolated subagent.",
            "Only solve the local task below and return a concise summary when finished.",
            "Do not assume you have the parent agent's full context; use only the provided parent context fields.",
            "",
            "# Subtask",
            description,
            "",
            "# Parent Context",
            json.dumps(parent_context, ensure_ascii=False, indent=2),
        ]
    )


def _check_budget(config: SubagentConfig, started_at: float, tool_call_count: int) -> None:
    elapsed = time.monotonic() - started_at
    if elapsed > config.timeout_seconds:
        raise ToolError(f"subagent timeout after {config.timeout_seconds:.1f}s")
    if tool_call_count > config.max_tool_calls:
        raise ToolError(f"subagent exceeded max tool calls: {config.max_tool_calls}")


def _sub_log(parent_log: Callable[..., None], subagent_id: str, event_type: str, **payload: Any) -> None:
    metadata = dict(payload.pop("metadata", {}) or {})
    metadata["subagent_id"] = subagent_id
    parent_log(event_type, metadata=metadata, **payload)


def _tool_message(tool_call_id: str, output: str) -> dict[str, str]:
    return {"role": "tool", "tool_call_id": tool_call_id, "content": output}

