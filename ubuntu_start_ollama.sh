#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ubuntu_common.sh"

if http_ok "${OLLAMA_HEALTH_URL}"; then
  echo "[INFO] Ollama already running: ${OLLAMA_BASE_URL}"
  exit 0
fi

require_command ollama

echo "========================================"
echo "Starting Ollama service"
echo "Ollama URL: ${OLLAMA_BASE_URL}"
echo "========================================"
echo

exec ollama serve
