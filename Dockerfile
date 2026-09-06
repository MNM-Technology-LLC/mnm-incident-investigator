# SPDX-License-Identifier: Apache-2.0
FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY investigator ./investigator
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
RUN groupadd --gid 10001 mnm && useradd --uid 10001 --gid mnm --create-home mnm \
    && mkdir -p /telemetry /evidence && chown mnm:mnm /telemetry /evidence
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY scripts ./scripts
COPY LICENSE NOTICE THIRD_PARTY_NOTICES.md ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 BIND_HOST=0.0.0.0
USER 10001:10001
CMD ["python", "-m", "mnm_investigator.console"]
