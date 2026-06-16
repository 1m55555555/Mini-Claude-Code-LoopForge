import os
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.execution.background import BackgroundNotificationHook, BackgroundTaskManager, BackgroundTaskTools
from agent.state.context import ContextConfig, ContextManager
from agent.policy.hooks import HookContext, HookManager, PermissionHook
from agent.tools.mcp import MCPClient
from agent.model.client import ModelCallError, ModelClient, ModelConfig
from agent.policy.permissions import PermissionPolicy
from agent.model.prompt import PromptContext, assemble_system_prompt, prompt_metadata
from agent.observability.run_logger import RunLogger
from agent.schemas import RunEvent, RunRequest, RunResponse
from agent.skills import SkillRegistry
from agent.execution.subagents import SubagentConfig, TaskHandler
from agent.state.tasks import TaskStore, TaskStoreTools
from agent.state.todos import TodoReminderHook, TodoState, TodoWriteHandler
from agent.tools.results import ToolResultConfig, ToolResultManager
from agent.tools.registry import ToolError, ToolRegistry


MAX_TURNS = 12


@dataclass(frozen=True)
class AgentConfig:
    api_key: str
    model: str
    base_url: str
    workspace_dir: Path
    skills_dir: Path
    model_mode: str = "api"
    max_turns: int = MAX_TURNS
    model_max_retries: int = 2
    model_timeout_seconds: float = 8.0
    subagent_max_turns: int = 3
    subagent_timeout_seconds: float = 30.0
    subagent_max_tool_calls: int = 8
    context_compact_after_chars: int = 12000
    context_keep_recent_messages: int = 10
    context_max_summary_chars: int = 3000
    tool_result_max_inline_chars: int = 4000
    tool_result_head_chars: int = 2200
    tool_result_tail_chars: int = 1000
    background_max_workers: int = 2

    @classmethod
    def from_env(cls, workspace_dir: Path) -> "AgentConfig":
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not set")

        return cls(
            api_key=api_key,
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model_mode=os.getenv("AGENT_MODEL_MODE", "api").strip().lower(),
            workspace_dir=workspace_dir,
            skills_dir=workspace_dir.resolve().parents[1] / "backend" / "skills",
            max_turns=int(os.getenv("AGENT_MAX_TURNS", str(MAX_TURNS))),
            model_max_retries=int(os.getenv("MODEL_MAX_RETRIES", "0")),
            model_timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "8")),
            subagent_max_turns=int(os.getenv("SUBAGENT_MAX_TURNS", "3")),
            subagent_timeout_seconds=float(os.getenv("SUBAGENT_TIMEOUT_SECONDS", "30")),
            subagent_max_tool_calls=int(os.getenv("SUBAGENT_MAX_TOOL_CALLS", "8")),
            context_compact_after_chars=int(os.getenv("CONTEXT_COMPACT_AFTER_CHARS", "12000")),
            context_keep_recent_messages=int(os.getenv("CONTEXT_KEEP_RECENT_MESSAGES", "10")),
            context_max_summary_chars=int(os.getenv("CONTEXT_MAX_SUMMARY_CHARS", "3000")),
            tool_result_max_inline_chars=int(os.getenv("TOOL_RESULT_MAX_INLINE_CHARS", "4000")),
            tool_result_head_chars=int(os.getenv("TOOL_RESULT_HEAD_CHARS", "2200")),
            tool_result_tail_chars=int(os.getenv("TOOL_RESULT_TAIL_CHARS", "1000")),
            background_max_workers=int(os.getenv("BACKGROUND_MAX_WORKERS", "2")),
        )


