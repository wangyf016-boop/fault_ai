#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ubuntu_common.sh"

print_row() {
  local service="${1}"
  local process_state="${2}"
  local endpoint_state="${3}"
  printf "%-12s %-22s %-12s\n" "${service}" "${process_state}" "${endpoint_state}"
}

docker_state() {
  local container_name="${1}"
  if ! command -v docker >/dev/null 2>&1; then
    echo "NO_DOCKER"
    return 0
  fi

  local state=""
  state="$(docker inspect -f '{{.State.Status}}' "${container_name}" 2>/dev/null || true)"
  if [[ -z "${state}" ]]; then
    echo "NOT_CREATED"
  else
    echo "${state}"
  fi
}

endpoint_state() {
  local url="${1}"
  if http_ok "${url}"; then
    echo "OK"
  else
    echo "FAIL"
  fi
}

echo "========================================"
echo "Fault AI status (Ubuntu)"
echo "========================================"
printf "%-12s %-22s %-12s\n" "SERVICE" "PROCESS" "HEALTH"
printf "%-12s %-22s %-12s\n" "------------" "----------------------" "------------"

neo4j_process="$(docker_state "fault_ai_neo4j")"
qdrant_process="$(docker_state "fault_ai_qdrant")"

print_row "neo4j" "${neo4j_process}" "$(endpoint_state "http://127.0.0.1:${NEO4J_HTTP_PORT}")"
print_row "qdrant" "${qdrant_process}" "$(endpoint_state "http://127.0.0.1:${QDRANT_HTTP_PORT}")"
print_row "backend" "$(process_status_text "${BACKEND_PID_FILE}")" "$(endpoint_state "http://127.0.0.1:${BACKEND_PORT}/docs")"
print_row "frontend" "$(process_status_text "${FRONTEND_PID_FILE}")" "$(endpoint_state "http://127.0.0.1:${FRONTEND_PORT}")"
print_row "ollama" "$(process_status_text "${OLLAMA_PID_FILE}")" "$(endpoint_state "${OLLAMA_HEALTH_URL}")"

echo
echo "Logs:"
echo "  ${LOG_DIR}/backend.log"
echo "  ${LOG_DIR}/frontend.log"
echo "  ${LOG_DIR}/ollama.log"
