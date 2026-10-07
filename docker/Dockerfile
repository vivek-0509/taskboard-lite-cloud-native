# syntax=docker/dockerfile:1
#
# TaskBoard Lite - multi-stage, multi-arch image (works on arm64 and amd64).
#
# The build context is the project root (final-devops-project/):
#   docker build -f docker/Dockerfile -t taskboard-lite:local .
#
# To build an amd64 image on Apple Silicon (for the EC2 instance in terraform/):
#   docker buildx build --platform linux/amd64 -f docker/Dockerfile -t taskboard-lite:amd64 .

# ---- stage 1: builder -------------------------------------------------------
FROM python:3.12-alpine AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY application/requirements.txt ./requirements.txt
# Install every dependency into an isolated prefix that is copied to the final stage.
RUN pip install --prefix=/install -r requirements.txt

# ---- stage 2: runtime -------------------------------------------------------
# Alpine base: the Debian slim image carried 44 HIGH CVEs (util-linux) at scan time and failed the Trivy gate.
FROM python:3.12-alpine

LABEL org.opencontainers.image.title="taskboard-lite" \
      org.opencontainers.image.description="TaskBoard Lite - final DevOps project workload" \
      org.opencontainers.image.source="https://github.com/vivek-0509/devops_final_assignment"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    DATA_DIR=/app/data

# Bring in the pre-built site-packages and console scripts (gunicorn).
COPY --from=builder /install /usr/local

# Non-root user with a fixed UID so Kubernetes securityContext can reference it.
RUN addgroup -g 10001 -S app \
 && adduser -u 10001 -S -G app -h /app -s /sbin/nologin app \
 && mkdir -p /app/data \
 && chown -R app:app /app

WORKDIR /app
COPY --chown=app:app application/ /app/

USER app

EXPOSE 8000

# curl is not installed in the image, so the health check uses the standard library.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# one worker process + threads so the in-process Prometheus counters are consistent (multi-worker needs prometheus multiprocess mode)
CMD ["gunicorn", "-b", "0.0.0.0:8000", "-w", "1", "--threads", "4", "app:app"]
