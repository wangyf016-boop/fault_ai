#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${SCRIPT_DIR}/.runtime"
BACKEND_PID_FILE="${RUNTIME_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUNTIME_DIR}/frontend.pid"

is_running() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

stop_pid_file() {
  local name="${1}"
  local pid_file="${2}"
  local pid=""

  if [[ ! -f "${pid_file}" ]]; then
    echo "[INFO] ${name} is not tracked."
    return 0
  fi

  pid="$(cat "${pid_file}" 2>/dev/null || true)"
  if ! is_running "${pid}"; then
    echo "[INFO] ${name} is already stopped."
    rm -f "${pid_file}"
    return 0
  fi

  echo "[INFO] Stopping ${name} (PID ${pid})..."
  kill "${pid}" 2>/dev/null || true

  for _ in {1..10}; do
    if ! is_running "${pid}"; then
      rm -f "${pid_file}"
      echo "[OK] ${name} stopped."
      return 0
    fi
    sleep 1
  done

  echo "[WARN] ${name} did not stop in time, forcing termination."
  kill -9 "${pid}" 2>/dev/null || true
  rm -f "${pid_file}"
}

echo "========================================"
echo "Stopping Fault AI full stack"
echo "========================================"

stop_pid_file "frontend" "${FRONTEND_PID_FILE}"
stop_pid_file "backend" "${BACKEND_PID_FILE}"

bash "${SCRIPT_DIR}/stop_infra.sh"

if [[ -d "${RUNTIME_DIR}" && -z "$(ls -A "${RUNTIME_DIR}" 2>/dev/null)" ]]; then
  rmdir "${RUNTIME_DIR}" 2>/dev/null || true
fi

echo "[OK] All services stopped."
