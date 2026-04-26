# ADR 0004 — 权限模型：五层评估 + 规则 DSL

## Status
Accepted (2026-04-26)

## Context
Coding Agent 执行文件读写、Shell 命令等操作。需要：
- 阻止高危操作（`rm -rf /`、写 `.env` 等）即使模型请求
- 允许常见安全操作（`git status`、`ls` 等）无需用户确认
- 用户可通过配置自定义规则
- 所有决策可审计

参考 Claude Code 的 allow / ask / deny 三态模型。

## Decision
采用 **五层评估引擎**，按优先级从高到低：

1. **内置 deny 规则**（不可覆盖）：`rm -rf /`、`mkfs`、fork bomb、写 `.env` / SSH 密钥等
2. **用户自定义规则**（YAML DSL）：`tool` + `action` + `match`（正则）/ `path`（glob）→ allow / ask / deny
3. **内置 allow 规则**：`git status/diff/log`、`ls`、`cat`、`python -m pytest` 等
4. **命令守卫启发式**（仅 bash）：shlex 解析后检查可执行文件黑白名单 + `--force` / 管道 / 重定向
5. **配置默认值**：`file_read=allow`, `file_write=ask`, `bash=ask`, `network=ask`

每层只负责"有明确意见"时返回决策，否则穿透到下一层。

## Consequences

**正向：**
- 内置 deny 层不可被用户配置覆盖，硬编码安全底线
- 常见安全命令自动放行，减少用户确认疲劳
- 用户规则优先级高于内置 allow，可收紧默认放行的操作
- 审计日志覆盖每一次权限检查，含决策理由

**负向：**
- 五层优先级对使用者有学习成本（"为什么我配了 deny 但 git status 还是通过了？"）
- 命令守卫基于 shlex，复杂 shell 语法（heredoc、进程替换）可能误判
- 规则数量多时首次匹配性能可能成为问题（当前规模远未触达）

## Alternatives considered
- **二层模型（deny + allow）**：过于简单，无法区分"自动放行"和"需要确认"
- **基于 Docker/seccomp 的沙箱**：安全性更强但部署复杂，课程场景下过度设计
- **每个工具硬编码权限逻辑**：灵活性差，无法用户自定义
