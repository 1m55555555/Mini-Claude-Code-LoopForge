const form = document.querySelector("#runForm");
const taskInput = document.querySelector("#taskInput");
const runButton = document.querySelector("#runButton");
const sampleButton = document.querySelector("#sampleButton");
const demoButton = document.querySelector("#demoButton");
const statusBadge = document.querySelector("#statusBadge");
const answerBox = document.querySelector("#answerBox");
const runIdText = document.querySelector("#runIdText");
const chatTranscript = document.querySelector("#chatTranscript");
const timeline = document.querySelector("#timeline");
const eventCount = document.querySelector("#eventCount");
const viewButtons = document.querySelectorAll(".view-button");
const toolCount = document.querySelector("#toolCount");
const allowCount = document.querySelector("#allowCount");
const denyCount = document.querySelector("#denyCount");
const todoCount = document.querySelector("#todoCount");
const reminderCount = document.querySelector("#reminderCount");
const todoList = document.querySelector("#todoList");
const toolEvents = document.querySelector("#toolEvents");
const acceptanceScore = document.querySelector("#acceptanceScore");
const acceptanceList = document.querySelector("#acceptanceList");

const sampleTask = "请做一次 Mini Claude Code runtime 综合验收：1. 先用 todo_write 写一个 4 步计划；2. 用 read_file 读取 agent_runtime_case.md 和 hello.txt；3. 用 search 搜索 workspace 里的 tool_result；4. 调用 mcp__runtime__inspect_context 检查 topic=runtime-demo；5. 用 task_create 创建一个 durable task，再用 task_update 标记 completed；6. 如果合适，用 background_task_start 启动一个很小的后台总结任务；最后用中文总结本次运行触发了哪些机制，以及哪些事件应该在右侧 trace 里出现。";
let currentTask = "";
let currentEvents = [];
let currentView = "story";

for (const button of viewButtons) {
  button.addEventListener("click", () => {
    currentView = button.dataset.view;
    for (const item of viewButtons) {
      item.classList.toggle("active", item === button);
    }
    renderTimeline(currentEvents);
  });
}

sampleButton.addEventListener("click", () => {
  taskInput.value = sampleTask;
  taskInput.focus();
});

demoButton.addEventListener("click", () => {
  taskInput.value = sampleTask;
  form.requestSubmit();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const task = taskInput.value.trim();
  if (!task) return;

  currentTask = task;
  setRunning(true);
  renderEmptyState("运行中，正在连接模型...");
  renderChatPending(task);

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({task}),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "运行失败");
    }
    renderRun(data);
    setStatus("Success", "success");
  } catch (error) {
    answerBox.textContent = formatRunError(error);
    setStatus("Failed", "failed");
  } finally {
    setRunning(false);
  }
});

function setRunning(isRunning) {
  runButton.disabled = isRunning;
  sampleButton.disabled = isRunning;
  demoButton.disabled = isRunning;
  if (isRunning) setStatus("Running", "running");
}

function setStatus(text, mode) {
  statusBadge.textContent = text;
  statusBadge.dataset.mode = mode;
}

function formatRunError(error) {
  const message = error?.message || "运行失败";
  if (message.toLowerCase().includes("connection")) {
    return `${message}\n\n模型连接失败。请检查 DEEPSEEK_API_KEY、DEEPSEEK_BASE_URL 或当前网络。`;
  }
  return message;
}

function renderEmptyState(message) {
  answerBox.textContent = message;
  runIdText.textContent = "";
  timeline.replaceChildren();
  currentEvents = [];
  toolEvents.replaceChildren();
  todoList.replaceChildren();
  renderAcceptance([]);
  eventCount.textContent = "0 events";
  toolCount.textContent = "0";
  allowCount.textContent = "0";
  denyCount.textContent = "0";
  todoCount.textContent = "0";
  reminderCount.textContent = "0";
}

function renderRun(data) {
  answerBox.textContent = data.answer || "";
  runIdText.textContent = data.run_id;
  currentEvents = data.events || [];
  renderChatResult(currentTask, data.answer || "");
  renderTimeline(currentEvents);
  renderStats(currentEvents);
  renderAcceptance(currentEvents);
}

