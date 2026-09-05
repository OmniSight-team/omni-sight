FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /workspace

# The whole workspace is needed for uv to resolve members and their
# inter-dependencies (omnisight-query depends on omnisight-common), even
# though only these two are actually installed below.
COPY pyproject.toml uv.lock ./
COPY services ./services

RUN uv sync --frozen --package omnisight-query

EXPOSE 8000

CMD ["uv", "run", "--package", "omnisight-query", "uvicorn", "app.main:app", \
     "--app-dir", "services/query", "--host", "0.0.0.0", "--port", "8000", "--reload"]
