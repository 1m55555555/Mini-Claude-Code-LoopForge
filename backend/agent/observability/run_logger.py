import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.schemas import RunEvent


class RunLogger:
    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def create_run_id(self) -> str:
        now = datetime.now().astimezone()
        return f"run-{now:%Y%m%d-%H%M%S-%f}"

    def append(
        self,
        run_id: str,
        event_type: str,
        sequence: int,
        **payload: Any,
    ) -> RunEvent:
        event = RunEvent(
            id=f"evt-{sequence:04d}",
            run_id=run_id,
            type=event_type,
            timestamp=datetime.now().astimezone().isoformat(),
            **payload,
        )
        with self._path_for(run_id).open("a", encoding="utf-8") as file:
            file.write(event.model_dump_json(exclude_none=True))
            file.write("\n")
        return event

    def read_events(self, run_id: str) -> list[dict[str, Any]]:
        path = self._path_for(run_id)
        if not path.exists():
            raise FileNotFoundError(run_id)

        events: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    def _path_for(self, run_id: str) -> Path:
        if "/" in run_id or "\\" in run_id or ".." in run_id:
            raise FileNotFoundError(run_id)
        return self.runs_dir / f"{run_id}.jsonl"