const acceptanceChecks = [
  {
    id: "loop",
    label: "Agent loop",
    detail: "模型至少完成一轮决策并成功结束",
    test: (events) => hasType(events, "model_call_started") && events.some((event) => event.type === "run_finished" && event.result === "success"),
  },
  {
    id: "todo",
    label: "Todo planning",
    detail: "使用 todo_write 维护计划状态",
    test: (events) => hasTool(events, "todo_write") && hasType(events, "todo_updated"),
  },
  {
    id: "read",
    label: "File context",
    detail: "读取 agent_runtime_case.md 与 hello.txt",
    test: (events) => hasToolInput(events, "read_file", "agent_runtime_case.md") && hasToolInput(events, "read_file", "hello.txt"),
  },
  {
    id: "search",
    label: "Workspace search",
    detail: "搜索 workspace 中的 tool_result",
    test: (events) => hasTool(events, "search"),
  },
  {
    id: "permission",
    label: "Permission gate",
    detail: "工具调用经过权限校验",
    test: (events) => events.some((event) => event.type === "permission_check" && event.result === "allow"),
  },
  {
    id: "mcp",
    label: "MCP routing",
    detail: "调用 mcp__runtime__inspect_context",
    test: (events) => hasTool(events, "mcp__runtime__inspect_context") || events.some((event) => event.type.startsWith("mcp_tool_")),
  },
  {
    id: "task",
    label: "Durable task",
    detail: "创建并更新持久任务",
    test: (events) => hasTool(events, "task_create") && hasTool(events, "task_update"),
  },
  {
    id: "background",
    label: "Background task",
    detail: "启动后台任务或收到后台通知",
    test: (events) => hasTool(events, "background_task_start") || events.some((event) => event.type.startsWith("background_task_")),
  },
];

function renderAcceptance(events) {
  const results = acceptanceChecks.map((check) => ({...check, passed: check.test(events)}));
  const passedCount = results.filter((item) => item.passed).length;
  acceptanceScore.textContent = `${passedCount}/${results.length}`;
  acceptanceScore.dataset.mode = passedCount === results.length ? "pass" : passedCount > 0 ? "partial" : "empty";

  acceptanceList.replaceChildren();
  for (const item of results) {
    const li = document.createElement("li");
    li.className = item.passed ? "acceptance-pass" : "acceptance-miss";

    const marker = document.createElement("span");
    marker.className = "acceptance-marker";
    marker.textContent = item.passed ? "✓" : "·";

    const body = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = item.label;
    const detail = document.createElement("small");
    detail.textContent = item.detail;
    body.append(title, detail);

    li.append(marker, body);
    acceptanceList.append(li);
  }
}

function hasType(events, type) {
  return events.some((event) => event.type === type);
}

function hasTool(events, tool) {
  return events.some((event) => event.tool === tool);
}

function hasToolInput(events, tool, value) {
  return events.some((event) => event.type === "tool_use" && event.tool === tool && JSON.stringify(event.input || {}).includes(value));
}

function renderChatPending(task) {
  chatTranscript.replaceChildren(
    createMessage("user", "U", task),
    createMessage("assistant", "A", "正在运行 agent loop，右侧会展示本次运行的结构化轨迹。"),
  );
}

function renderChatResult(task, answer) {
  chatTranscript.replaceChildren(
    createMessage("user", "U", task),
    createMessage("assistant", "A", answer || "没有最终回答。"),
  );
}

function createMessage(role, avatarText, content) {
  const article = document.createElement("article");
  article.className = `message ${role}-message`;

  const avatar = document.createElement("div");
  avatar.className = "avatar";
  avatar.textContent = avatarText;

  const body = document.createElement("div");
  body.className = "message-body";
  const p = document.createElement("p");
  p.textContent = content;
  body.append(p);

  article.append(avatar, body);
  return article;
}

function renderTimeline(events) {
  timeline.replaceChildren();
  eventCount.textContent = `${events.length} events`;

  for (const event of events) {
    if (currentView === "story" && !shouldShowStoryEvent(event)) continue;

    const item = document.createElement("li");
    item.className = `event event-${event.type} event-${eventMechanism(event)}`;

    const title = document.createElement("div");
    title.className = "event-title";

    const titleLeft = document.createElement("div");
    titleLeft.className = "event-title-left";

    const mechanism = document.createElement("span");
    mechanism.className = "event-mechanism";
    mechanism.textContent = currentView === "story" ? "story" : eventMechanism(event);

    const name = document.createElement("span");
    name.textContent = currentView === "story" ? storyTitle(event) : eventTitle(event);

    const time = document.createElement("time");
    time.textContent = formatTime(event.timestamp);

    const meta = document.createElement("div");
    meta.className = "event-meta";
    meta.append(...timelineDetails(event));

    titleLeft.append(mechanism, name);
    title.append(titleLeft, time);
    item.append(title, meta);
    timeline.append(item);
  }
}

function timelineDetails(event) {
  if (currentView === "story") return [detailText(storyText(event))];
  if (currentView === "raw") return [detailText(truncate(JSON.stringify(compactEvent(event)), 260))];
  return eventDetails(event);
}

