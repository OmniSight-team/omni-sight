FROM python:3.13-slim

RUN pip install --no-cache-dir uv

# OMNI-308: ffmpeg's own CLI — the opencv-python-headless wheel only bundles
# the libraries it links against, not the ffmpeg/ffprobe binaries. Needed to
# detect a video's real codec and, when it isn't H.264 (CCD's clips are
# MPEG-4 Part 2 — OMNI-300), transcode a browser-playable copy for the player.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# The whole workspace is needed for uv to resolve members and their
# inter-dependencies (omnisight-ingestion depends on omnisight-common), even
# though only these two are actually installed below.
COPY pyproject.toml uv.lock ./
COPY services ./services

RUN uv sync --frozen --package omnisight-ingestion

EXPOSE 8000

CMD ["uv", "run", "--package", "omnisight-ingestion", "uvicorn", "app.main:app", \
     "--app-dir", "services/ingestion", "--host", "0.0.0.0", "--port", "8000", "--reload"]
