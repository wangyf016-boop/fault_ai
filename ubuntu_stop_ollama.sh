#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ubuntu_common.sh"

stop_by_pid_file "ollama" "${OLLAMA_PID_FILE}"

if http_ok "${OLLAMA_HEALTH_URL}"; then
  echo "[WARN] Ollama is still reachable at ${OLLAMA_BASE_URL}."
  echo "[WARN] It may be managed by system service or started elsewhere."
  echo "To stop manually, run: pkill -f \"ollama serve\""
else
  echo "[OK] Ollama is not reachable."
fi
