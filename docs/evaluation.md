# 评测方法

## 概述

本项目的评测分为三个层次：单元测试、集成测试、端到端冒烟测试。

## 单元测试

覆盖所有核心模块的独立功能：

| 模块 | 测试文件 | 测试数 | 覆盖重点 |
|------|----------|--------|----------|
| 工具系统 | `test_tools_rw_ls.py` | 15 | read/write/ls 工具的正常与边界行为 |
| 工具系统 | `test_tools_edit_glob_grep_bash.py` | 22 | edit/glob/grep/bash 工具 |
| 工具系统 | `test_tools_todo_task.py` | 多个 | todo_write 状态管理、`task` 子 Agent 派发（只读工具集 + 单层递归） |
| 工具系统 | `test_tools_base.py` | 若干 | 注册表、schema 生成、参数校验 |
| Grep 回退 | `test_grep_fallback.py` | 9 | 无 rg 时的纯 Python 搜索 |
| 编排器 | `test_orchestrator.py` | 15 | 权限检查、并行执行、错误隔离、审计 |
| 权限规则 | `test_rules.py` | 14 | 规则匹配、内置规则、YAML 加载 |
| 命令守卫 | `test_command_guard.py` | 17 | shlex 解析、危险/安全判定 |
| 权限引擎 | `test_permissions.py` | 11 | 五层评估优先级 |
| 审计日志 | `test_audit.py` | 4 | JSONL 写入、格式校验 |
| 路径守卫 | `test_path_guard.py` | 若干 | 路径穿越、符号链接、白名单 |
| Provider | `test_provider_openai_compat.py` | 若干 | SSE 解析、tool_call 装配、错误码 |
| Provider | `test_provider_anthropic.py` | 若干 | Anthropic 事件流解析 |
| Provider | `test_provider_registry.py` | 若干 | 配置驱动的工厂模式 |
| 上下文 | `test_context_compaction.py` | 14 | budget 阈值、分片、LLM 压缩、回退 |
| 会话 | `test_session.py` | 若干 | 消息添加、持久化、加载 |
| 配置 | `test_config.py` | 若干 | YAML 分层、环境变量、默认值 |
| Token | `test_tokens.py` | 若干 | tiktoken 计数 |
| 斜杠命令 | `test_slash_commands.py` | 10 | 命令分发、未知命令处理 |

## 集成测试

使用 MockProvider 模拟 LLM 响应，验证完整的 Agent 循环：

| 测试场景 | 文件 | 描述 |
|----------|------|------|
| 纯文本响应 | `test_agent_loop.py` | 模型不调用工具，直接返回文本 |
| 工具调用 + 后续回复 | `test_agent_loop.py` | write → 确认文件创建 → 模型总结 |
| 读取文件 | `test_agent_loop.py` | read 工具读取真实文件 |
| 未知工具 | `test_agent_loop.py` | 模型请求不存在的工具 → 错误隔离 |
| 迭代上限 | `test_agent_loop.py` | 模型持续调用工具 → max_iterations 停止 |
| 会话持久化 | `test_agent_loop.py` | 运行后 JSON 快照写入磁盘 |
| 权限确认回调 | `test_agent_loop.py` | confirm 回调拒绝 → 工具不执行 |
| 多工具链 | `test_agent_advanced.py` | read → edit → text 三步操作 |
| Bash 执行 | `test_agent_advanced.py` | 在 allow 权限下执行 shell 命令 |
| Glob + Grep | `test_agent_advanced.py` | 文件搜索工作流 |
| Provider 错误 | `test_agent_advanced.py` | 错误事件传播到上层 |
| TodoWrite | `test_agent_advanced.py` | 任务规划工具在 loop 中的集成 |
| 多段文本 | `test_agent_advanced.py` | 多个 TEXT_DELTA 事件正确传播 |

## 端到端冒烟测试（手动）

需要真实 API Key，适合本地验证和答辩演示：

1. **创建文件**：`请创建一个 hello.py，内容为 print("Hello, World!")`
2. **修改文件**：`把 hello.py 中的 Hello 改为 Hi`
3. **搜索代码**：`在 src/ 下找到所有定义了 async def 的文件`
4. **运行命令**：`运行 python hello.py 并告诉我输出`
5. **危险命令拦截**：`运行 rm -rf /` → 应被内置 deny 规则拦截
6. **多步任务**：`创建一个 Python 项目，包含 main.py 和 tests/test_main.py`
7. **上下文压缩**：长对话后 `/compact` 查看 token 用量

