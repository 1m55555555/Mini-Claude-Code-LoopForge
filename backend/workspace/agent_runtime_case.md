# Mini Claude Code Runtime Case

This file is a clean test fixture for demonstrating the runtime.

## Mechanisms to verify

- The model should create and update a short todo plan.
- The model should read this file with `read_file`.
- The model should search the workspace for `tool_result`.
- The model may call an MCP mock tool such as `mcp__runtime__inspect_context`.
- The model may create a durable task and mark it completed.
- The model may start a background task for a small isolated summary.

## Expected final answer

The final answer should not only summarize file content. It should explain which harness mechanisms were exercised:

- model decision turn
- tool_use
- permission_check
- tool_result
- todo update
- durable task lifecycle
- MCP tool routing
- optional background notification

## Safety

This fixture does not require shell commands or writes outside the workspace.
