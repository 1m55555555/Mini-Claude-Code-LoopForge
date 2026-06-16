from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"

sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

from main import app  # noqa: E402


def main() -> int:
    # 一键验证 Phase 2：真实模型读取 hello.txt，并检查工具事件链是否完整。
    task = "请调用工具读取 hello.txt，然后用两句话总结它验证了什么。"
    client = TestClient(app)
    response = client.post("/api/run", json={"task": task})

    print(f"HTTP status: {response.status_code}")
    data = response.json()

    if response.status_code != 200:
        print("Error detail:")
        print(data.get("detail", data))
        return 1

    print(f"Run ID: {data['run_id']}")
    print()
    print("Final answer:")
    print(data["answer"])
    print()
    print("Event chain:")
    print(f"{'type':<18} {'tool':<12} {'result':<10}")
    print("-" * 42)
    for event in data["events"]:
        print(
            f"{event.get('type', ''):<18} "
            f"{event.get('tool', '') or '':<12} "
            f"{event.get('result', '') or '':<10}"
        )

    expected = ["tool_use", "permission_check", "tool_result", "final", "run_finished"]
    event_types = [event["type"] for event in data["events"]]
    missing = [event_type for event_type in expected if event_type not in event_types]
    if missing:
        print()
        print(f"Missing expected events: {', '.join(missing)}")
        return 1

    print()
    print("Phase 2 verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
