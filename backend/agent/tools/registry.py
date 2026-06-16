from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from agent.errors import ToolError
from agent.policy.permissions import ToolPermission


@dataclass(frozen=True)
class ToolResult:
    output: str


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any]], ToolResult]
    permission: ToolPermission

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(
        self,
        workspace_dir: Path,
        todo_write_handler: Callable[[dict[str, Any]], str] | None = None,
        load_skill_handler: Callable[[dict[str, Any]], ToolResult] | None = None,
        task_handler: Callable[[dict[str, Any]], ToolResult] | None = None,
        task_create_handler: Callable[[dict[str, Any]], str] | None = None,
        task_list_handler: Callable[[dict[str, Any]], str] | None = None,
        task_get_handler: Callable[[dict[str, Any]], str] | None = None,
        task_update_handler: Callable[[dict[str, Any]], str] | None = None,
        background_task_start_handler: Callable[[dict[str, Any]], str] | None = None,
        background_task_list_handler: Callable[[dict[str, Any]], str] | None = None,
        background_task_get_handler: Callable[[dict[str, Any]], str] | None = None,
        external_tools: list[ToolDefinition] | None = None,
    ) -> None:
        self.workspace_dir = workspace_dir.resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.todo_write_handler = todo_write_handler
        self.load_skill_handler = load_skill_handler
        self.task_handler = task_handler
        self.task_create_handler = task_create_handler
        self.task_list_handler = task_list_handler
        self.task_get_handler = task_get_handler
        self.task_update_handler = task_update_handler
        self.background_task_start_handler = background_task_start_handler
        self.background_task_list_handler = background_task_list_handler
        self.background_task_get_handler = background_task_get_handler
        self._tools: dict[str, ToolDefinition] = {}
        self._register_builtin_tools()
        if self.task_handler is not None:
            self._register_task_tool()
        for tool in external_tools or []:
            self.register(tool)

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            raise ToolError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def openai_tools(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def definitions(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        return self.get(name).handler(arguments)

    def get(self, name: str) -> ToolDefinition:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"unknown tool: {name}")
        return tool

    def read_file(self, arguments: dict[str, Any]) -> ToolResult:
        path = str(arguments.get("path", ""))
        target = self._resolve_workspace_path(path)
        if not target.exists() or not target.is_file():
            raise ToolError(f"file not found: {path}")
        return ToolResult(output=target.read_text(encoding="utf-8"))

    def write_file(self, arguments: dict[str, Any]) -> ToolResult:
        path = str(arguments.get("path", ""))
        if "content" not in arguments:
            raise ToolError("content is required")

        target = self._resolve_workspace_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = str(arguments["content"])
        target.write_text(content, encoding="utf-8")
        rel = target.relative_to(self.workspace_dir).as_posix()
        return ToolResult(output=f"wrote {rel} ({len(content)} chars)")

    def search(self, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query", ""))
        if not query:
            raise ToolError("query is required")

        matches: list[str] = []
        for path in self.workspace_dir.rglob("*"):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for line_no, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    rel = path.relative_to(self.workspace_dir).as_posix()
                    matches.append(f"{rel}:{line_no}: {line}")

        output = "\n".join(matches) if matches else "no matches found"
        return ToolResult(output=output)

    def todo_write(self, arguments: dict[str, Any]) -> ToolResult:
        if self.todo_write_handler is None:
            raise ToolError("todo_write handler is not configured")
        return ToolResult(output=self.todo_write_handler(arguments))

    def load_skill(self, arguments: dict[str, Any]) -> ToolResult:
        if self.load_skill_handler is None:
            raise ToolError("load_skill handler is not configured")
        return self.load_skill_handler(arguments)

    def task(self, arguments: dict[str, Any]) -> ToolResult:
        if self.task_handler is None:
            raise ToolError("task handler is not configured")
        return self.task_handler(arguments)

    def task_create(self, arguments: dict[str, Any]) -> ToolResult:
        if self.task_create_handler is None:
            raise ToolError("task_create handler is not configured")
        return ToolResult(output=self.task_create_handler(arguments))

    def task_list(self, arguments: dict[str, Any]) -> ToolResult:
        if self.task_list_handler is None:
            raise ToolError("task_list handler is not configured")
        return ToolResult(output=self.task_list_handler(arguments))

    def task_get(self, arguments: dict[str, Any]) -> ToolResult:
        if self.task_get_handler is None:
            raise ToolError("task_get handler is not configured")
        return ToolResult(output=self.task_get_handler(arguments))

    def task_update(self, arguments: dict[str, Any]) -> ToolResult:
        if self.task_update_handler is None:
            raise ToolError("task_update handler is not configured")
        return ToolResult(output=self.task_update_handler(arguments))

    def background_task_start(self, arguments: dict[str, Any]) -> ToolResult:
        if self.background_task_start_handler is None:
            raise ToolError("background_task_start handler is not configured")
        return ToolResult(output=self.background_task_start_handler(arguments))

    def background_task_list(self, arguments: dict[str, Any]) -> ToolResult:
        if self.background_task_list_handler is None:
            raise ToolError("background_task_list handler is not configured")
        return ToolResult(output=self.background_task_list_handler(arguments))

    def background_task_get(self, arguments: dict[str, Any]) -> ToolResult:
        if self.background_task_get_handler is None:
            raise ToolError("background_task_get handler is not configured")
        return ToolResult(output=self.background_task_get_handler(arguments))

    def _resolve_workspace_path(self, path: str) -> Path:
        if not path:
            raise ToolError("path is required")
        target = (self.workspace_dir / path).resolve()
        try:
            target.relative_to(self.workspace_dir)
        except ValueError:
            raise ToolError("path outside backend/workspace")
        return target

    def _register_builtin_tools(self) -> None:
        self.register(
            ToolDefinition(
                name="read_file",
                description="Read a UTF-8 text file inside the workspace.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
                handler=self.read_file,
                permission=ToolPermission("workspace_path", path_arg="path"),
            )
        )
        self.register(
            ToolDefinition(
                name="write_file",
                description="Write a UTF-8 text file inside the workspace.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                    "required": ["path", "content"],
                    "additionalProperties": False,
                },
                handler=self.write_file,
                permission=ToolPermission("workspace_path", path_arg="path"),
            )
        )
        self.register(
            ToolDefinition(
                name="search",
                description="Search UTF-8 text files inside the workspace.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                    "additionalProperties": False,
                },
                handler=self.search,
                permission=ToolPermission("allow"),
            )
        )
        self.register(
            ToolDefinition(
                name="todo_write",
                description="Update the current run's todo list.",
                parameters={
                    "type": "object",
                    "properties": {
                        "todos": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "content": {"type": "string"},
                                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                                },
                                "required": ["content", "status"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    "required": ["todos"],
                    "additionalProperties": False,
                },
                handler=self.todo_write,
                permission=ToolPermission("allow"),
            )
        )
        self.register(
            ToolDefinition(
                name="load_skill",
                description="Load full instructions for a named skill.",
                parameters={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                handler=self.load_skill,
                permission=ToolPermission("allow"),
            )
        )
        self._register_durable_task_tools()
        self._register_background_task_tools()

    def _register_task_tool(self) -> None:
        self.register(
            ToolDefinition(
                name="task",
                description="Start an isolated synchronous subagent for a local task and return only its summary.",
                parameters={
                    "type": "object",
                    "properties": {"description": {"type": "string"}},
                    "required": ["description"],
                    "additionalProperties": False,
                },
                handler=self.task,
                permission=ToolPermission("allow"),
            )
        )

    def _register_durable_task_tools(self) -> None:
        status_schema = {"type": "string", "enum": ["pending", "in_progress", "blocked", "completed", "cancelled"]}
        self.register(
            ToolDefinition(
                name="task_create",
                description="Create a durable harness-managed task.",
                parameters={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "status": status_schema,
                        "blocked_by": {"type": "array", "items": {"type": "string"}},
                        "owner": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["title"],
                    "additionalProperties": False,
                },
                handler=self.task_create,
                permission=ToolPermission("allow"),
            )
        )
        self.register(
            ToolDefinition(
                name="task_list",
                description="List durable harness-managed tasks, optionally filtered by status.",
                parameters={"type": "object", "properties": {"status": status_schema}, "additionalProperties": False},
                handler=self.task_list,
                permission=ToolPermission("allow"),
            )
        )
        self.register(
            ToolDefinition(
                name="task_get",
                description="Get one durable harness-managed task by id.",
                parameters={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                    "additionalProperties": False,
                },
                handler=self.task_get,
                permission=ToolPermission("allow"),
            )
        )
        self.register(
            ToolDefinition(
                name="task_update",
                description="Update a durable harness-managed task.",
                parameters={
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "status": status_schema,
                        "blocked_by": {"type": "array", "items": {"type": "string"}},
                        "owner": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["id"],
                    "additionalProperties": False,
                },
                handler=self.task_update,
                permission=ToolPermission("allow"),
            )
        )

    def _register_background_task_tools(self) -> None:
        self.register(
            ToolDefinition(
                name="background_task_start",
                description="Start a background subagent job and return immediately with a background task id.",
                parameters={
                    "type": "object",
                    "properties": {"description": {"type": "string"}},
                    "required": ["description"],
                    "additionalProperties": False,
                },
                handler=self.background_task_start,
                permission=ToolPermission("allow"),
            )
        )
        self.register(
            ToolDefinition(
                name="background_task_list",
                description="List background jobs started in this run and their statuses.",
                parameters={"type": "object", "properties": {}, "additionalProperties": False},
                handler=self.background_task_list,
                permission=ToolPermission("allow"),
            )
        )
        self.register(
            ToolDefinition(
                name="background_task_get",
                description="Get one background job by id, including result when complete.",
                parameters={
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                    "additionalProperties": False,
                },
                handler=self.background_task_get,
                permission=ToolPermission("allow"),
            )
        )
