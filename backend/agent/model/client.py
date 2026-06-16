import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError


@dataclass(frozen=True)
class ModelConfig:
    api_key: str
    model: str
    base_url: str
    max_retries: int = 2
    timeout_seconds: float = 8.0
    mode: str = "api"


class ModelCallError(Exception):
    def __init__(self, category: str, message: str) -> None:
        self.category = category
        super().__init__(message)


class ModelClient:
    def __init__(self, config: ModelConfig, log: Callable[..., None]) -> None:
        self.config = config
        self.log = log
        self.client = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            max_retries=0,
            timeout=config.timeout_seconds,
        )

    def create_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        turn: int,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        if self.config.mode == "mock":
            self.log(
                "model_call_started",
                metadata={**(metadata or {}), "turn": turn, "attempt": 1, "model": "mock"},
            )
            return _mock_completion(messages)

        attempt = 1
        base_metadata = metadata or {}
        while True:
            self.log(
                "model_call_started",
                metadata={**base_metadata, "turn": turn, "attempt": attempt, "model": self.config.model},
            )
            try:
                return self.client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.2,
                )
            except Exception as exc:
                category = classify_model_error(exc)
                if not _should_retry(category, attempt, self.config.max_retries):
                    self.log(
                        "model_call_failed",
                        result="failure",
                        reason=str(exc),
                        metadata={**base_metadata, "turn": turn, "attempt": attempt, "category": category},
                    )
                    raise ModelCallError(category, str(exc)) from exc

                delay = min(2 ** (attempt - 1), 4)
                self.log(
                    "model_retry",
                    result="retry",
                    reason=str(exc),
                    metadata={
                        **base_metadata,
                        "turn": turn,
                        "attempt": attempt,
                        "category": category,
                        "next_delay_seconds": delay,
                    },
                )
                time.sleep(delay)
                attempt += 1


def classify_model_error(exc: Exception) -> str:
    if isinstance(exc, APITimeoutError):
        return "timeout"
    if isinstance(exc, APIConnectionError):
        return "connection"
    if isinstance(exc, RateLimitError):
        return "rate_limit"

    message = str(exc).lower()
    if "prompt" in message and ("too long" in message or "maximum context" in message):
        return "prompt_too_long"
    if "timeout" in message or "timed out" in message:
        return "timeout"
    if "connection" in message or "network" in message:
        return "connection"
    if "rate limit" in message or "429" in message:
        return "rate_limit"
    return "unknown"


def _should_retry(category: str, attempt: int, max_retries: int) -> bool:
    if attempt > max_retries:
        return False
    return category in {"timeout", "connection", "rate_limit"}


class _MockMessage:
    def __init__(self, content: str = "", tool_calls: list[Any] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self, exclude_none: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {"role": "assistant"}
        if self.content:
            data["content"] = self.content
        if self.tool_calls:
            data["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return data


def _mock_completion(messages: list[dict[str, Any]]) -> Any:
    has_tool_result = any(message.get("role") == "tool" for message in messages)
    if not has_tool_result:
        call = SimpleNamespace(
            id="mock-call-001",
            function=SimpleNamespace(name="read_file", arguments='{"path":"hello.txt"}'),
        )
        message = _MockMessage(tool_calls=[call])
    else:
        message = _MockMessage(
            content=(
                "Mock 模型已通过 read_file 读取 hello.txt。"
                "这次运行验证了 tool_use -> permission_check -> tool_result -> final answer 的完整 agent loop。"
            )
        )
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)

