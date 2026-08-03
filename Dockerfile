# syntax=docker/dockerfile:1.7

FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:${PATH}" \
    PORT=8016

WORKDIR /app

RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf \
        /root/.cache/pip \
        /usr/local/bin/pip \
        /usr/local/bin/pip3 \
        /usr/local/bin/pip3.12 \
        /usr/local/lib/python3.12/ensurepip \
        /usr/local/lib/python3.12/site-packages/jaraco* \
        /usr/local/lib/python3.12/site-packages/msgpack* \
        /usr/local/lib/python3.12/site-packages/pip* \
        /usr/local/lib/python3.12/site-packages/setuptools* \
        /usr/local/lib/python3.12/site-packages/wheel* \
        /var/lib/apt/lists/* \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app

# Official base images and wheels can contain embedded third-party SBOM files
# that describe superseded build-time packages. The CI pipeline generates and
# retains a fresh CycloneDX SBOM separately, so stale embedded documents are
# removed from the runtime filesystem before the blocking rootfs scan.
RUN find /usr/local /opt/venv -type f \( \
        -name '*.spdx' -o \
        -name '*.spdx.json' -o \
        -name '*.cdx' -o \
        -name '*.cdx.json' \
    \) -print -delete \
    && python - <<'PY'
from importlib.metadata import version

expected = {
    "jaraco.context": "6.1.0",
    "msgpack": "1.2.1",
    "setuptools": "83.0.0",
    "wheel": "0.46.2",
}
for package, expected_version in expected.items():
    actual = version(package)
    if actual != expected_version:
        raise SystemExit(f"{package}={actual}, expected {expected_version}")
print("Verified pinned runtime dependency versions")
PY

USER 10001:10001

EXPOSE 8016

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
    CMD curl -fsS http://127.0.0.1:${PORT}/health || exit 1

STOPSIGNAL SIGTERM

CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
