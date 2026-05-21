# Agent 主循环

## 概述

Agent 主循环（`agent/loop.py`）是整个系统的核心驱动器。它接收用户输入，反复调用 LLM 直到模型不再请求工具调用为止。整个过程是异步的、流式的、可中断的。

## 运行模型

```
用户输入 "修复 bug"
       ↓
session.add_user(input)
       ↓
┌─── while iterations < max_iterations ───┐
│                                          │
│  Provider.stream(messages, tools)        │
│    → 消费 StreamEvent 流                  │
│    → 产出 AgentEvent 给 TUI 实时渲染     │
│    → 收集 assistant_text + tool_calls    │
│                                          │
│  session.add_assistant(text, tool_calls) │
│                                          │
│  if no tool_calls → TURN_END, return     │
│                                          │
│  orchestrator.execute(tool_calls)        │
│    → 权限检查 → 并行/串行执行            │
│    → 产出 ToolResult                     │
│                                          │
│  session.add_tool_results(results)       │
│  session.save()                          │
│  → 继续下一轮                            │
└──────────────────────────────────────────┘
```

## 事件系统

主循环通过 `AsyncIterator[AgentEvent]` 向上层（TUI）传递实时事件：

| EventKind | 含义 | 携带数据 |
| --- | --- | --- |
| `TEXT_DELTA` | 模型输出的文本片段 | `text: str` |
| `TOOL_START` | 工具调用开始 | `tool_call: ToolCall` |
| `TOOL_RESULT` | 工具执行完成 | `tool_result: ToolResult` |
| `USAGE` | Token 用量统计 | `usage: Usage` |
| `TURN_END` | 本轮对话结束 | `finish_reason: str` |
| `ERROR` | 错误（不一定致命） | `error: str` |

TUI 的 `Renderer` 消费这些事件实现流式渲染——文本逐 token 显示，工具调用显示为折叠面板。

## Tool Call 增量装配

LLM 的工具调用参数通过多个 SSE chunk 分片到达。主循环维护两个缓冲区：

- `tool_names: dict[id, name]` — 记录每个工具调用的名称（`TOOL_USE_START` 时设置）
- `tool_arg_buffers: dict[id, list[str]]` — 累积参数 JSON 片段（`TOOL_USE_DELTA` 时追加）

当收到 `TOOL_USE_END` 时，拼接参数片段并 `json.loads` 解析，构建完整的 `ToolCall` 对象。解析失败时降级为空 dict，由工具自身的参数校验报错。

## 流式工具派发（streaming tool dispatch）

`AgentConfig.streaming_tool_dispatch`（默认 `True`，详见 [ADR-0007](decisions/0007-streaming-dispatch.md)）改变了"何时开始执行工具"的时机：

- **关闭时**（旧路径）：等 `DONE` 事件后，把这一轮的所有 `ToolCall` 交给 `execute_tool_calls()` 批量执行。
- **打开时**：**每收到一个 `TOOL_USE_END` 就立刻 `asyncio.create_task(execute_single_call(...))`**，工具与 LLM 流并发跑。流结束后再按模型给出的顺序 `await` 所有 task，组装回原顺序。

效果：当一轮里同时有较长文本和长耗时工具时，**整体延迟从 `T_text + T_tool` 降到 `max(T_text, T_tool)`**。集成测试 `tests/integration/test_streaming_dispatch.py` 用一个会在 `DONE` 前 sleep 0.3s 的 mock provider 断言 `elapsed < 1x sleep × 2.5`，证明实际并发。

异常路径：

- Ctrl+C / Provider 错误：在 `ERROR`/`except` 路径上 `task.cancel()` 所有未完成的 task，避免 work leak。
- 单个工具失败：被包装成 `ok=False` 的 `ToolResult` 喂回模型，不影响其他工具。
- 取消的 task：合成一条 `ToolResult(ok=False, content="Cancelled by user.")`，保证回传给模型的 `tool_results` 与 `tool_calls` 数量对齐（这是 OpenAI 协议的硬约束）。

## 工具执行流程

工具调用通过 `orchestrator.execute_tool_calls()` 分发：

1. 从注册表查找工具类
2. Pydantic 校验参数
3. 权限引擎评估（deny → 直接拒绝，ask → 弹出确认 UI，allow → 直接执行）
4. 调用 `tool.run(params, ctx)`
5. 审计日志记录
6. 错误隔离——单个工具失败不影响批次中其他工具

当 `parallel_tool_calls=True`（默认）且批次中有多个调用时，使用 `asyncio.gather` 并行执行。

## 安全边界

- **最大迭代次数**：`config.agent.max_iterations`（默认 50），防止模型无限循环调用工具
- **取消机制**：`Agent.cancel()` 设置 `asyncio.Event`，主循环在每次流式事件消费和每轮迭代开始时检查
- **错误隔离**：Provider 错误、工具错误均捕获并包装为 `AgentEvent.ERROR`，不崩溃主循环
- **会话持久化**：每轮工具执行后和最终结束时都调用 `session.save()`，防止中断丢失数据

## 消息格式

Session 中的消息遵循标准角色模型：

- `system` — 系统提示（首条消息，一次性设置）
- `user` — 用户输入
- `assistant` — 模型回复（可携带 `tool_calls`）
- `tool` — 工具执行结果（每个 `ToolResult` 一条）

这些消息由 Provider 层转换为各厂商的 wire format（OpenAI 的 `messages` 数组 / Anthropic 的 content blocks）。
