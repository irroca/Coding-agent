# Coding Agent

一个面向终端的、生产级别的 AI 编码助手，参考 [Claude Code](https://claude.ai/code) 的设计理念，完全用 Python 从零实现。

课程项目（《人工智能应用开发》）—— 目标是真实可用的工程级 Agent，而非演示玩具。

## 目录

- [特性](#特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [配置 API Key](#配置-api-key)
- [启动与使用](#启动与使用)
- [斜杠命令](#斜杠命令)
- [内置工具](#内置工具)
- [配置系统](#配置系统)
- [权限与安全](#权限与安全)
- [支持的 Provider](#支持的-provider)
- [架构概览](#架构概览)
- [开发与测试](#开发与测试)
- [评测](#评测)
- [项目文档](#项目文档)
- [许可](#许可)

## 特性

- **Agent Loop**：流式工具调用、并行执行、可中断（Ctrl+C）、自动上下文压缩、会话持久化与恢复
- **多 Provider**：默认 DeepSeek，可一键切换 Qwen / Kimi / OpenAI / Anthropic
- **9 个内置工具**：`read` / `write` / `edit` / `ls` / `glob` / `grep` / `bash` / `todo_write` / `task`
- **多层权限系统**：5 层评估引擎、路径守卫（防穿越 / 符号链接逃逸）、diff 预览、会话级 auto-approve、JSONL 审计日志
- **上下文管理**：自动 Token 预算监控、LLM 摘要压缩、工具输出截断
- **TUI**：Rich 流式 Markdown 渲染 + prompt_toolkit 多行输入 + 10 个斜杠命令
- **评测框架**：10 个自动化评测任务，覆盖文件创建、代码修改、Bug 修复等场景

## 环境要求

| 依赖 | 要求 | 说明 |
| --- | --- | --- |
| Python | ≥ 3.11 | 推荐 3.11 或 3.12 |
| uv | 最新版 | Python 包管理器（推荐）；也可用 pip |
| ripgrep (rg) | 可选 | 提升 `grep` 工具搜索性能 |
| 操作系统 | Linux / macOS / WSL | 纯 Python，跨平台 |

## 安装

### 方式一：使用 uv（推荐）

```bash
# 1. 安装 uv（如未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 克隆项目
git clone <repo-url> coding-agent
cd coding-agent

# 3. 创建虚拟环境并安装依赖
uv sync --all-extras

# 4.（可选）安装 ripgrep 提升搜索性能
# Ubuntu / Debian / WSL:
sudo apt install ripgrep
# macOS:
brew install ripgrep
```

### 方式二：使用 pip

```bash
git clone <repo-url> coding-agent
cd coding-agent

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate   # Linux / macOS
# .venv\Scripts\activate    # Windows

# 安装项目（含开发依赖）
pip install -e ".[dev]"
```

## 配置 API Key

运行前必须配置至少一个 LLM Provider 的 API Key。

```bash
# 复制模板
cp .env.example .env

# 编辑 .env，填入你的 API Key
# 最简配置只需一行：
# DEEPSEEK_API_KEY=sk-your-key-here
```

`.env` 文件示例（默认使用 DeepSeek）：

```bash
DEEPSEEK_API_KEY=sk-your-deepseek-key-here
```

如果要使用其他 Provider：

```bash
# 使用 Qwen
DASHSCOPE_API_KEY=sk-your-dashscope-key
CODING_AGENT_PROVIDER=qwen

# 使用 Moonshot Kimi
MOONSHOT_API_KEY=sk-your-moonshot-key
CODING_AGENT_PROVIDER=moonshot

# 使用 OpenAI
OPENAI_API_KEY=sk-your-openai-key
CODING_AGENT_PROVIDER=openai

# 使用 Anthropic
ANTHROPIC_API_KEY=sk-your-anthropic-key
CODING_AGENT_PROVIDER=anthropic
```

## 启动与使用

### 启动交互式 REPL

```bash
# 使用 uv
uv run coding-agent

# 或使用 pip 安装后
coding-agent

# 也可以通过 python -m 启动
uv run python -m coding_agent
```

启动后你会看到如下界面：

```text
  Coding Agent v0.1.0  [deepseek:deepseek-chat]
  Workspace: /your/current/directory
  Type /help for commands. Ctrl+C to cancel. Ctrl+D to exit.

  >
```

### 使用示例

在 `>` 提示符后输入自然语言指令：

```text
  > 创建一个 hello.py，内容是打印 Hello World
  > 读取 src/main.py 并找到所有的 TODO 注释
  > 把 config.py 中的 MAX_RETRIES 从 3 改成 5
  > 运行 python -m pytest tests/ 并修复失败的测试
  > 在 src/ 下搜索所有使用了 deprecated_function 的地方
```

Agent 会自动调用工具（读文件、写文件、执行命令等），对于写操作和 Shell 命令，默认会弹出确认提示：

```text
  [ask] write → Write file: hello.py
  [y] Allow  [n] Deny  [a] Always allow this session
```

### 其他 CLI 命令

```bash
# 查看版本
uv run coding-agent --version

# 查看解析后的配置（API Key 已脱敏）
uv run coding-agent config-show

# 列出最近的会话
uv run coding-agent sessions

# 恢复之前的会话继续对话
uv run coding-agent chat --resume <session-id>

# 指定使用其他 Provider 启动
uv run coding-agent chat --provider qwen
```

## 斜杠命令

在 REPL 中输入以 `/` 开头的命令：

| 命令 | 功能 |
| --- | --- |
| `/help` | 显示所有可用命令 |
| `/clear` | 清空屏幕 |
| `/cost` | 显示当前会话 Token 用量 |
| `/model` | 显示当前 Provider 和模型信息 |
| `/compact` | 显示上下文利用率（压缩自动触发） |
| `/history` | 显示对话消息数按角色统计 |
| `/sessions` | 列出最近保存的会话 |
| `/permissions` | 显示当前权限配置 |
| `/tools` | 列出所有已注册工具 |
| `/exit` | 退出 Agent |

## 内置工具

Agent 可自动调用以下工具完成任务：

| 工具 | 功能 | 权限 |
| --- | --- | --- |
| `read` | 读取文件内容（支持行偏移、二进制检测） | 自动允许 |
| `write` | 写入文件（新建或覆盖，带 diff 预览） | 需确认 |
| `edit` | 精准字符串替换（支持 replace_all） | 需确认 |
| `ls` | 列出目录内容（支持 .gitignore 过滤） | 自动允许 |
| `glob` | 按文件名模式搜索（fnmatch） | 自动允许 |
| `grep` | 按内容搜索（优先 ripgrep，回退纯 Python） | 自动允许 |
| `bash` | 执行 Shell 命令（超时控制、输出截断） | 需确认 |
| `todo_write` | 任务规划列表管理 | 自动允许 |
| `task` | 子 Agent 派发（占位，待实现） | 需确认 |

## 配置系统

配置按优先级从低到高叠加，后者覆盖前者：

1. **内置默认值**（代码中）
2. **用户级配置** `~/.config/coding_agent/config.yaml`
3. **项目级配置** `<workspace>/.coding_agent/config.yaml`
4. **环境变量** / `.env` 文件
5. **CLI 命令行参数**

### 配置文件示例

```yaml
# <workspace>/.coding_agent/config.yaml
provider: deepseek

permissions:
  file_read: allow       # allow / ask / deny
  file_write: ask
  bash: ask
  rules_file: .coding_agent/rules.yaml   # 自定义规则文件路径

agent:
  max_iterations: 50           # 单次对话最大循环次数
  parallel_tool_calls: true    # 并行执行工具调用
  compact_threshold: 0.85      # 上下文占用超过此比例触发压缩
  keep_recent_turns: 6         # 压缩时保留最近 N 轮原文

ui:
  theme: dark
  show_token_usage: true
```

### 自定义权限规则

```yaml
# .coding_agent/rules.yaml
rules:
  - tool: bash
    match: "^npm\\s+(install|run|test)"
    decision: allow            # 自动放行 npm 常用命令

  - tool: bash
    match: "^docker\\s+rm"
    decision: deny             # 禁止删除容器

  - tool: write
    path: "dist/**"
    decision: deny             # 禁止写入构建产物目录

  - tool: write
    path: "*.md"
    decision: allow            # 自动放行 Markdown 文件编辑
```

## 权限与安全

系统采用 5 层权限评估引擎（按优先级从高到低）：

1. **内置 Deny 规则**（不可覆盖）：`rm -rf /`、`mkfs`、fork bomb、写 `.env` / SSH 密钥等
2. **用户自定义规则**：通过 YAML 配置 allow / ask / deny
3. **内置 Allow 规则**：`git status`、`ls`、`python -m pytest` 等安全命令
4. **命令守卫启发式**（仅 bash）：基于 shlex 解析判断危险性
5. **配置默认值**：`file_read=allow`, `file_write=ask`, `bash=ask`

所有权限决策记录到审计日志：`~/.local/share/coding_agent/audit.log`（JSONL 格式）。

## 支持的 Provider

| Provider | 环境变量 | 默认模型 | 协议 |
| --- | --- | --- | --- |
| DeepSeek（默认） | `DEEPSEEK_API_KEY` | deepseek-chat | OpenAI 兼容 |
| Qwen | `DASHSCOPE_API_KEY` | qwen3-coder-plus | OpenAI 兼容 |
| Moonshot Kimi | `MOONSHOT_API_KEY` | kimi-k2-0905-preview | OpenAI 兼容 |
| OpenAI | `OPENAI_API_KEY` | gpt-4o-mini | OpenAI 原生 |
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4-6 | Messages API |

切换方式：

```bash
# 环境变量
export CODING_AGENT_PROVIDER=qwen

# 或 .env 文件
CODING_AGENT_PROVIDER=qwen

# 或 CLI 参数
uv run coding-agent chat --provider qwen

# 或配置文件
# provider: qwen
```

## 架构概览

```text
┌──────────────────────────────────────────────────────────────┐
│  TUI 层 (cli/)                                              │
│  REPL / 流式渲染 / 权限确认弹窗 / 斜杠命令                  │
├──────────────────────────────────────────────────────────────┤
│  Agent 核心 (agent/)                                         │
│  Agent loop / 工具调度 / 上下文压缩 / Todo 规划 / 子 Agent  │
├──────────────────────────────────────────────────────────────┤
│  Provider 层 (providers/)                                    │
│  LLMProvider 抽象 + DeepSeek/Qwen/Kimi/OpenAI/Anthropic     │
├──────────────────────────────────────────────────────────────┤
│  工具层 (tools/)                                             │
│  read/write/edit/ls/glob/grep/bash/todo_write/task           │
├──────────────────────────────────────────────────────────────┤
│  权限与沙箱 (security/)                                      │
│  路径守卫 / 规则 DSL / 命令守卫 / 权限引擎 / 审计日志       │
├──────────────────────────────────────────────────────────────┤
│  基础设施 (core/)                                            │
│  配置 / 日志 / 会话 / Token 计数 / 类型 / 错误               │
└──────────────────────────────────────────────────────────────┘
```

## 开发与测试

### 运行测试

```bash
# 运行全部 230 个测试（不依赖 API Key）
uv run pytest tests/ -v

# 带覆盖率报告（当前 75%）
uv run pytest tests/ --cov=coding_agent --cov-report=term-missing

# 仅运行单元测试
uv run pytest tests/unit/ -v

# 仅运行集成测试（使用 MockProvider，无需 API Key）
uv run pytest tests/integration/ -v
```

### 代码质量检查

```bash
# Lint 检查
uv run ruff check src/ tests/

# 自动修复 lint 问题
uv run ruff check --fix src/ tests/

# 类型检查
uv run mypy src/
```

### 项目结构

```text
Coding_agent/
├── src/coding_agent/          # 源代码
│   ├── __init__.py
│   ├── __main__.py            # python -m coding_agent 入口
│   ├── agent/                 # Agent 核心
│   │   ├── loop.py            # 主循环
│   │   ├── orchestrator.py    # 工具调度
│   │   ├── compaction.py      # 上下文压缩
│   │   ├── context.py         # Token 预算管理
│   │   └── prompts.py         # System Prompt 装配
│   ├── cli/                   # TUI 层
│   │   ├── app.py             # Typer CLI 入口
│   │   ├── repl.py            # 交互式 REPL
│   │   ├── render.py          # Rich 流式渲染
│   │   ├── confirm.py         # 权限确认 UI
│   │   └── slash_commands.py  # 斜杠命令
│   ├── core/                  # 基础设施
│   │   ├── config.py          # 配置加载
│   │   ├── session.py         # 会话持久化
│   │   ├── tokens.py          # Token 计数
│   │   ├── types.py           # 领域模型
│   │   └── errors.py          # 异常层级
│   ├── providers/             # LLM Provider 层
│   │   ├── base.py            # 抽象接口
│   │   ├── openai_compat.py   # OpenAI 兼容协议实现
│   │   ├── anthropic.py       # Anthropic Messages API
│   │   ├── deepseek.py        # DeepSeek 适配
│   │   ├── qwen.py            # Qwen 适配
│   │   ├── moonshot.py        # Moonshot 适配
│   │   └── registry.py        # Provider 工厂
│   ├── security/              # 权限与沙箱
│   │   ├── permissions.py     # 5 层权限引擎
│   │   ├── rules.py           # 规则 DSL
│   │   ├── command_guard.py   # 命令解析
│   │   ├── path_guard.py      # 路径校验
│   │   └── audit.py           # 审计日志
│   ├── tools/                 # 工具实现
│   │   ├── base.py            # Tool ABC + 注册表
│   │   ├── read.py / write.py / edit.py / ls.py
│   │   ├── glob.py / grep.py / bash.py
│   │   ├── todo_write.py / task.py
│   │   └── __init__.py        # 自动注册
│   └── evals/                 # 评测框架
│       ├── task.py            # 任务定义
│       ├── runner.py          # 执行器
│       ├── cli.py             # 评测 CLI
│       └── tasks/*.json       # 10 个评测任务
├── tests/
│   ├── unit/                  # 单元测试（~200 个）
│   └── integration/           # 集成测试（~15 个）
├── docs/                      # 设计文档
├── scripts/                   # 辅助脚本
├── pyproject.toml             # 项目配置
├── .env.example               # API Key 模板
└── .python-version            # Python 3.11
```

## 评测

项目包含自动化评测框架，可验证 Agent 在真实场景下的任务完成能力。

```bash
# 列出所有评测任务
uv run python -m coding_agent.evals.cli --list

# 运行全部 10 个评测任务（需要 API Key）
DEEPSEEK_API_KEY=sk-xxx uv run python -m coding_agent.evals.cli

# 运行单个任务
DEEPSEEK_API_KEY=sk-xxx uv run python -m coding_agent.evals.cli --task 01-create-file

# 使用脚本运行
bash scripts/eval.sh --list
DEEPSEEK_API_KEY=sk-xxx bash scripts/eval.sh
```

评测任务覆盖 10 个场景：创建文件、修改文件、创建项目结构、修复 Bug、搜索代码、跨文件重命名、添加文档、运行修复、生成 README、实现类。

## 项目文档

- [架构总览](docs/architecture.md) — 分层架构、目录结构、进度
- [Agent 主循环](docs/agent-loop.md) — 事件驱动的 run loop 设计
- [工具系统](docs/tool-system.md) — Tool ABC、注册机制、JSON Schema
- [权限模型](docs/permission-model.md) — 5 层评估引擎、规则 DSL、审计
- [Provider 抽象层](docs/provider-abstraction.md) — 流式事件归一化、协议适配
- [System Prompt 设计](docs/prompt-design.md) — 模块化 prompt 装配
- [评测方法](docs/evaluation.md) — 测试策略、评测任务集
- 架构决策记录 (ADR)：
  - [ADR 0001 — 选择 Python](docs/decisions/0001-language-and-runtime.md)
  - [ADR 0002 — DeepSeek + Provider 抽象](docs/decisions/0002-llm-backend.md)
  - [ADR 0003 — 工具协议](docs/decisions/0003-tool-protocol.md)
  - [ADR 0004 — 权限模型](docs/decisions/0004-permission-model.md)

## 许可

MIT
