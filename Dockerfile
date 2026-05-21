# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git is handy for the agent's bash tool to work with git repos.
# tini gives us proper signal handling so Ctrl+C inside a container exits cleanly.
RUN apt-get update \
 && apt-get install -y --no-install-recommends git tini \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy only the metadata first so the layer caches across source-only edits.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Install with the MCP extra so the bundled coding-agent-mcp script works
# inside the image. Docker users can pip install [docker] separately if they
# want the nested-container bash driver.
RUN pip install --no-cache-dir ".[mcp]"

# Non-root by default — production safety.
RUN useradd --create-home --uid 1000 agent
USER agent
WORKDIR /workspace

ENTRYPOINT ["tini", "--", "coding-agent"]
CMD ["chat"]