function shouldShowStoryEvent(event) {
  return [
    "run_started",
    "prompt_built",
    "model_call_started",
    "model_retry",
    "model_call_failed",
    "context_compacted",
    "background_task_started",
    "background_task_finished",
    "background_task_notification",
    "mcp_tool_discovered",
    "mcp_tool_called",
    "subagent_started",
    "subagent_finished",
    "tool_use",
    "permission_check",
    "tool_result",
    "task_created",
    "task_updated",
    "task_completed",
    "skill_loaded",
    "todo_updated",
    "todo_reminder",
    "final",
    "run_finished",
  ].includes(event.type);
}

function storyTitle(event) {
  const titles = {
    run_started: "Agent 开始处理任务",
    prompt_built: "Harness 组装提示词",
    model_call_started: "模型开始决策",
    model_retry: "模型调用重试",
    model_call_failed: "模型调用失败",
    context_compacted: "上下文压缩",
    background_task_started: "后台任务启动",
    background_task_finished: "后台任务完成",
    background_task_notification: "后台通知注入",
    mcp_tool_discovered: "发现 MCP 工具",
    mcp_tool_called: "调用 MCP 工具",
    subagent_started: "启动子 Agent",
    subagent_finished: "子 Agent 返回",
    tool_use: "模型请求工具",
    permission_check: "权限检查",
    tool_result: "工具返回结果",
    task_created: "持久任务创建",
    task_updated: "持久任务更新",
    task_completed: "持久任务完成",
    skill_loaded: "技能加载",
    todo_updated: "计划更新",
    todo_reminder: "计划提醒",
    final: "最终回答",
    run_finished: "运行结束",
  };
  return titles[event.type] || event.type;
}

function storyText(event) {
  const metadata = event.metadata || {};
  if (event.type === "run_started") return `使用模型 ${metadata.model || "unknown"} 创建新运行。`;
  if (event.type === "prompt_built") return `当前暴露 ${metadata.tool_count || 0} 个工具，${metadata.skill_count || 0} 个技能。`;
  if (event.type === "model_call_started") return `第 ${metadata.turn || "?"} 轮模型决策开始。`;
  if (event.type === "model_retry") return `模型调用遇到 ${metadata.category || "unknown"}，harness 安排重试。`;
  if (event.type === "model_call_failed") return `模型调用失败：${event.reason || metadata.category || "unknown"}。`;
  if (event.type === "context_compacted") return `上下文从 ${metadata.before_messages || 0} 条压缩到 ${metadata.after_messages || 0} 条。`;
  if (event.type.startsWith("background_task_")) {
    const job = metadata.background_task || {};
    return `${job.id || "background task"} 状态：${job.status || event.result || "unknown"}。`;
  }
  if (event.type.startsWith("mcp_tool_")) return `${event.tool || "MCP tool"} 经过统一工具管线处理。`;
  if (event.type === "subagent_started") return `启动 ${metadata.subagent_id || "subagent"} 处理隔离任务。`;
  if (event.type === "subagent_finished") return `${metadata.subagent_id || "subagent"} 结束，状态 ${event.result || "unknown"}。`;
  if (event.type === "tool_use") return `模型请求调用 ${event.tool}。`;
  if (event.type === "permission_check") return `${event.tool} 权限检查结果：${event.result || "unknown"}。`;
  if (event.type === "tool_result") {
    if (metadata.truncated) return `${event.tool} 输出过大，模型收到 ${metadata.returned_chars || 0}/${metadata.full_chars || 0} chars。`;
    return `${event.tool} 返回 ${metadata.returned_chars || 0} chars。`;
  }
  if (event.type.startsWith("task_")) {
    const task = metadata.task || {};
    return `${task.id || "task"}：${task.title || ""}，状态 ${task.status || "unknown"}。`;
  }
  if (event.type === "skill_loaded") return `加载技能 ${metadata.name || "unknown"}。`;
  if (event.type === "todo_updated") {
    const counts = metadata.counts || {};
    return `pending ${counts.pending || 0}，in_progress ${counts.in_progress || 0}，completed ${counts.completed || 0}。`;
  }
  if (event.type === "todo_reminder") return `Harness 提醒模型维护计划。`;
  if (event.type === "final") return "模型生成最终回答。";
  if (event.type === "run_finished") return `运行结束，状态 ${event.result || "unknown"}。`;
  return "";
}

function compactEvent(event) {
  return {
    type: event.type,
    tool: event.tool,
    result: event.result,
    reason: event.reason,
    input: event.input,
    metadata: event.metadata,
  };
}

