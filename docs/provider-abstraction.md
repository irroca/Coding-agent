# Provider 抽象层

## 设计目标

让上层（Agent loop / Tool 系统 / TUI）完全不感知具体 LLM 厂商。换 DeepSeek 为 Qwen，应该只改一行配置（`provider: qwen`），所有上层代码不变。

## 接口

`coding_agent.providers.base.LLMProvider` 是唯一对外契约：

```python
class LLMProvider(ABC):
    name: str

    def stream(self, messages, tools, *, temperature=None, max_tokens=None
              ) -> AsyncIterator[StreamEvent]: ...
    def count_tokens(self, messages: list[Message]) -> int: ...

    @property
    def context_window(self) -> int: ...
    @property
    def max_output_tokens(self) -> int: ...
    @property
    def model(self) -> str: ...
```

## 流式事件契约

所有 Provider 都吐出 `coding_agent.core.types.StreamEvent`，按如下顺序约束：

1. **TEXT_DELTA**：文本片段，可多次出现
2. **TOOL_USE_START**：每个工具调用一次，带 `tool_call_id` 和 `tool_name`
3. **TOOL_USE_DELTA**：参数 JSON 片段，按到达顺序拼接
4. **TOOL_USE_END**：每个工具调用一次，标记参数完整
5. **USAGE**：token 用量，至少一次
6. **DONE**：终态，带 `finish_reason`（`stop` / `tool_calls` / `length` / 错误）
7. **ERROR**：失败，迭代器随后结束

文本与工具事件可任意交错；并行工具调用通过不同 `tool_call_id` 区分。

## 五家厂商，两种协议

| Provider      | 协议                          | 适配器           |
| ------------- | ----------------------------- | ---------------- |
| DeepSeek      | OpenAI Chat Completions       | `deepseek.py`    |
| Qwen3         | OpenAI 兼容（DashScope 模式） | `qwen.py`        |
| Moonshot Kimi | OpenAI 兼容                   | `moonshot.py`    |
| OpenAI        | OpenAI 原生                   | `openai.py`      |
| Anthropic     | Messages API（事件型 SSE）    | `anthropic.py`   |

前四家共用 `OpenAICompatProvider` 主体实现，差异仅是 `default_base_url` / `default_model`。Anthropic 协议结构差异较大，独立实现。

## OpenAI 兼容流的关键难点

**Tool call 增量按 index 索引而非 id**：vendor 只在第一个 chunk 发 `id` + `function.name`，后续只发 `function.arguments` 片段。我们用 `_ToolCallAccumulator` 维护 `index → (id, name, args_buffer)` 表，在 `id` + `name` 都集齐时才合成 `TOOL_USE_START` 事件。

**Empty deltas**：DeepSeek 在 turn 开始时常发若干空 delta；过滤掉，不上发空 `TEXT_DELTA`。

**Usage 时机**：开启 `stream_options={"include_usage": True}` 时，usage 在最后一个 `choices` 为空的 chunk 上。我们用 `usage_seen` 标记兜底（没收到时合成空 Usage）。

**重试策略**：429 / 连接超时按指数退避重试 3 次；4xx（除 429）和 5xx 不重试，直接报错。Auth 单独映射为 `ProviderAuthError`。

## Anthropic 流的关键难点

事件类型放在 SSE 的 `event:` 行，**不在 `data:` JSON 里**。需要跨 line 配对：先记 `pending_event`，下一个 `data:` 行附上这个类型。早期实现忘了这点导致整流被吞 —— 这是 M1 阶段实测踩到的最大坑，记录在此。

工具调用通过 `content_block_*` 事件流式装配，规则比 OpenAI 协议更清晰（每个 block 有明确的 start / delta / stop）。

## 测试

`tests/unit/test_provider_openai_compat.py`、`test_provider_anthropic.py`、`test_provider_registry.py` 共 27 个用例，覆盖：

- SSE 解析边界（DONE / 空行 / 注释行 / 损坏 JSON）
- 跨 chunk 的 tool_call 装配
- 并行 tool_calls
- 错误码映射（401 / 429 / 5xx）
- 重试行为（429 重试到极限）
- 配置驱动的 Provider 工厂

所有测试都用 `respx` mock httpx 流，不依赖真实 API key。
