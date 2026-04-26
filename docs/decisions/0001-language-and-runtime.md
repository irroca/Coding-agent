# ADR 0001 — 选择 Python 作为实现语言

## Status
Accepted (2026-04-25)

## Context
课程项目从零构建一个类 Claude Code 的终端 Coding Agent。候选语言：Python / TypeScript / Go。

## Decision
选择 **Python 3.11+**。

## Consequences

**正向：**
- LLM 生态最成熟（openai / anthropic SDK 均为一等公民）
- TUI 库（Rich + prompt_toolkit）足以达成业界 TUI 体验
- 课程上下文中 Python 调试与答辩演示更友好
- pydantic v2 + structlog 给我们一套快速搭建可信服务的工具链

**负向：**
- 异步并发工具调用比 Node.js 略显笨重（用 `asyncio.gather` 弥补）
- 单文件分发不便（用 `pip install -e .` + `coding-agent` 命令解决）

## Alternatives considered
- **TypeScript / Node.js**：与 Claude Code 原版同源，ink TUI 体验最佳；但课程语境下 Python 优势更大
- **Go**：单二进制分发优雅，但 LLM SDK 生态相对薄弱，TUI 库选择少
