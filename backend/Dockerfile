# AI Job Hunter — backend image (API + scheduler + Playwright collectors).
FROM python:3.12-slim

# uv for dependency management (copied from the official image).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 1) Install dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Install the Chromium browser + its OS dependencies for the collectors.
RUN playwright install --with-deps chromium

# 3) App code + migrations.
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

# Entrypoint runs `alembic upgrade head` then execs the command below.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "app.main", "serve-api", "--host", "0.0.0.0", "--port", "8000"]
