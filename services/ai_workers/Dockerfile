FROM python:3.13-slim

RUN pip install --no-cache-dir uv

WORKDIR /workspace

# The whole workspace is needed for uv to resolve members and their
# inter-dependencies (omnisight-ai-workers depends on omnisight-common), even
# though only these two are actually installed below. PyTorch comes from its
# CPU-only index (root pyproject.toml), so no CUDA libraries are installed.
COPY pyproject.toml uv.lock ./
COPY services ./services

RUN uv sync --frozen --package omnisight-ai-workers

# The checkpoint is not in the image: it is on the `models/pretrained` mount.
# No --reload: a reload would load the 4.5 GB model again on any file change.
CMD ["uv", "run", "--package", "omnisight-ai-workers", "uvicorn", "app.main:app", \
     "--app-dir", "services/ai_workers", "--host", "0.0.0.0", "--port", "8000"]
