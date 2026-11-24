# The job worker: places the calls for one test job, scores them and writes a
# results page. See WORKER.md.
#
# Build from the repository root after `uv run dvc pull` (or `dvc repro`), so
# that the caller's rendered lines and the noise files exist under data/:
#
#     docker build -t arena-worker --build-arg ARENA_VERSION=$(git rev-parse --short HEAD) .

FROM python:3.12-slim

# ffmpeg compresses the failure recordings; libsndfile reads and writes audio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy HF_HOME=/opt/models

# Dependencies first, so editing the code does not reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra worker --no-install-project

# The speech recogniser that reads the agent's replies is stored in the image,
# so a job never waits for a download.
ARG WHISPER_MODEL=large-v3-turbo
RUN uv run --no-sync python -c "from faster_whisper import download_model; download_model('${WHISPER_MODEL}')"

COPY src ./src
RUN uv sync --frozen --no-dev --extra worker

COPY params.yaml ./
COPY prompts ./prompts
COPY scenarios ./scenarios
# Rendered once on a machine with the speech model; the worker only plays them.
COPY data/caller_audio ./data/caller_audio
COPY data/noise ./data/noise

ARG ARENA_VERSION=unknown
# int8 is the fast setting for a machine without a GPU.
ENV ARENA_VERSION=${ARENA_VERSION} ARENA_COMPUTE_TYPE=int8 HF_HUB_OFFLINE=1 PYTHONUNBUFFERED=1

RUN useradd --create-home worker && mkdir /out && chown worker /out
USER worker

ENTRYPOINT ["uv", "run", "--no-sync", "arena", "job"]
CMD ["--out", "/out"]
