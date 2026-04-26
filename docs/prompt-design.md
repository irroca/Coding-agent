# System Prompt 设计

## 设计思路

System prompt 采用模块化装配，每个部分独立可调，便于迭代优化。通过 `agent/prompts.py` 的 `build_system_prompt()` 函数组装。

## 模块组成

### 1. Role — 角色定义

定义 Agent 的身份和核心行为准则：

- 终端编码助手，帮助软件工程任务
- 强调使用工具而非猜测文件内容
- 倾向精确编辑而非全文重写
- 调查问题时先收集证据再提出方案

### 2. Tool Usage Rules — 工具使用规则

指导模型正确选择工具：

- `read` 优先于 `bash cat`
- `edit` 优先于 `write`（已有文件）
- 先用 `glob`/`grep` 定位再编辑
- 不运行交互式命令
- 失败后调整策略而非重试相同调用

### 3. Code Style — 代码风格

约束生成代码的质量：

- 不多加注释（只在 why 不明显时加）
- 不过度抽象、不加未需求的功能
- 不加不可能触发的错误处理
- 注意安全漏洞

### 4. Communication — 沟通风格

控制 Agent 的回复方式：

- 简洁直接
- 操作前先说明意图（一句话）
- 关键时刻给简短更新
- 结束时一两句话总结
- 不叙述内部思考过程

### 5. Safety — 安全提示

强调破坏性操作的限制：

- 不执行 `rm -rf`、`git reset --hard` 等未经用户确认
- 不修改 workspace 外的文件
- 不自动 commit / push / 创建 PR
- 不暴露密钥和密码

### 6. Environment — 环境信息

动态注入运行时环境：

- 工作目录路径
- 平台（Linux/macOS/Windows）和版本
- Python 版本
- 当前时间（UTC）
- Provider 和模型名称

## 自定义指令

支持两级自定义指令文件，追加到 system prompt 末尾：

1. **用户级**：`~/.coding_agent/AGENTS.md` — 个人偏好，全局生效
2. **项目级**：`<workspace>/AGENTS.md` — 项目特定规则

加载顺序：用户级 → 项目级。两者都存在时均追加，项目级在后（优先级更高）。

## 调优记录

### 原则

- **简洁胜于冗长**：system prompt 占 token 预算，每一句都应有明确目的
- **行为导向**：告诉模型"做什么"而非"是什么"
- **具体胜于抽象**：`read 优先于 bash cat` 比 `选择合适的工具` 更有效

### 当前版本总 token 数

约 400-500 tokens（不含自定义指令），在 128K context window 中占比极低。

### 后续优化方向（M7+）

- 根据实际使用中模型的常见错误追加针对性规则
- 为不同 Provider/模型定制变体（如 DeepSeek 和 Claude 对工具调用的理解差异）
- 加入 todo/task 工具的使用指导
