# ADR 0003 — 工具协议：Pydantic 模型 + __init_subclass__ 自注册

## Status
Accepted (2026-04-25)

## Context
Agent 需要一套工具系统，支持：
- 自动生成 JSON Schema 供 LLM 使用
- 参数校验与类型安全
- 工具发现无需手动维护列表
- 每个工具自带权限声明

候选方案：函数装饰器 / 基类继承 / 独立注册表。

## Decision
采用 **抽象基类 `Tool` + `__init_subclass__` 自动注册 + Pydantic `Params` 模型**。

每个工具是一个 `Tool` 子类，声明三个 ClassVar：
- `name`：工具名（唯一标识）
- `description`：自然语言描述
- `Params`：Pydantic BaseModel，定义参数 schema

导入工具模块即自动注册到全局 `_TOOL_REGISTRY`，无需手动 `register()` 调用。

## Consequences

**正向：**
- JSON Schema 由 Pydantic v2 的 `model_json_schema()` 自动生成，与 LLM 工具格式对齐
- 参数校验在工具执行前完成（`validate_params()`），错误消息清晰
- `permission_request()` 与 `run()` 在同一类中，权限声明不会与实现漂移
- 新增工具只需创建文件、继承 `Tool`、在 `__init__.py` 中 import 一行

**负向：**
- 每个工具一个文件 + 一个 Pydantic Model 略显模板代码多（对比装饰器方案）
- `__init_subclass__` 魔法对新手不太直观

## Alternatives considered
- **函数装饰器 `@tool(name, params_schema)`**：更轻量，但参数 schema 需手写 dict，容易与实际参数不同步
- **独立注册表 + `register(name, fn, schema)`**：灵活但容易忘记注册，工具与 schema 分离导致漂移
