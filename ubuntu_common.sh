#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${PROJECT_DIR}/.runtime"
LOG_DIR="${PROJECT_DIR}/logs"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.ubuntu.yml"

BACKEND_PID_FILE="${RUNTIME_DIR}/backend.pid"
FRONTEND_PID_FILE="${RUNTIME_DIR}/frontend.pid"
OLLAMA_PID_FILE="${RUNTIME_DIR}/ollama.pid"

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
NEO4J_HTTP_PORT="${NEO4J_HTTP_PORT:-7474}"
QDRANT_HTTP_PORT="${QDRANT_HTTP_PORT:-6333}"
OLLAMA_BASE_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:${OLLAMA_PORT:-11434}}"
OLLAMA_HEALTH_URL="${OLLAMA_BASE_URL%/}/api/tags"

ensure_runtime_dirs() {
  mkdir -p "${RUNTIME_DIR}" "${LOG_DIR}"
}

require_command() {
  local cmd="${1}"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "[ERROR] Required command not found: ${cmd}"
    exit 1
  fi
}

is_pid_running() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

read_pid_file() {
  local pid_file="${1}"
  if [[ -f "${pid_file}" ]]; then
    tr -d '[:space:]' < "${pid_file}"
  fi
  return 0
}

cleanup_pid_file() {
  local pid_file="${1}"
  local pid=""
  pid="$(read_pid_file "${pid_file}")"

  if [[ -f "${pid_file}" && ! is_pid_running "${pid}" ]]; then
    rm -f "${pid_file}"
  fi
}

is_port_listening() {
  local port="${1}"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :${port}" | tail -n +2 | grep -q .
    return $?
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"${port}" -sTCP:LISTEN -t >/dev/null 2>&1
    return $?
  fi

  return 1
}

http_ok() {
  local url="${1}"
  if ! command -v curl >/dev/null 2>&1; then
    return 1
  fi
  curl -fsS --max-time 2 "${url}" >/dev/null 2>&1
}

wait_http_ok() {
  local url="${1}"
  local timeout_seconds="${2:-30}"
  local i=0

  while [[ "${i}" -lt "${timeout_seconds}" ]]; do
    if http_ok "${url}"; then
      return 0
    fi
    sleep 1
    i=$((i + 1))
  done

  return 1
}

run_compose() {
  require_command docker

  if [[ ! -f "${COMPOSE_FILE}" ]]; then
    echo "[ERROR] Compose file not found: ${COMPOSE_FILE}"
    exit 1
  fi

  if docker compose version >/dev/null 2>&1; then
    docker compose -f "${COMPOSE_FILE}" "$@"
    return 0
  fi

  if command -v docker-compose >/dev/null 2>&1; then
    docker-compose -f "${COMPOSE_FILE}" "$@"
    return 0
  fi

  echo "[ERROR] docker compose is not available."
  exit 1
}

start_script_background() {
  local name="${1}"
  local script_path="${2}"
  local pid_file="${3}"
  local log_file="${4}"
  local pid=""

  ensure_runtime_dirs
  cleanup_pid_file "${pid_file}"

  if [[ -f "${pid_file}" ]]; then
    pid="$(read_pid_file "${pid_file}")"
    if is_pid_running "${pid}"; then
      echo "[INFO] ${name} already running (PID ${pid})."
      return 0
    fi
  fi

  echo "[INFO] Starting ${name}..."
  nohup bash "${script_path}" > "${log_file}" 2>&1 &
  pid=$!
  echo "${pid}" > "${pid_file}"

  sleep 2
  if is_pid_running "${pid}"; then
    echo "[OK] ${name} started (PID ${pid})."
    return 0
  fi

  echo "[ERROR] ${name} failed to start. Recent logs:"
  tail -n 60 "${log_file}" 2>/dev/null || true
  rm -f "${pid_file}"
  return 1
}

stop_by_pid_file() {
  local name="${1}"
  local pid_file="${2}"
  local pid=""

  cleanup_pid_file "${pid_file}"

  if [[ ! -f "${pid_file}" ]]; then
    echo "[INFO] ${name} is not tracked."
    return 0
  fi

  pid="$(read_pid_file "${pid_file}")"
  if ! is_pid_running "${pid}"; then
    echo "[INFO] ${name} already stopped."
    rm -f "${pid_file}"
    return 0
  fi

  echo "[INFO] Stopping ${name} (PID ${pid})..."
  kill "${pid}" 2>/dev/null || true

  for _ in {1..10}; do
    if ! is_pid_running "${pid}"; then
      rm -f "${pid_file}"
      echo "[OK] ${name} stopped."
      return 0
    fi
    sleep 1
  done

  echo "[WARN] ${name} did not stop in time, forcing kill."
  kill -9 "${pid}" 2>/dev/null || true
  rm -f "${pid_file}"
}

process_status_text() {
  local pid_file="${1}"
  local pid=""

  cleanup_pid_file "${pid_file}"

  if [[ -f "${pid_file}" ]]; then
    pid="$(read_pid_file "${pid_file}")"
    if is_pid_running "${pid}"; then
      echo "RUNNING(pid=${pid})"
      return 0
    fi
  fi

  echo "STOPPED"
  return 0
}
