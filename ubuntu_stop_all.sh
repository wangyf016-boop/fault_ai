#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ubuntu_common.sh"

echo "========================================"
echo "Stopping Fault AI full stack (Ubuntu)"
echo "========================================"

stop_by_pid_file "frontend" "${FRONTEND_PID_FILE}"
stop_by_pid_file "backend" "${BACKEND_PID_FILE}"
bash "${SCRIPT_DIR}/ubuntu_stop_ollama.sh"
bash "${SCRIPT_DIR}/ubuntu_stop_db.sh"

if [[ -d "${RUNTIME_DIR}" && -z "$(ls -A "${RUNTIME_DIR}" 2>/dev/null)" ]]; then
  rmdir "${RUNTIME_DIR}" 2>/dev/null || true
fi

echo
echo "[DONE] Full stack stopped."