## 运行方式

```bash
# 单元测试 + 集成测试
uv run pytest tests/ -v

# 带覆盖率报告
uv run pytest tests/ --cov=coding_agent --cov-report=term-missing

# 仅集成测试
uv run pytest tests/integration/ -v

# 跳过需要 API Key 的测试
uv run pytest tests/ -v -m "not requires_api"
```

## 覆盖率目标

目标 ≥70%。当前共 **294** 个测试用例全部通过。CLI 层（`app.py`、`repl.py`、`render.py` 等）因涉及终端交互不纳入自动化测试覆盖率目标，其正确性通过手动冒烟测试验证。

## 自动化评测框架（M9）

### 框架简介

项目包含一套自动化评测框架（`src/coding_agent/evals/`），定义了 10 个代表性任务，覆盖 Agent 的核心能力维度。评测通过真实 API 调用运行 Agent，对结果进行断言式检查。

### 任务集

| ID | 名称 | 能力维度 | 断言数 |
| --- | --- | --- | --- |
| 01 | 创建 Python 文件 | 文件创建 | 3 |
| 02 | 修改已有文件 | 精准编辑（edit） | 3 |
| 03 | 创建项目结构 | 多文件创建 | 5 |
| 04 | 修复 Bug | 代码理解 + 修复 | 2 |
| 05 | 搜索代码并报告 | grep/glob 使用 | 2 |
| 06 | 跨文件重命名函数 | 多文件协调编辑 | 4 |
| 07 | 添加文档字符串 | 代码理解 + 选择性编辑 | 2 |
| 08 | 运行脚本并修复 | bash + 错误诊断 + 修复 | 2 |
| 09 | 生成 README | 项目理解 + 内容生成 | 3 |
| 10 | 实现一个类 | 代码生成（规格→实现） | 8 |

### 评测运行方式

```bash
# 列出所有任务
uv run python -m coding_agent.evals.cli --list

# 运行全部任务（需要 API Key 或本地代理）
DEEPSEEK_API_KEY=xxx uv run python -m coding_agent.evals.cli

# 运行单个任务
DEEPSEEK_API_KEY=xxx uv run python -m coding_agent.evals.cli --task 01-create-file

# 对接本地 OpenAI-兼容代理 + 导出 JSON 报告
uv run python -m coding_agent.evals.cli \
    --provider openai --base-url http://localhost:23333/api/openai/v1 \
    --api-key sk-local --model claude-haiku-4.5 \
    --report docs/eval-reports/run-$(date +%Y%m%d).json

# 对接 Anthropic 端点
uv run python -m coding_agent.evals.cli \
    --provider anthropic --base-url http://localhost:23333/api/anthropic/v1 \
    --api-key sk-local --model claude-haiku-4.5
```

### 输出指标（TaskMetrics）

每个任务记录：

- `iterations` — Agent 主循环轮次
- `tool_calls` + `tool_histogram` — 工具调用总数与各工具命中分布
- `usage.prompt_tokens` / `completion_tokens` / `cached_prompt_tokens` / `cache_creation_tokens`
- `usage.cache_hit_rate` — prompt cache 命中率（衡量 Anthropic `cache_control` 是否生效）
- `error_events` — provider/工具错误事件计数
- 任务级 `passed` + 每条 assertion 的 `ok` / `message`

`--report path.json` 会把所有任务的 metrics 序列化成单个 JSON 文件，便于跨次评测对比（参考 `docs/eval-reports/baseline-*.json` 与 `docs/eval-reports/final-*.json`）。

### 断言类型

- `file_exists`：文件存在
- `file_contains`：文件包含指定内容
- `file_not_contains`：文件不包含指定内容
- `file_equals`：文件内容精确匹配
- `command_output`：命令输出包含预期字符串

### 评测流程

1. 为每个任务创建临时工作目录
2. 执行 `setup_commands` 准备初始环境
3. 以任务 `prompt` 驱动 Agent 完整循环
4. 对工作目录状态逐条检查断言
5. 清理临时目录
6. 输出汇总报告（通过率 + 各任务结果 + 失败原因）
