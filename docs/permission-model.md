# 权限模型

## 设计目标

Agent 拥有读写文件和执行 Shell 命令的能力，必须有严格的权限控制防止误操作。设计参考 Claude Code 的三态决策模型：**allow**（自动放行）、**ask**（弹窗确认）、**deny**（直接拒绝）。

## 权限类型

每个工具调用通过 `permission_request()` 声明其权限类型：

| 权限类型 | 默认策略 | 典型工具 |
| --- | --- | --- |
| `file_read` | allow | read, ls, glob, grep |
| `file_write` | ask | write, edit |
| `bash` | ask | bash |
| `network` | ask | （预留） |

## 多层评估

权限引擎（`security/permissions.py`）按以下顺序评估，**首个匹配的规则决定结果**：

```
1. 内置 deny 规则（不可覆盖）
   ↓ 无匹配
2. 用户自定义规则（YAML 配置）
   ↓ 无匹配
3. 内置 allow 规则（便利放行）
   ↓ 无匹配
4. 命令守卫启发式（仅 bash）
   ↓ 无匹配
5. 配置默认值（file_read=allow, file_write=ask, ...）
```

### 第 1 层：内置 deny 规则

这些安全底线不可被用户规则覆盖：

- `rm -rf /` — 根目录递归删除
- `mkfs.*` — 格式化磁盘
- `dd if=... of=/dev/` — 磁盘原始写入
- fork bomb
- 写入 `.env` / `.env.*` 文件（防止泄露密钥）
- 写入 SSH 私钥 (`id_rsa*`) 和 PEM 证书

### 第 2 层：用户自定义规则

通过配置文件的 `rules` 列表或独立 YAML 文件定义：

```yaml
# .coding_agent/config.yaml
permissions:
  rules_file: .coding_agent/rules.yaml

# .coding_agent/rules.yaml
rules:
  - tool: bash
    match: "^npm\\s+(install|run|test)"
    decision: allow
  - tool: write
    path: "dist/**"
    decision: deny
  - tool: bash
    match: "^docker\\s+"
    decision: ask
```

规则字段：

- `tool` — 匹配工具名
- `action` — 匹配权限类型（file_read / file_write / bash / network）
- `match` — 正则表达式匹配命令内容（主要用于 bash）
- `path` — glob 模式匹配文件路径（用于 write/edit）
- `decision` — allow / ask / deny

### 第 3 层：内置 allow 规则

自动放行常见安全命令，减少确认疲劳：

- `git status/diff/log/show/branch`
- `ls/cat/head/tail/wc/find/which/echo/pwd/date`
- `python -m pytest/ruff/mypy`

### 第 4 层：命令守卫

`security/command_guard.py` 对 bash 命令进行结构化分析：

**解析**：用 `shlex` 分词，识别管道、重定向、子 shell、后台执行、命令链

**危险命令识别**（→ ask）：
- 可执行文件在危险列表中（rm, sudo, kill, curl, wget, chmod, ...）
- `git push/reset/clean/rebase` 或 `git --force`

**安全只读命令识别**（→ allow）：
- 可执行文件在安全列表中（ls, cat, git, python, rg, grep, ...）
- 无子 shell（`$(...)`）
- 无重定向
- git 子命令在安全集合内（status, diff, log, show, branch, tag, ...）

### 第 5 层：配置默认值

用户可在配置中覆盖默认策略：

```yaml
permissions:
  file_read: allow    # 默认值
  file_write: ask     # 默认值
  bash: allow         # 改为全部自动放行
  network: deny       # 改为全部拒绝
```

## 确认 UI

当决策为 `ask` 时，TUI 层弹出确认面板：

```
╭─ ⚠ bash requires approval ──╮
│ Run: npm install             │
╰──────────────────────────────╯
  [y] Allow  [n] Deny  [a] Allow all for this session
```

对于 write/edit 操作，如果工具实现了 `generate_diff()`，还会展示执行前的 diff 预览。

选择 `[a]` 会将该工具名加入会话级 auto-approve 集合，本次会话内不再询问。

## 审计日志

所有经过权限引擎评估的操作都记录到 `~/.local/share/coding_agent/audit.log`（JSONL 格式）：

```json
{"ts": 1714100000.0, "session": "s-abc123", "tool": "bash", "action": "bash", "summary": "Run: git status", "decision": "allow", "reason": "Matched built-in allow rule"}
```

记录字段：时间戳、会话 ID、工具名、权限类型、操作摘要、决策结果、原因。文件操作额外记录路径，bash 操作额外记录命令。

## 路径守卫

`security/path_guard.py` 是所有文件操作的第一道防线：

1. **Null byte 检查**：路径包含 `\x00` → 拒绝
2. **路径解析**：相对路径基于 workspace 解析为绝对路径
3. **Workspace 约束**：解析后路径必须在 workspace 目录内
4. **符号链接检查**：`resolve()` 会跟踪符号链接，确保最终目标在 workspace 内
5. **存在性检查**：`must_exist=True` 时确认文件/目录存在

路径守卫在工具层面生效（`resolve_and_validate` 调用），与权限引擎独立运作，两者同时保护。
