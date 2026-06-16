---
name: frontend-runtime-ui
description: 设计 Mini Claude Code 前端 runtime 面板，让用户看懂模型决策、hook、权限、工具结果和 todo 状态。
---

# Frontend Runtime UI

使用场景：

- 用户要求改进 Web 工作台。
- 用户要求让页面更能展示 Agent Harness。
- 用户要求可视化运行轨迹。

设计重点：

- 页面第一屏应该是可用工作台，不是营销页。
- 时间线要按机制分层：model、prompt、tool、hook、todo、stop。
- 右侧状态面板展示 harness state，而不是宣传说明。
- `permission_check.metadata.hook` 应直接显示。
- `todo_updated.metadata.todos` 应渲染成当前计划。
- `model_retry` / `model_call_failed` 应作为 runtime 状态展示。

避免：

- 不要写大段功能说明。
- 不要把事件原始 JSON 直接丢给用户。
- 不要做成普通聊天页面。
