#!/bin/sh
set -eu

DB_PATH="${INSIGHTFLOW_DB_PATH:-/app/data/warehouse/insightflow.db}"
if [ ! -f "$DB_PATH" ]; then
  echo "Initializing InsightFlow demo warehouse at $DB_PATH"
  INSIGHTFLOW_READ_ONLY=false insightflow --db "$DB_PATH" bootstrap
fi

exec "$@"
