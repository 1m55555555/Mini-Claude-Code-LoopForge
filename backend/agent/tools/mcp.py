from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agent.errors import ToolError
from agent.policy.permissions import ToolPermission
from agent.tools.registry import ToolDefinition, ToolResult


@dataclass(frozen=True)
class MCPToolSpec:
    server: str
    name: str
    description: str
    parameters: dict[str, Any]
    read_only: bool = True
    destructive: bool = False

    @property
    def registry_name(self) -> str:
        return f"mcp__{self.server}__{self.name}"

    @property
    def permission(self) -> ToolPermission:
        if self.destructive:
            return ToolPermission("deny")
        return ToolPermission("allow" if self.read_only else "ask")


class MockMCPServer:
    def __init__(self, name: str, tools: list[MCPToolSpec]) -> None:
        self.name = name
        self._tools = tools

    def list_tools(self) -> list[MCPToolSpec]:
        return list(self._tools)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if self.name == "runtime" and tool_name == "echo":
            return json.dumps({"echo": arguments}, ensure_ascii=False)
        if self.name == "runtime" and tool_name == "inspect_context":
            return json.dumps(
                {
                    "available": True,
                    "note": "mock MCP context inspector",
                    "arguments": arguments,
                },
                ensure_ascii=False,
            )
        raise ToolError(f"unknown MCP tool: {self.name}/{tool_name}")


class MCPClient:
    def __init__(self, servers: list[MockMCPServer]) -> None:
        self.servers = {server.name: server for server in servers}

    @classmethod
    def default_mock(cls) -> "MCPClient":
        return cls(
            [
                MockMCPServer(
                    "runtime",
                    [
                        MCPToolSpec(
                            server="runtime",
                            name="echo",
                            description="Mock MCP tool that echoes arguments for protocol verification.",
                            parameters={
                                "type": "object",
                                "properties": {"message": {"type": "string"}},
                                "required": ["message"],
                                "additionalProperties": False,
                            },
                            read_only=True,
                        ),
                        MCPToolSpec(
                            server="runtime",
                            name="inspect_context",
                            description="Mock MCP tool that returns a small context inspection payload.",
                            parameters={
                                "type": "object",
                                "properties": {"topic": {"type": "string"}},
                                "additionalProperties": False,
                            },
                            read_only=True,
                        ),
                    ],
                )
            ]
        )

    def tool_definitions(self, log: Any | None = None) -> list[ToolDefinition]:
        definitions: list[ToolDefinition] = []
        for server in self.servers.values():
            for spec in server.list_tools():
                if log is not None:
                    log(
                        "mcp_tool_discovered",
                        tool=spec.registry_name,
                        metadata={
                            "server": spec.server,
                            "name": spec.name,
                            "read_only": spec.read_only,
                            "destructive": spec.destructive,
                            "permission": spec.permission.mode,
                        },
                    )
                definitions.append(
                    ToolDefinition(
                        name=spec.registry_name,
                        description=f"[MCP:{spec.server}] {spec.description}",
                        parameters=spec.parameters,
                        handler=self._handler_for(spec),
                        permission=spec.permission,
                    )
                )
        return definitions

    def _handler_for(self, spec: MCPToolSpec) -> Any:
        def handler(arguments: dict[str, Any]) -> ToolResult:
            server = self.servers.get(spec.server)
            if server is None:
                raise ToolError(f"MCP server not found: {spec.server}")
            output = server.call_tool(spec.name, arguments)
            return ToolResult(output=output)

        return handler

