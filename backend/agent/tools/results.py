from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolResultConfig:
    max_inline_chars: int = 4000
    head_chars: int = 2200
    tail_chars: int = 1000


@dataclass(frozen=True)
class ManagedToolResult:
    original_output: str
    message_output: str
    metadata: dict[str, object]


class ToolResultManager:
    def __init__(self, *, runs_dir: Path, run_id: str, config: ToolResultConfig) -> None:
        self.runs_dir = runs_dir
        self.run_id = run_id
        self.config = config
        self.sequence = 0

    def manage(self, *, tool_name: str, output: str, status: str) -> ManagedToolResult:
        full_chars = len(output)
        if full_chars <= self.config.max_inline_chars:
            return ManagedToolResult(
                original_output=output,
                message_output=output,
                metadata={
                    "full_chars": full_chars,
                    "returned_chars": full_chars,
                    "truncated": False,
                },
            )

        self.sequence += 1
        artifact_path = self._write_artifact(tool_name, output)
        message_output = self._compact_output(output, artifact_path)
        return ManagedToolResult(
            original_output=output,
            message_output=message_output,
            metadata={
                "full_chars": full_chars,
                "returned_chars": len(message_output),
                "truncated": True,
                "artifact_path": artifact_path.as_posix(),
                "status": status,
            },
        )

    def _write_artifact(self, tool_name: str, output: str) -> Path:
        safe_tool_name = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in tool_name)[:50]
        relative = Path("artifacts") / self.run_id / f"tool-{self.sequence:03d}-{safe_tool_name}.txt"
        target = self.runs_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output, encoding="utf-8")
        return relative

    def _compact_output(self, output: str, artifact_path: Path) -> str:
        head = output[: self.config.head_chars]
        tail = output[-self.config.tail_chars :] if self.config.tail_chars > 0 else ""
        omitted = len(output) - len(head) - len(tail)
        return (
            "[tool_result truncated by harness]\n"
            f"full_chars: {len(output)}\n"
            f"artifact_path: {artifact_path.as_posix()}\n"
            f"omitted_chars: {max(omitted, 0)}\n\n"
            "[head]\n"
            f"{head}\n\n"
            "[tail]\n"
            f"{tail}"
        )

