FROM python:3.11-slim AS builder
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY libs/ ./libs/
COPY services/query_service/ ./services/query_service/
RUN uv sync --frozen --package query-service

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/services/query_service/src ./src
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["python", "-m", "query_service"]