function renderStats(events) {
  const toolUseEvents = events.filter((event) => event.type === "tool_use");
  const permissionEvents = events.filter((event) => event.type === "permission_check");
  const reminderEvents = events.filter((event) => event.type === "todo_reminder");
  const latestTodoEvent = events.filter((event) => event.type === "todo_updated").at(-1);
  const todos = latestTodoEvent?.metadata?.todos || [];

  toolCount.textContent = String(toolUseEvents.length);
  allowCount.textContent = String(permissionEvents.filter((event) => event.result === "allow").length);
  denyCount.textContent = String(permissionEvents.filter((event) => event.result === "deny").length);
  todoCount.textContent = String(todos.length);
  reminderCount.textContent = String(reminderEvents.length);

  todoList.replaceChildren();
  for (const todo of todos) {
    const li = document.createElement("li");
    const status = document.createElement("span");
    status.className = `todo-status todo-${todo.status}`;
    status.textContent = todo.status;
    const content = document.createElement("span");
    content.textContent = todo.content;
    li.append(status, content);
    todoList.append(li);
  }

  toolEvents.replaceChildren();
  for (const event of events.filter((item) => item.tool)) {
    const li = document.createElement("li");
    li.textContent = `${event.type} · ${event.tool}${event.result ? ` · ${event.result}` : ""}`;
    toolEvents.append(li);
  }
}

function eventMechanism(event) {
  if (event.type === "prompt_built" || event.type === "skill_loaded") return "prompt";
  if (event.type === "context_compacted") return "context";
  if (event.type.startsWith("background_task_")) return "background";
  if (event.type.startsWith("mcp_tool_")) return "mcp";
  if (event.type === "assistant_message" || event.type.startsWith("model_")) return "model";
  if (event.type.startsWith("subagent_")) return "subagent";
  if (event.type === "tool_use" || event.type === "tool_result") return "tool";
  if (event.type === "permission_check") return "hook";
  if (event.type.startsWith("task_")) return "task";
  if (event.type.startsWith("todo_")) return "todo";
  if (event.type === "final" || event.type === "run_finished") return "stop";
  return "runtime";
}

function eventTitle(event) {
  if (event.tool) return `${event.type} · ${event.tool}`;
  if (event.type === "assistant_message") return `assistant_message${event.metadata?.turn ? ` · turn ${event.metadata.turn}` : ""}`;
  if (event.type === "model_call_started") return `model_call_started · turn ${event.metadata?.turn || ""} · attempt ${event.metadata?.attempt || ""}`;
  if (event.type.startsWith("background_task_")) return `${event.type} · ${event.metadata?.background_task?.id || ""}`;
  if (event.type.startsWith("task_")) return `${event.type} · ${event.metadata?.task?.id || ""}`;
  return event.type;
}

function eventDetails(event) {
  const details = [];
  if (event.result) details.push(detailPill("result", event.result));
  if (event.metadata?.hook) details.push(detailPill("hook", event.metadata.hook));
  if (event.metadata?.category) details.push(detailPill("category", event.metadata.category));

  if (event.type === "tool_use" && event.input) {
    details.push(detailText(`input ${truncate(JSON.stringify(event.input), 160)}`));
  } else if (event.type === "tool_result" && event.output) {
    if (event.metadata?.truncated) {
      details.push(detailPill("truncated", "true"));
      details.push(detailText(`${event.metadata.returned_chars || 0}/${event.metadata.full_chars || 0} chars returned · ${event.metadata.artifact_path || ""}`));
    }
    details.push(detailText(`output ${truncate(event.output, 180)}`));
  } else if (event.type.startsWith("task_")) {
    const task = event.metadata?.task || {};
    details.push(detailPill("status", task.status || "unknown"));
    details.push(detailText(`${task.id || ""} · ${task.title || ""}`));
  } else if (event.type.startsWith("background_task_")) {
    const job = event.metadata?.background_task || {};
    details.push(detailPill("status", job.status || event.result || "unknown"));
    details.push(detailText(`${job.id || ""} · ${job.description || ""}`));
  } else if (event.content) {
    details.push(detailText(truncate(event.content, 180)));
  } else if (event.reason) {
    details.push(detailText(truncate(event.reason, 180)));
  }

  if (details.length === 0) details.push(detailText(""));
  return details;
}

function detailPill(label, value) {
  const span = document.createElement("span");
  span.className = "detail-pill";
  span.textContent = `${label}: ${value}`;
  return span;
}

function detailText(value) {
  const span = document.createElement("span");
  span.className = "detail-text";
  span.textContent = value;
  return span;
}

function formatTime(timestamp) {
  return timestamp ? new Date(timestamp).toLocaleTimeString("zh-CN", {hour12: false}) : "";
}

function truncate(text, maxLength) {
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}
