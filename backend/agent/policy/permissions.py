from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolPermission:
    mode: str
    path_arg: str | None = None


@dataclass(frozen=True)
class PermissionResult:
    result: str
    reason: str | None = None


class PermissionPolicy:
    def __init__(self, workspace_dir: Path) -> None:
        self.workspace_dir = workspace_dir.resolve()

    def check_tool(self, permission: ToolPermission, arguments: dict[str, Any]) -> PermissionResult:
        if permission.mode == "allow":
            return PermissionResult("allow")
        if permission.mode == "workspace_path":
            if permission.path_arg is None:
                return PermissionResult("deny", "workspace_path permission requires path_arg")
            return self._check_workspace_path(str(arguments.get(permission.path_arg, "")))
        if permission.mode == "deny":
            return PermissionResult("deny", "tool is denied by policy")
        if permission.mode == "ask":
            return PermissionResult("deny", "ask permission is not implemented yet")
        return PermissionResult("deny", f"unknown permission mode: {permission.mode}")

    def check_unknown_tool(self, tool_name: str) -> PermissionResult:
        if not tool_name:
            return PermissionResult("deny", "tool name is required")
        return PermissionResult("deny", f"unknown tool: {tool_name}")

    def _check_workspace_path(self, path: str) -> PermissionResult:
        if not path:
            return PermissionResult("deny", "path is required")

        target = (self.workspace_dir / path).resolve()
        try:
            target.relative_to(self.workspace_dir)
        except ValueError:
            return PermissionResult("deny", "path outside backend/workspace")

        return PermissionResult("allow")
