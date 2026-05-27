FROM python:3.11-slim AS builder
RUN pip install uv
WORKDIR /app

COPY pyproject.toml uv.lock ./

# All workspace member pyproject.toml stubs — uv needs them to resolve the workspace
COPY libs/omnisight_common/pyproject.toml       ./libs/omnisight_common/pyproject.toml
COPY libs/omnisight_messaging/pyproject.toml    ./libs/omnisight_messaging/pyproject.toml
COPY services/ingestion/pyproject.toml          ./services/ingestion/pyproject.toml
COPY services/ai_worker_frame/pyproject.toml    ./services/ai_worker_frame/pyproject.toml
COPY services/ai_worker_temporal/pyproject.toml ./services/ai_worker_temporal/pyproject.toml
COPY services/query_service/pyproject.toml      ./services/query_service/pyproject.toml
COPY services/pfm/pyproject.toml                ./services/pfm/pyproject.toml
COPY services/verification/pyproject.toml       ./services/verification/pyproject.toml
COPY services/rag_forensics/pyproject.toml      ./services/rag_forensics/pyproject.toml

# Source for this service and shared libs
COPY libs/ ./libs/
COPY services/rag_forensics/src ./services/rag_forensics/src

RUN uv sync --frozen --package rag-forensics

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/services/rag_forensics/src ./src
ENV PATH="/app/.venv/bin:$PATH"
CMD ["python", "-m", "rag_forensics"]
