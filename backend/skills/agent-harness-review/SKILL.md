---
name: agent-harness-review
description: 检查 Mini Claude Code 的 agent loop、工具、权限、hooks、todo 和 prompt assembly 是否保持清晰边界。
---

# Agent Harness Review

使用场景：

- 用户要求检查当前实现是否像 Claude Code 的 harness。
- 用户要求判断下一步机制是否应该进入 loop、tool、permission、hook、todo 或 prompt 层。
- 用户担心功能变成普通聊天 demo。

检查重点：

- `run_agent` 是否只保留稳定主流程。
- 工具是否通过 `ToolRegistry` 注册，而不是散落函数。
- 权限是否由 `PermissionHook` / `PermissionPolicy` 判断，而不是 prompt 约定。
- 扩展逻辑是否挂在 hook 上。
- todo 是否作为 harness 状态被记录和展示。
- prompt 是否由 runtime state 组装，而不是单个大字符串。

输出方式：

- 先指出最大设计风险。
- 再给出 1-3 个具体修改建议。
- 不要泛泛夸项目。
