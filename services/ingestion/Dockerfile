FROM python:3.11-slim AS builder
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY libs/ ./libs/
COPY services/ingestion/ ./services/ingestion/
RUN uv sync --frozen --package ingestion

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/services/ingestion/src ./src
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "ingestion"]
