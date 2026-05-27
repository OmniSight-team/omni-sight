FROM python:3.11-slim AS builder
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY libs/ ./libs/
COPY services/ai_worker_temporal/ ./services/ai_worker_temporal/
RUN uv sync --frozen --package ai-worker-temporal

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/services/ai_worker_temporal/src ./src
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "ai_worker_temporal"]
