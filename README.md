# Coding Agent

一个面向终端的、生产级别的 AI 编码助手，参考 [Claude Code](https://claude.ai/code) 的设计理念，完全用 Python 从零实现。

课程项目（《人工智能应用开发》）—— 目标是真实可用的工程级 Agent，而非演示玩具。

## 目录

- [特性](#特性)
- [环境要求](#环境要求)
- [安装](#安装)
- [配置 API Key](#配置-api-key)
- [启动与使用](#启动与使用)
- [浏览器 UI](#浏览器-ui)
- [斜杠命令](#斜杠命令)
- [内置工具](#内置工具)
- [配置系统](#配置系统)
- [权限与安全](#权限与安全)
- [支持的 Provider](#支持的-provider)
- [架构概览](#架构概览)
- [MCP 互通](#mcp-互通)
- [Docker 沙箱](#docker-沙箱)
- [插件系统](#插件系统)
- [开发与测试](#开发与测试)
- [评测](#评测)
- [项目文档](#项目文档)
- [许可](#许可)

## 特性

- **Agent Loop**：**流式工具派发**（`TOOL_USE_END` 触发，不等 stream 结束）、并行执行、可中断（Ctrl+C）、自动上下文压缩、会话持久化与恢复
- **多 Provider**：默认 DeepSeek，可一键切换 Qwen / Kimi / OpenAI / Anthropic
- **Prompt Cache**：Anthropic 用 `cache_control` 显式标记 system + tools；OpenAI/DeepSeek 自动 cache 命中率上报；`/cost` 实时显示
- **真实子 Agent**：`task` 工具派发独立 Agent 处理探索性子任务，**只读工具集 + 单层递归**，只把摘要回传父 Agent
- **9 个内置工具**：`read` / `write` / `edit` / `ls` / `glob` / `grep` / `bash` / `todo_write` / `task`
- **MCP 双向互通**：作为 client 接入外部 MCP server（filesystem/github/…），作为 server (`coding-agent-mcp`) 暴露内置工具给 Claude Code / Cursor
- **Bash 沙箱**：可选 `docker` 后端，`--network none` + CPU/内存限额，工作目录隔离
- **多层权限系统**：5 层评估引擎、路径守卫（防穿越 / 符号链接逃逸）、diff 预览、会话级 auto-approve
- **可追溯审计**：**SHA-256 hash chain** 防篡改 JSONL 审计日志；写入前自动 redact API key
- **插件系统**：基于 `entry_points` 加载第三方工具 / Provider / 斜杠命令，无需改核心
- **上下文管理**：自动 Token 预算监控、LLM 摘要压缩、工具输出截断
- **TUI**：Rich 流式 Markdown 渲染 + prompt_toolkit 多行输入 + 12 个斜杠命令（含 `/diff` `/undo`）
- **评测框架**：10 个自动化任务、JSON 报告、token/iteration/cache 多维指标，可针对任意 OpenAI-compat 或 Anthropic-compat 端点跑

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

# 按内容搜历史会话
uv run coding-agent sessions --grep "fix bug"

# 恢复之前的会话继续对话
uv run coding-agent chat --resume <session-id>

# 指定使用其他 Provider 启动
uv run coding-agent chat --provider qwen

# 把内置工具暴露为 MCP server，供 Claude Code / Cursor 调用
uv run coding-agent-mcp                              # stdio MCP server
uv run python -m coding_agent.mcp.server --list      # 打印工具 JSON schema
```

## 浏览器 UI

如果你更喜欢 ChatGPT / Claude 风格的图形界面（或者在 Windows / WSL 上想躲开终端），用浏览器 UI：

```bash
# 1) 安装时带上 web 这个 extra
uv sync --extra web                       # 仓库内开发
pip install 'coding-agent[web]'           # 已安装的 wheel

# 2) 启动
uv run coding-agent web                   # 默认 http://127.0.0.1:8765，自动打开浏览器
uv run coding-agent web --port 9000 --no-open-browser
uv run coding-agent web --workspace /path/to/project
```

**WSL 提示**：WSL2（Win10 19044+ / Win11）默认会把 `localhost` 转发到 Windows，所以在 Ubuntu 里跑 `coding-agent web`，直接在 Windows Chrome 打开 `http://localhost:8765` 即可，无需额外配置。如果某些老版本 WSL 没开转发，加上 `--host 0.0.0.0` 然后用 `$(hostname -I)` 拿到 IP 访问。

界面特性：

- **多会话侧栏**（按日期分组、可切换、可删除、新建对话）
- **Workspace 切换器**（顶栏下拉显示最近 workspace，支持手动输入任意绝对路径）
- **流式渲染**（文本逐字出现，工具调用以可折叠卡片实时显示运行状态）
- **权限弹窗**（modal + 行级 diff 高亮，"Allow / Deny / Always for this session" 三选项，与 TUI 同语义）
- **实时用量条**（顶部显示 provider:model、prompt/completion tokens、prompt cache 命中率）
- **自动重连**（WebSocket 断开后 1.5s 重连，重新发送 `session_state` 续传）

> v1 仅 localhost；**不要把端口暴露公网**。详见 [docs/web-ui.md](docs/web-ui.md) 和 [ADR-0011](docs/decisions/0011-web-ui.md)。

前端构建产物（`src/coding_agent/web/static/`）已随包提交，**安装时不需要 Node.js**。只有修改前端代码时才需要 `cd frontend && npm install && npm run build`。

## 斜杠命令

在 REPL 中输入以 `/` 开头的命令：

| 命令 | 功能 |
| --- | --- |
| `/help` | 显示所有可用命令 |
| `/clear` | 清空屏幕 |
| `/cost` | 显示当前会话 Token 用量与 **prompt cache 命中率** |
| `/model` | 显示当前 Provider 和模型信息 |
| `/compact` | 显示上下文利用率（压缩自动触发） |
| `/history` | 显示对话消息数按角色统计 |
| `/sessions` | 列出最近保存的会话 |
| `/permissions` | 显示当前权限配置 |
| `/tools` | 列出所有已注册工具（含 MCP 和插件） |
| `/diff` | 显示本会话累计修改的所有文件的 unified diff |
| `/undo` | 撤回上一次 `write` / `edit`（新建的文件则删除） |
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
| `bash` | 执行 Shell 命令（超时控制、输出截断、可选 docker 沙箱） | 需确认 |
| `todo_write` | 任务规划列表管理 | 自动允许 |
| `task` | **真实子 Agent 派发**：独立 session、只读工具集、单层递归 | 需确认 |

通过 MCP 客户端接入的外部工具会以 `mcp__<server>__<tool>` 形式注册，权限默认按 `bash` 处理。

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

### 审计与密钥防护

- **审计日志**：所有权限决策落盘到 `~/.local/share/coding_agent/audit.log`（JSONL），每行携带 SHA-256 `prev_hash` + `hash` 形成**哈希链**，单条被改即 `AuditLog.verify_chain()` 报错。
- **密钥扫描**：`security/secrets.py` 内置 7 类精准模式（OpenAI / Anthropic / GitHub / AWS / Google / Slack / 通用 hex），扫描时保留 4+2 字符窗口便于排查。所有 `summary` / `reason` / `command` 字段在写入审计日志前**先 redact 再哈希**，攻击者无法从审计日志反推密钥。
- **Pre-commit 钩子**：`scripts/secret_scan.py` 在 `.pre-commit-config.yaml` 中注册，提交含密钥的文件会被阻断。
- **路径守卫**：所有文件工具走 `path_guard.resolve_and_validate`，拦截路径穿越、符号链接逃逸、绝对路径注入、null byte。

## 支持的 Provider

| Provider | 环境变量 | 默认模型 | 协议 | Prompt Cache |
| --- | --- | --- | --- | --- |
| DeepSeek（默认） | `DEEPSEEK_API_KEY` | deepseek-chat | OpenAI 兼容 | ✓（自动） |
| Qwen | `DASHSCOPE_API_KEY` | qwen3-coder-plus | OpenAI 兼容 | – |
| Moonshot Kimi | `MOONSHOT_API_KEY` | kimi-k2-0905-preview | OpenAI 兼容 | – |
| OpenAI | `OPENAI_API_KEY` | gpt-4o-mini | OpenAI 原生 | ✓（自动，需 prompt > 1024 tokens） |
| Anthropic | `ANTHROPIC_API_KEY` | claude-sonnet-4-6 | Messages API | ✓（显式 `cache_control`） |

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
│  REPL / 流式渲染 / 权限确认弹窗 / 12 个斜杠命令              │
├──────────────────────────────────────────────────────────────┤
│  Agent 核心 (agent/)                                         │
│  Agent loop（流式工具派发）/ 编排 / 上下文压缩 / Todo / 子 Agent │
├──────────────────────────────────────────────────────────────┤
│  Provider 层 (providers/)                                    │
│  LLMProvider 抽象 + DeepSeek/Qwen/Kimi/OpenAI/Anthropic + Prompt Cache │
├──────────────────────────────────────────────────────────────┤
│  工具层 (tools/)                                             │
│  read/write/edit/ls/glob/grep/bash/todo_write/task           │
├──────────────────────────────────────────────────────────────┤
│  MCP 层 (mcp/)                                               │
│  Client：接入外部 MCP server  ·  Server：暴露内置工具         │
├──────────────────────────────────────────────────────────────┤
│  权限与沙箱 (security/)                                      │
│  5 层引擎 / 规则 DSL / 路径守卫 / 密钥扫描 / 审计哈希链        │
├──────────────────────────────────────────────────────────────┤
│  基础设施 (core/) + 插件 (plugins.py)                         │
│  配置 / 日志 / 会话 / Token 计数 / 类型 / entry_points 装载    │
└──────────────────────────────────────────────────────────────┘
```

## MCP 互通

基于 [Model Context Protocol](https://modelcontextprotocol.io)（官方 Python SDK）实现双向互通。

### 作为 Client：接入外部 MCP server

在 `~/.config/coding_agent/config.yaml` 中声明任意外部 server，REPL 启动时会通过 stdio 与之握手，发现的工具自动注册为 `mcp__<server>__<tool>`：

```yaml
mcp:
  servers:
    filesystem:
      command: npx
      args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    github:
      command: docker
      args: ["run", "-i", "--rm", "ghcr.io/github/github-mcp-server"]
      env:
        GITHUB_PERSONAL_ACCESS_TOKEN: "ghp_xxx"
```

外部工具默认按 `bash` 类权限处理，可用规则放行：`{tool: "mcp__filesystem__*", decision: allow}`。

### 作为 Server：把内置工具暴露给 Claude Code / Cursor

```bash
# 启动 stdio MCP server
uv run coding-agent-mcp

# 调试：打印所有工具的 JSON schema
uv run python -m coding_agent.mcp.server --list
```

在 Claude Code / Cursor 的 MCP 配置中引用即可。**权限引擎与审计日志仍然在 server 端生效**——通过 MCP 进来的调用并不绕过沙箱。

## Docker 沙箱

可选的 `bash` 后端，把每条命令放进一次性容器执行：

```yaml
# .coding_agent/config.yaml
agent:
  bash_driver: docker             # subprocess（默认）或 docker
  bash_docker_image: python:3.12-slim
```

容器以 `--rm --network none --cpus 2 --memory 1g --security-opt no-new-privileges` 启动，workspace 挂载到 `/workspace`。**拒绝**任何 `working_directory` 解析到 workspace 之外的请求；docker 二进制缺失时给出清晰报错并不破坏 subprocess 路径。

## 插件系统

第三方可通过 Python `entry_points` 注入工具、Provider、斜杠命令，**无需 fork 本仓库**。

在你的 `pyproject.toml` 中：

```toml
[project.entry-points."coding_agent.tools"]
my_tool = "my_pkg.tools:MyTool"

[project.entry-points."coding_agent.providers"]
my_provider = "my_pkg.providers:MyProvider"

[project.entry-points."coding_agent.slash_commands"]
my_cmd = "my_pkg.commands"
```

REPL 启动时 `plugins.load_plugins()` 会扫描这三个 group，单个插件出错不会拖垮主进程；调用 `load_plugins()` 多次是幂等的。

## 开发与测试

### 运行测试

```bash
# 运行全部 ~294 个测试（不依赖 API Key）
uv run pytest tests/ -q

# 带覆盖率报告
uv run pytest tests/ --cov=coding_agent --cov-report=term-missing

# 仅运行单元测试
uv run pytest tests/unit/ -v

# 仅运行集成测试（使用 MockProvider，无需 API Key）
uv run pytest tests/integration/ -v

# 跳过需要真实 API Key 的用例（默认行为）
uv run pytest -m "not requires_api"
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
│   │   ├── loop.py            # 主循环（含流式工具派发）
│   │   ├── orchestrator.py    # 工具调度
│   │   ├── compaction.py      # 上下文压缩
│   │   ├── context.py         # Token 预算管理
│   │   └── prompts.py         # System Prompt 装配（含 AGENTS.md 加载）
│   ├── cli/                   # TUI 层
│   ├── core/                  # 基础设施
│   ├── providers/             # LLM Provider 层
│   ├── mcp/                   # MCP client + server
│   │   ├── client.py          # 接入外部 MCP server
│   │   └── server.py          # 暴露内置工具为 MCP server
│   ├── security/              # 权限 / 路径守卫 / 命令守卫 / 审计 / 密钥扫描
│   │   ├── permissions.py
│   │   ├── rules.py
│   │   ├── command_guard.py
│   │   ├── path_guard.py
│   │   ├── audit.py           # 哈希链审计日志
│   │   └── secrets.py         # 7 类密钥精准模式
│   ├── tools/                 # 9 个内置工具
│   ├── plugins.py             # entry_points 插件装载
│   └── evals/                 # 评测框架
├── tests/
│   ├── unit/                  # 单元测试
│   └── integration/           # 集成测试（含子 Agent / 流式派发 / MCP / 压缩 E2E）
├── docs/                      # 设计文档 + ADR + 评测报告 + 迭代日志
├── scripts/                   # 辅助脚本（含 secret_scan.py pre-commit）
├── .github/workflows/         # CI（matrix）+ Release（PyPI/GHCR）
├── Dockerfile                 # python:3.12-slim 运行时镜像
├── .pre-commit-config.yaml
├── pyproject.toml
└── CHANGELOG.md
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
- [浏览器 UI](docs/web-ui.md) — Web 前端架构、协议、开发流程
- [迭代日志](docs/iteration-log.md) — 生产化迭代每个阶段的状态与决策（最新进度从这里看）
- 架构决策记录 (ADR)：
  - [ADR 0001 — 选择 Python](docs/decisions/0001-language-and-runtime.md)
  - [ADR 0002 — DeepSeek + Provider 抽象](docs/decisions/0002-llm-backend.md)
  - [ADR 0003 — 工具协议](docs/decisions/0003-tool-protocol.md)
  - [ADR 0004 — 权限模型](docs/decisions/0004-permission-model.md)
  - [ADR 0005 — 子 Agent 设计](docs/decisions/0005-subagent-design.md)
  - [ADR 0006 — Prompt cache 策略](docs/decisions/0006-prompt-cache.md)
  - [ADR 0007 — 流式工具派发](docs/decisions/0007-streaming-dispatch.md)
  - [ADR 0008 — MCP client + server](docs/decisions/0008-mcp.md)
  - [ADR 0009 — Bash 沙箱后端](docs/decisions/0009-bash-sandbox.md)
  - [ADR 0010 — 插件系统](docs/decisions/0010-plugins.md)
  - [ADR 0011 — 浏览器 UI](docs/decisions/0011-web-ui.md)

## 许可

MIT
