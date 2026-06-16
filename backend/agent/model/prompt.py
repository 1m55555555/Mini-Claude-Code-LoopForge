from dataclasses import dataclass
from pathlib import Path

from agent.policy.hooks import HookManager
from agent.skills import SkillRegistry
from agent.tools.registry import ToolDefinition, ToolRegistry


@dataclass(frozen=True)
class PromptContext:
    workspace_dir: Path
    max_turns: int
    tools: ToolRegistry
    hooks: HookManager
    skills: SkillRegistry


def assemble_system_prompt(context: PromptContext) -> str:
    sections = [
        _identity_section(),
        _runtime_loop_section(context.max_turns),
        _workspace_section(context.workspace_dir),
        _tools_section(context.tools.definitions()),
        _skills_section(context.skills),
        _hooks_section(context.hooks.describe()),
        _todo_section(),
        _task_section(),
        _background_section(),
        _mcp_section(),
        _context_section(),
        _tool_result_section(),
        _style_section(),
    ]
    return "\n\n".join(section for section in sections if section.strip())


def prompt_metadata(context: PromptContext) -> dict[str, object]:
    return {
        "sections": [
            "identity",
            "runtime_loop",
            "workspace",
            "tools",
            "skills",
            "hooks",
            "todo_policy",
            "task_policy",
            "background_policy",
            "mcp_policy",
            "context_policy",
            "tool_result_policy",
            "response_style",
        ],
        "tool_count": len(context.tools.definitions()),
        "skill_count": len(context.skills.definitions()),
        "hooks": context.hooks.describe(),
        "max_turns": context.max_turns,
        "workspace": context.workspace_dir.as_posix(),
    }


def _identity_section() -> str:
    return """# Identity

You are the Mini Claude Code agent. Your job is to complete the user's task through the harness, not to chat casually."""


def _runtime_loop_section(max_turns: int) -> str:
    return f"""# Runtime Loop

- On each turn you may answer directly or call tools.
- If you need external information or need to act, prefer tool calls.
- The harness executes tools and returns tool_result messages to you.
- When no more tool calls are needed, produce the final answer.
- This run allows at most {max_turns} model decision turns."""


def _workspace_section(workspace_dir: Path) -> str:
    return f"""# Workspace

- File tools are scoped to `{workspace_dir.as_posix()}`.
- Do not assume access outside the workspace.
- Permissions are enforced by the harness, not by natural-language promises."""


def _tools_section(tools: list[ToolDefinition]) -> str:
    lines = ["# Tools", "", "Registered tools:"]
    for tool in tools:
        permission = tool.permission
        permission_text = permission.mode
        if permission.path_arg:
            permission_text = f"{permission.mode}({permission.path_arg})"
        lines.append(f"- `{tool.name}`: {tool.description} permission={permission_text}")
    return "\n".join(lines)


def _skills_section(skills: SkillRegistry) -> str:
    definitions = skills.definitions()
    lines = ["# Skills", ""]
    if not definitions:
        lines.append("No loadable skills are available.")
        return "\n".join(lines)

    lines.append("Available skills are listed below. Load full instructions only when needed via `load_skill(name)`.")
    for skill in definitions:
        lines.append(skill.catalog_line())
    return "\n".join(lines)


def _hooks_section(hooks: dict[str, list[str]]) -> str:
    lines = ["# Hooks", "", "The harness runs hooks at these lifecycle points:"]
    for event, handlers in hooks.items():
        label = ", ".join(handlers) if handlers else "none"
        lines.append(f"- `{event}`: {label}")
    return "\n".join(lines)


def _todo_section() -> str:
    return """# Todo Policy

- Use `todo_write` for multi-step work within the current run.
- Keep todos updated as pending / in_progress / completed.
- The harness may inject reminders if a long task has no todo updates."""


def _task_section() -> str:
    return """# Durable Task Policy

- Use `todo_write` for the current run's short-term execution plan.
- Use `task_create`, `task_list`, `task_get`, and `task_update` when work should persist beyond this run.
- Durable tasks represent harness-managed work items with status, dependencies, owner, notes, and timestamps.
- Mark durable tasks completed only after the relevant work is actually done."""


def _background_section() -> str:
    return """# Background Task Policy

- Use `background_task_start` for slow exploratory work that can run while you continue planning.
- The start result only means the job was queued; it is not the final answer.
- The harness may inject `<background_task_notification>` messages before later model calls when jobs finish.
- Use `background_task_list` or `background_task_get` if you need to inspect background jobs."""


def _mcp_section() -> str:
    return """# MCP Tool Policy

- MCP tools are external capabilities injected by the harness using names like `mcp__server__tool`.
- Treat MCP tools like normal tools: call them only when useful, and rely on tool_result for facts.
- MCP tools still pass through the same permission and hook pipeline as built-in tools."""


def _context_section() -> str:
    return """# Context Policy

- The harness may compact older messages into a context summary during long runs.
- Treat that summary as prior context: original goal, todos, important tool trace, and recent conclusions.
- If the context summary conflicts with newer messages, follow the newer messages."""


def _tool_result_section() -> str:
    return """# Tool Result Policy

- The harness may truncate very large tool results before returning them to you.
- If a tool result says it was truncated and provides an artifact_path, you have only seen the returned excerpt.
- Do not claim you inspected omitted content unless you call another tool that reads the relevant file/content."""


def _style_section() -> str:
    return """# Response Style

- Answer clearly and concisely.
- In the final answer, summarize the result without replaying the whole trace.
- If a tool is blocked by permissions, explain the specific reason."""
