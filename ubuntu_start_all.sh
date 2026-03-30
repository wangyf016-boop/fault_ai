#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ubuntu_common.sh"

ensure_runtime_dirs

echo "========================================"
echo "Starting Fault AI full stack (Ubuntu)"
echo "========================================"

bash "${SCRIPT_DIR}/ubuntu_start_db.sh"

if [[ "${START_OLLAMA:-1}" == "1" ]]; then
  if http_ok "${OLLAMA_HEALTH_URL}"; then
    echo "[INFO] Ollama already healthy: ${OLLAMA_BASE_URL}"
  else
    start_script_background \
      "ollama" \
      "${SCRIPT_DIR}/ubuntu_start_ollama.sh" \
      "${OLLAMA_PID_FILE}" \
      "${LOG_DIR}/ollama.log"

    if wait_http_ok "${OLLAMA_HEALTH_URL}" 40; then
      echo "[OK] Ollama API is ready."
    else
      echo "[WARN] Ollama did not become healthy in time. Check logs/ollama.log"
    fi
  fi
else
  echo "[INFO] START_OLLAMA=${START_OLLAMA:-1}, skip ollama startup."
fi

start_script_background \
  "backend" \
  "${SCRIPT_DIR}/ubuntu_start_backend.sh" \
  "${BACKEND_PID_FILE}" \
  "${LOG_DIR}/backend.log"

if wait_http_ok "http://127.0.0.1:${BACKEND_PORT}/docs" 40; then
  echo "[OK] Backend HTTP is ready."
else
  echo "[WARN] Backend health check timeout. Check logs/backend.log"
fi

start_script_background \
  "frontend" \
  "${SCRIPT_DIR}/ubuntu_start_frontend.sh" \
  "${FRONTEND_PID_FILE}" \
  "${LOG_DIR}/frontend.log"

if wait_http_ok "http://127.0.0.1:${FRONTEND_PORT}" 60; then
  echo "[OK] Frontend HTTP is ready."
else
  echo "[WARN] Frontend health check timeout. Check logs/frontend.log"
fi

echo
echo "[DONE] Full stack startup completed."
echo "Neo4j:   http://localhost:${NEO4J_HTTP_PORT}"
echo "Qdrant:  http://localhost:${QDRANT_HTTP_PORT}"
echo "Backend: http://localhost:${BACKEND_PORT}"
echo "Frontend:http://localhost:${FRONTEND_PORT}"
echo "Ollama:  ${OLLAMA_BASE_URL}"
echo
echo "Use ./ubuntu_status.sh to check status."
echo "Use ./ubuntu_stop_all.sh to stop all."
