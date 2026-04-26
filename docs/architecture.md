# 架构总览

> 此文档随实施进度持续更新。当前进度：M8 测试完善 + 文档 + ADR 完成。

## 设计目标

实现一个**生产级别**的终端 Coding Agent，达成"真实可用"水平：

1. **正确性**：工具调用稳定、上下文管理到位、不丢消息
2. **安全性**：多层权限系统，默认安全（write/bash 都需要确认）
3. **可扩展性**：Provider / Tool / Permission rule 都是可热插拔的
4. **可演示性**：流式 TUI，每一步都可视化
5. **可移植性**：纯 Python，跨 macOS / Linux / WSL

## 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│  TUI 层 (cli/)                                              │
│  REPL / 流式渲染 / 权限确认弹窗 / 斜杠命令                  │
├──────────────────────────────────────────────────────────────┤
│  Agent 核心 (agent/)                                         │
│  Agent loop / 工具调度 / 上下文压缩 / Todo 规划 / 子 Agent  │
├──────────────────────────────────────────────────────────────┤
│  Provider 层 (providers/)                                    │
│  LLMProvider 抽象 + DeepSeek/Qwen/Kimi/OpenAI/Anthropic 适配│
├──────────────────────────────────────────────────────────────┤
│  工具层 (tools/)                                             │
│  Tool 基类 + read/write/edit/glob/grep/bash/todo/task/...   │
├──────────────────────────────────────────────────────────────┤
│  权限与沙箱 (security/)                                      │
│  路径守卫 / 命令守卫 / 规则 DSL / 审计日志                  │
├──────────────────────────────────────────────────────────────┤
│  基础设施 (core/)                                            │
│  配置 / 日志 / 会话 / Token 计数 / 类型 / 错误               │
└──────────────────────────────────────────────────────────────┘
```

每层只依赖下面层；同层之间避免横向耦合。

## 数据流（一次用户输入的完整路径）

```
用户输入
   ↓
REPL → 加入 Session (User message)
   ↓
Agent.run()
   ↓
[loop start]
  ContextManager.maybe_compact()
  Provider.stream(messages, tools)  ─┐
                                     ├→ TUI 实时渲染 (TextDelta / ToolUseStart / ...)
  消费流 → 得到 (assistant_text, [ToolCall])
                                     │
  if not tool_calls: return          │
                                     │
  Orchestrator.execute(tool_calls):  │
    for each call:                   │
      PermissionEngine.check(call)   │
        ├─ allow → run               │
        ├─ ask → ConfirmUI → run/abort
        └─ deny → ToolResult(ok=False)
      Tool.run() → ToolResult        │
    回灌为 tool 消息                 │
[loop end → 下一轮]
   ↓
Session.save()
```

## 关键不变量

- **Session.messages 是唯一真相**：任何上下文修改（压缩、截断）都改这个列表，不维护"虚拟 view"
- **Provider 不感知工具实现**：它只看见 ToolSchema 和 ToolCall/ToolResult 的字符串化
- **Tool 不感知 Provider**：通过 ToolContext 拿到工作目录、权限引擎等环境
- **权限决策不在工具内部**：工具只声明它要做什么（PermissionRequest），引擎决定能不能做

## 目录结构

```
src/coding_agent/
├── __init__.py / __main__.py     # 入口
├── core/                         # 基础设施
│   ├── config.py                 # 多层配置加载（env + YAML + CLI）
│   ├── errors.py                 # 异常层级
│   ├── logging.py                # structlog 结构化日志
│   ├── session.py                # 会话持久化
│   ├── tokens.py                 # tiktoken token 计数
│   └── types.py                  # 领域模型（Message / ToolCall / StreamEvent 等）
├── providers/                    # LLM Provider 层
│   ├── base.py                   # LLMProvider ABC
│   ├── openai_compat.py          # OpenAI 兼容协议共享实现
│   ├── deepseek.py / qwen.py / moonshot.py / openai.py  # 四家 OpenAI 兼容
│   ├── anthropic.py              # Anthropic Messages API
│   └── registry.py               # Provider 工厂
├── agent/                        # Agent 核心
│   ├── loop.py                   # Agent 主循环（流式事件驱动）
│   ├── orchestrator.py           # 工具调度 + 权限集成
│   └── prompts.py                # System prompt 模块化装配
├── tools/                        # 工具层
│   ├── base.py                   # Tool ABC + 自动注册 + JSON Schema
│   ├── read.py / write.py / edit.py / ls.py  # 文件操作
│   ├── glob.py / grep.py         # 搜索
│   ├── bash.py                   # Shell 执行
│   ├── todo_write.py             # Todo 列表管理
│   └── task.py                   # 子 Agent 派发（占位）
├── security/                     # 权限与沙箱
│   ├── path_guard.py             # 路径校验（防穿越/符号链接/null byte）
│   ├── rules.py                  # allow/ask/deny 规则 DSL
│   ├── command_guard.py          # Bash 命令解析与危险性判定
│   ├── permissions.py            # 权限决策引擎（5 层评估）
│   └── audit.py                  # JSONL 审计日志
└── cli/                          # TUI 层
    ├── app.py                    # Typer CLI 入口
    ├── repl.py                   # REPL 主循环
    ├── render.py                 # Rich Live 流式渲染
    ├── prompt.py                 # prompt_toolkit 输入
    ├── confirm.py                # 权限确认 UI
    └── slash_commands.py         # /help /clear /cost /model /exit /history /sessions /permissions /tools
```

## 测试覆盖

当前共 **214** 个测试用例，全部通过，整体覆盖率 **≥78%**：

- `tests/unit/` — 涵盖配置、错误、会话、token 计数、Provider 流解析、工具基类、9 个工具（含 todo_write / task）、路径守卫、规则 DSL、命令守卫、权限引擎、审计日志、编排器（权限/并行/错误隔离）、grep 回退搜索、斜杠命令分发
- `tests/integration/` — 使用 MockProvider 跑完整 Agent 循环：文本回复 / 工具调用 / 未知工具 / 最大迭代 / 会话持久化 / 权限拒绝 / 多工具链（read→edit→text）/ bash 执行 / glob+grep 工作流 / Provider 错误传播 / TodoWrite 集成

所有测试不依赖真实 API Key，使用 `respx` mock HTTP 或自建 `MockProvider`。

## 进度

| 阶段 | 状态 | 内容 |
|------|------|------|
| M0 | ✅ | 项目骨架、配置、日志、错误、类型 |
| M1 | ✅ | Provider 抽象 + 5 家适配 + 流式事件归一化 |
| M2 | ✅ | 工具系统骨架 + read/write/ls + 路径守卫 |
| M3 | ✅ | Agent 主循环 + TUI + REPL + 流式渲染 |
| M4 | ✅ | 完整工具集：edit/glob/grep/bash |
| M5 | ✅ | 权限系统：规则 DSL + 命令守卫 + 权限引擎 + 审计日志 |
| M6 | ✅ | 上下文管理：budget 监控 + 摘要压缩 + 输出截断 |
| M7 | ✅ | 高阶能力：TodoWrite + Task 子 Agent + 斜杠命令完整 |
| M8 | ✅ | 测试完善（230 用例, 75% 覆盖率）+ 文档 + ADR |
| M9 | ✅ | 评测框架：10 个任务 + runner + CLI + 评测报告 |
