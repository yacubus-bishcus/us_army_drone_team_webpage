#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${SIGNAL_PHONE_NUMBER:-}" ]]; then
  echo "ERROR: SIGNAL_PHONE_NUMBER environment variable is required" >&2
  exit 1
fi

if [[ -z "${SIGNAL_GROUP_NAME:-}" ]]; then
  echo "ERROR: SIGNAL_GROUP_NAME environment variable is required" >&2
  exit 1
fi

LOG_FILE=${SIGNAL_LOG_FILE:-/app/static/logs/news_log.log}
SIGNAL_CLI_BIN=${SIGNAL_CLI_BIN:-signal-cli}
MAX_MINUTES=${SIGNAL_MAX_MINUTES:-}
TARGET_COUNT=${SIGNAL_TARGET_COUNT:-10}
ADDED_BY=${SIGNAL_ADDED_BY:-}

mkdir -p "$(dirname "${LOG_FILE}")"

ARGS=("--number" "${SIGNAL_PHONE_NUMBER}" "--group-name" "${SIGNAL_GROUP_NAME}" "--signal-cli" "${SIGNAL_CLI_BIN}" "--log-file" "${LOG_FILE}")

if [[ -n "${MAX_MINUTES}" ]]; then
  ARGS+=("--max-minutes" "${MAX_MINUTES}")
fi

if [[ -n "${TARGET_COUNT}" ]]; then
  ARGS+=("--target-count" "${TARGET_COUNT}")
fi

if [[ -n "${ADDED_BY}" ]]; then
  ARGS+=("--added-by" "${ADDED_BY}")
fi

if [[ "${SIGNAL_DRY_RUN:-}" == "1" ]]; then
  ARGS+=("--dry-run")
fi

exec python -m scripts.signal_service "${ARGS[@]}"
