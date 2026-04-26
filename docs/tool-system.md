# 工具系统

## 设计原则

1. **自动注册**：工具类通过 `__init_subclass__` 自动注册到全局注册表，导入模块即完成注册
2. **Schema 自动生成**：参数定义使用 Pydantic v2 `BaseModel`，JSON Schema 自动派生，直接传给 LLM
3. **权限声明式**：每个工具通过 `permission_request()` 声明意图，权限决策由外部引擎完成
4. **错误隔离**：工具执行失败只影响当前调用，不影响 Agent 循环

## 基类设计

```python
class Tool(ABC):
    name: ClassVar[str]           # 工具名，LLM 看到的标识符
    description: ClassVar[str]    # 工具描述，帮助 LLM 判断何时使用
    Params: ClassVar[type[BaseModel]]  # Pydantic 参数模型

    @classmethod
    def schema(cls) -> ToolSchema:
        # 从 Params 自动生成 JSON Schema
        ...

    @abstractmethod
    async def run(self, params: BaseModel, ctx: ToolContext) -> ToolResult:
        ...

    def permission_request(self, params: BaseModel) -> PermissionRequest:
        # 声明本次调用需要的权限类型
        ...
```

`ToolContext` 为每次调用提供运行时环境：工作目录（`workspace`）和会话 ID。

## 当前工具清单

| 工具 | 权限类型 | 功能 |
| --- | --- | --- |
| `read` | file_read | 读取文件内容，支持行偏移和行数限制，检测二进制 |
| `write` | file_write | 写入文件，自动创建父目录，生成 unified diff |
| `edit` | file_write | 精准字符串替换，支持 `replace_all`，唯一性检查 |
| `ls` | file_read | 目录列表，支持深度限制，感知 .gitignore |
| `glob` | file_read | 文件名模式搜索（fnmatch），跳过隐藏目录 |
| `grep` | file_read | 内容搜索，优先用 ripgrep，退回内置正则 |
| `bash` | bash | Shell 命令执行，可配置超时（1-600s），输出截断 |

## 工具注册机制

```python
# tools/__init__.py — 导入即注册
from coding_agent.tools import bash, edit, glob, grep, ls, read, write
```

注册表提供三个查询函数：

- `get_tool(name)` — 按名称查找工具类
- `all_tools()` — 返回所有已注册工具的字典
- `all_schemas()` — 返回所有工具的 JSON Schema 列表，传给 LLM

## 路径安全

所有文件操作工具使用 `security/path_guard.py` 的 `resolve_and_validate()` 校验路径：

- 拦截 null byte 注入
- 将相对路径解析为绝对路径（基于 workspace）
- 检查解析后的路径是否在 workspace 内（防止 `../../../etc/passwd` 穿越）
- 检查符号链接目标是否在 workspace 内（防止链接逃逸）
- 可选检查文件是否存在

## edit 工具细节

`edit` 是最关键的代码修改工具，设计参考 Claude Code 的 Edit tool：

- `old_string` 必须在文件中精确存在
- 默认要求匹配唯一——出现多次时返回错误，提示用户提供更多上下文
- `replace_all=True` 可替换所有出现
- `old_string == new_string` 时直接报错（避免无效调用）
- 执行后返回 unified diff，方便 LLM 确认修改结果

## bash 工具安全

- 默认 120 秒超时，最大 600 秒
- 输出超过 30,000 字符时截断（保留首尾，中间标注截断）
- stdout 和 stderr 合并捕获
- 工作目录可指定（仍受路径守卫约束）
- 超时时强制 kill 子进程

## grep 工具双模式

- **ripgrep 模式**（优先）：调用系统 `rg` 命令，支持 `--glob` 过滤、`--max-filesize` 限制
- **内置模式**（退回）：`os.walk` + `re.compile`，跳过隐藏目录
- 两种模式统一返回 `path:lineno:content` 格式
- 结果上限 200 行