def run_agent(
    request: RunRequest,
    logger: RunLogger,
    config: AgentConfig,
) -> RunResponse:
    run_id = logger.create_run_id()
    events: list[RunEvent] = []
    sequence = 1

    def log(event_type: str, **payload: object) -> None:
        nonlocal sequence
        events.append(logger.append(run_id, event_type, sequence, **payload))
        sequence += 1

    log("run_started", metadata={"model": config.model})

    model_config = ModelConfig(
        api_key=config.api_key,
        model=config.model,
        base_url=config.base_url,
        max_retries=config.model_max_retries,
        timeout_seconds=config.model_timeout_seconds,
        mode=config.model_mode,
    )
    model_client = ModelClient(model_config, log)
    current_turn = 0

    def get_current_turn() -> int:
        return current_turn

    messages: list[dict[str, Any]] = []
    context_manager = ContextManager(
        ContextConfig(
            compact_after_chars=config.context_compact_after_chars,
            keep_recent_messages=config.context_keep_recent_messages,
            max_summary_chars=config.context_max_summary_chars,
        )
    )
    tool_result_manager = ToolResultManager(
        runs_dir=logger.runs_dir,
        run_id=run_id,
        config=ToolResultConfig(
            max_inline_chars=config.tool_result_max_inline_chars,
            head_chars=config.tool_result_head_chars,
            tail_chars=config.tool_result_tail_chars,
        ),
    )

    todo_state = TodoState()
    task_store = TaskStore(config.workspace_dir.parent / "tasks" / "tasks.json")
    task_store_tools = TaskStoreTools(task_store)
    skills = SkillRegistry(config.skills_dir)

    def parent_context() -> dict[str, Any]:
        return {
            "parent_task": request.task,
            "parent_turn": current_turn,
            "todos": todo_state.as_dicts(),
            "task_counts": task_store.counts(),
            "recent_messages": _recent_message_summary(messages),
            "workspace": config.workspace_dir.resolve().as_posix(),
        }

    background_manager = BackgroundTaskManager(
        model_config=model_config,
        subagent_config=SubagentConfig(
            workspace_dir=config.workspace_dir,
            skills_dir=config.skills_dir,
            max_turns=config.subagent_max_turns,
            timeout_seconds=config.subagent_timeout_seconds,
            max_tool_calls=config.subagent_max_tool_calls,
        ),
        max_workers=config.background_max_workers,
    )
    background_tools = BackgroundTaskTools(background_manager, parent_context)
    mcp_client = MCPClient.default_mock()
    mcp_tools = mcp_client.tool_definitions(log)

    tools = ToolRegistry(
        config.workspace_dir,
        todo_write_handler=TodoWriteHandler(todo_state, get_current_turn),
        load_skill_handler=skills.load_skill,
        task_create_handler=task_store_tools.create,
        task_list_handler=task_store_tools.list,
        task_get_handler=task_store_tools.get,
        task_update_handler=task_store_tools.update,
        background_task_start_handler=background_tools.start,
        background_task_list_handler=background_tools.list,
        background_task_get_handler=background_tools.get,
        external_tools=mcp_tools,
        task_handler=TaskHandler(
            SubagentConfig(
                workspace_dir=config.workspace_dir,
                skills_dir=config.skills_dir,
                max_turns=config.subagent_max_turns,
                timeout_seconds=config.subagent_timeout_seconds,
                max_tool_calls=config.subagent_max_tool_calls,
            ),
            model_client,
            log,
            parent_context,
        ),
    )
    permissions = PermissionPolicy(config.workspace_dir)
    hooks = HookManager()
    hooks.register("PreToolUse", PermissionHook(permissions))
    hooks.register("BeforeModelCall", BackgroundNotificationHook(background_manager))
    hooks.register("BeforeModelCall", TodoReminderHook(todo_state))
    prompt_context = PromptContext(
        workspace_dir=config.workspace_dir.resolve(),
        max_turns=config.max_turns,
        tools=tools,
        hooks=hooks,
        skills=skills,
    )
    system_prompt = assemble_system_prompt(prompt_context)
    log("prompt_built", metadata=prompt_metadata(prompt_context))
    log("user_message", content=request.task)

    messages.extend(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": request.task},
        ]
    )
    hooks.run(
        "UserPromptSubmit",
        HookContext(
            run_id=run_id,
            logger=logger,
            metadata={"task": request.task},
        ),
    )

    answer = ""
    try:
        for turn in range(1, config.max_turns + 1):
            current_turn = turn
            hooks.run(
                "BeforeModelCall",
                HookContext(
                    run_id=run_id,
                    logger=logger,
                    log=log,
                    messages=messages,
                    turn=turn,
                ),
            )
            compaction = context_manager.maybe_compact(
                messages=messages,
                task=request.task,
                todos=todo_state.as_dicts(),
                turn=turn,
            )
            if compaction is not None:
                log(
                    "context_compacted",
                    result="success",
                    reason=compaction.reason,
                    metadata={
                        "turn": turn,
                        "before_messages": compaction.before_messages,
                        "after_messages": compaction.after_messages,
                        "before_chars": compaction.before_chars,
                        "after_chars": compaction.after_chars,
                        "compacted_messages": compaction.compacted_messages,
                        "summary_chars": compaction.summary_chars,
                        "preserved": compaction.preserved,
                    },
                )
            completion = model_client.create_completion(
                messages=messages,
                tools=tools.openai_tools(),
                turn=turn,
                metadata={
                    "message_count": len(messages),
                    "context_chars": sum(len(str(item.get("content", ""))) for item in messages),
                },
            )
            message = completion.choices[0].message
            usage = completion.usage.model_dump() if completion.usage is not None else None
            tool_calls = list(message.tool_calls or [])
            content = message.content or ""

            assistant_message = message.model_dump(exclude_none=True)
            messages.append(assistant_message)
            log(
                "assistant_message",
                content=content,
                metadata={
                    "turn": turn,
                    "usage": usage,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        }
                        for call in tool_calls
                    ],
                },
            )

            if not tool_calls:
                answer = content
                hooks.run(
                    "Stop",
                    HookContext(
                        run_id=run_id,
                        logger=logger,
                        output=answer,
                        result="success",
                        metadata={"turn": turn},
                    ),
                )
                log("final", content=answer)
                log("run_finished", result="success", metadata={"turns": turn})
                return RunResponse(run_id=run_id, answer=answer, events=events)

            for call in tool_calls:
                tool_name = call.function.name
                raw_arguments = call.function.arguments or "{}"
                try:
                    arguments = json.loads(raw_arguments)
                except json.JSONDecodeError as exc:
                    arguments = {}
                    output = f"invalid tool arguments: {exc}"
                    managed = tool_result_manager.manage(tool_name=tool_name, output=output, status="error")
                    log("tool_use", tool=tool_name, input={"raw": raw_arguments})
                    log("permission_check", tool=tool_name, result="deny", reason=output)
                    log("tool_result", tool=tool_name, output=managed.message_output, result="error", metadata=managed.metadata)
                    messages.append(_tool_message(call.id, managed.message_output))
                    continue

                log("tool_use", tool=tool_name, input=arguments)
                try:
                    tool = tools.get(tool_name)
                except ToolError:
                    permission = permissions.check_unknown_tool(tool_name)
                    log(
                        "permission_check",
                        tool=tool_name,
                        result=permission.result,
                        reason=permission.reason,
                        metadata={"hook": "PermissionHook"},
                    )
                    output = permission.reason or "permission denied"
                    managed = tool_result_manager.manage(tool_name=tool_name, output=output, status="denied")
                    log("tool_result", tool=tool_name, output=managed.message_output, result="denied", metadata=managed.metadata)
                    messages.append(_tool_message(call.id, managed.message_output))
                    continue

                pre_tool_results = hooks.run(
                    "PreToolUse",
                    HookContext(
                        run_id=run_id,
                        logger=logger,
                        tool=tool,
                        arguments=arguments,
                    ),
                )
                permission = _first_blocking_result(pre_tool_results)
                if permission is None:
                    permission = pre_tool_results[-1] if pre_tool_results else None
                log(
                    "permission_check",
                    tool=tool_name,
                    result=permission.result if permission is not None else "allow",
                    reason=permission.reason if permission is not None else None,
                    metadata=permission.metadata if permission is not None else None,
                )
                if permission is not None and permission.result != "allow":
                    output = permission.output or permission.reason or "permission denied"
                    status = _blocked_status(permission.result)
                    managed = tool_result_manager.manage(tool_name=tool_name, output=output, status=status)
                    log("tool_result", tool=tool_name, output=managed.message_output, result=status, metadata=managed.metadata)
                    messages.append(_tool_message(call.id, managed.message_output))
                    continue

                try:
                    result = tool.handler(arguments)
                    output = result.output
                    status = "success"
                except ToolError as exc:
                    output = str(exc)
                    status = "error"

                hooks.run(
                    "PostToolUse",
                    HookContext(
                        run_id=run_id,
                        logger=logger,
                        tool=tool,
                        arguments=arguments,
                        output=output,
                        result=status,
                    ),
                )
                managed = tool_result_manager.manage(tool_name=tool_name, output=output, status=status)
                log("tool_result", tool=tool_name, output=managed.message_output, result=status, metadata=managed.metadata)
                if tool_name == "todo_write" and status == "success":
                    log(
                        "todo_updated",
                        metadata={
                            "turn": turn,
                            "todos": todo_state.as_dicts(),
                            "counts": todo_state.counts(),
                        },
                    )
                if tool_name == "load_skill" and status == "success":
                    log(
                        "skill_loaded",
                        tool=tool_name,
                        metadata={
                            "turn": turn,
                            "name": arguments.get("name"),
                            "chars": len(output),
                            "returned_chars": managed.metadata.get("returned_chars"),
                            "truncated": managed.metadata.get("truncated"),
                        },
                    )
                if tool_name.startswith("task_") and status == "success":
                    _log_task_lifecycle(tool_name, output, turn, log)
                if tool_name.startswith("background_task_") and status == "success":
                    _log_background_lifecycle(tool_name, output, turn, log)
                if tool_name.startswith("mcp__"):
                    _log_mcp_call(tool_name, arguments, status, turn, log)
                messages.append(_tool_message(call.id, managed.message_output))

        answer = f"Reached max turns ({config.max_turns}); agent stopped."
        hooks.run(
            "Stop",
            HookContext(
                run_id=run_id,
                logger=logger,
                output=answer,
                result="failure",
                reason="max turns reached",
            ),
        )
        log("final", content=answer)
        log("run_finished", result="failure", reason="max turns reached")
    except ModelCallError as exc:
        log("run_finished", result="failure", reason=str(exc), metadata={"category": exc.category})
        raise RuntimeError(f"run {run_id} failed: {exc}") from exc
    except Exception as exc:
        log("run_finished", result="failure", reason=str(exc))
        raise RuntimeError(f"run {run_id} failed: {exc}") from exc

    return RunResponse(run_id=run_id, answer=answer, events=events)


