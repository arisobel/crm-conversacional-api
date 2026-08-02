#!/bin/sh
set -eu

if [ "${1:-}" = "uvicorn" ]; then
  if [ "${CRM_RUN_MIGRATIONS_ON_STARTUP:-true}" = "true" ]; then
    alembic upgrade head
  fi

  exec uvicorn crm_api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
fi

exec "$@"
