#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${SCRIPT_DIR}/.runtime"
LOG_DIR="${SCRIPT_DIR}/logs"
BACKEND_PID_FILE="${RUNTIME_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUNTIME_DIR}/frontend.pid"

mkdir -p "${RUNTIME_DIR}" "${LOG_DIR}"

is_running() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

cleanup_pid_file() {
  local pid_file="${1}"
  if [[ -f "${pid_file}" ]]; then
    local pid
    pid="$(cat "${pid_file}" 2>/dev/null || true)"
    if ! is_running "${pid}"; then
      rm -f "${pid_file}"
    fi
  fi
}

start_background_service() {
  local name="${1}"
  local command_path="${2}"
  local pid_file="${3}"
  local log_file="${4}"
  local pid=""

  cleanup_pid_file "${pid_file}"

  if [[ -f "${pid_file}" ]]; then
    pid="$(cat "${pid_file}")"
    if is_running "${pid}"; then
      echo "[INFO] ${name} is already running (PID ${pid})."
      return 0
    fi
  fi

  echo "[INFO] Starting ${name}..."
  nohup bash "${command_path}" >"${log_file}" 2>&1 &
  pid=$!
  echo "${pid}" > "${pid_file}"

  sleep 3
  if is_running "${pid}"; then
    echo "[OK] ${name} started (PID ${pid})."
  else
    echo "[ERROR] ${name} failed to start. Last log lines:"
    tail -n 40 "${log_file}" 2>/dev/null || true
    exit 1
  fi
}

echo "========================================"
echo "Starting Fault AI full stack"
echo "Project root: ${SCRIPT_DIR}"
echo "========================================"

bash "${SCRIPT_DIR}/start_infra.sh"

start_background_service \
  "backend" \
  "${SCRIPT_DIR}/start_server.sh" \
  "${BACKEND_PID_FILE}" \
  "${LOG_DIR}/backend.log"

start_background_service \
  "frontend" \
  "${SCRIPT_DIR}/start_frontend.sh" \
  "${FRONTEND_PID_FILE}" \
  "${LOG_DIR}/frontend.log"

echo
echo "[OK] All services are up."
echo "Neo4j:   http://localhost:${NEO4J_HTTP_PORT:-7474}"
echo "Qdrant:  http://localhost:${QDRANT_HTTP_PORT:-6333}"
echo "Backend: http://localhost:${BACKEND_PORT:-8000}"
echo "Frontend:http://localhost:${FRONTEND_PORT:-5173}"
echo
echo "Logs:"
echo "  ${LOG_DIR}/backend.log"
echo "  ${LOG_DIR}/frontend.log"
echo
echo "Use ./stop_all.sh to stop backend, frontend, Neo4j and Qdrant."