def _first_blocking_result(results: list[object]) -> Any | None:
    for result in results:
        if getattr(result, "result", None) != "allow":
            return result
    return None


def _blocked_status(result: str) -> str:
    if result == "deny":
        return "denied"
    return result


def _log_task_lifecycle(tool_name: str, output: str, turn: int, log: Any) -> None:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return
    task = payload.get("task")
    if not isinstance(task, dict):
        return
    metadata = {
        "turn": turn,
        "task": task,
        "counts": payload.get("counts"),
    }
    if tool_name == "task_create":
        log("task_created", metadata=metadata)
        if task.get("status") == "completed":
            log("task_completed", metadata=metadata)
    elif tool_name == "task_update":
        log("task_updated", metadata=metadata)
        if task.get("status") == "completed":
            log("task_completed", metadata=metadata)


def _log_background_lifecycle(tool_name: str, output: str, turn: int, log: Any) -> None:
    if tool_name != "background_task_start":
        return
    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return
    background_task = payload.get("background_task")
    if not isinstance(background_task, dict):
        return
    log(
        "background_task_started",
        result=background_task.get("status"),
        metadata={"turn": turn, "background_task": background_task},
    )


def _log_mcp_call(tool_name: str, arguments: dict[str, Any], status: str, turn: int, log: Any) -> None:
    parts = tool_name.split("__", 2)
    if len(parts) != 3:
        return
    _, server, name = parts
    log(
        "mcp_tool_called",
        tool=tool_name,
        input=arguments,
        result=status,
        metadata={"turn": turn, "server": server, "name": name},
    )


def _recent_message_summary(messages: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for message in messages[-limit:]:
        role = str(message.get("role", ""))
        content = str(message.get("content", ""))
        if not content:
            continue
        summary.append({"role": role, "content": content[:500]})
    return summary


def _tool_message(tool_call_id: str, output: str) -> dict[str, str]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": output,
    }

