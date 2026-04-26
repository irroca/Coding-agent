# ADR 0002 — 主力 LLM 后端：DeepSeek + Provider 抽象

## Status
Accepted (2026-04-25)

## Context
需要选择一个国产模型作为默认后端（成本、可访问性），同时为后续切换其他模型预留扩展点。

## Decision
- **默认后端**：DeepSeek（`deepseek-chat`），通过 OpenAI 兼容协议调用
- **抽象层**：定义 `LLMProvider` 协议 + 统一的 `StreamEvent` 归一化层
- **首发支持**：DeepSeek、Qwen（DashScope OpenAI 模式）、Kimi（OpenAI 兼容）、OpenAI、Anthropic（预留）

## Consequences

**正向：**
- DeepSeek 成本极低、Tool Use 在国产模型里相对成熟、API 即 OpenAI 协议复用
- 抽象层让我们能在评测时对比不同后端
- 由于多数后端都走 OpenAI 协议，三家适配可共享一个 OpenAI-compatible 实现

**负向：**
- DeepSeek 的 Tool Use 与 OpenAI 行为有细微差异（如多工具并行时的 chunk 顺序），需在适配器内吸收
- Anthropic 协议差异较大，单独实现

## Alternatives considered
- **只接一家**：开发快但失去答辩亮点
- **OpenAI 主力**：成本高、国内访问受限
