#!/bin/sh
# Build/upgrade the database schema, then run the given command (API + scheduler).
set -e

echo "[entrypoint] applying database migrations…"
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
