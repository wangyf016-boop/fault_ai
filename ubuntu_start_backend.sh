#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ubuntu_common.sh"

if [[ ! -f "${PROJECT_DIR}/.venv/bin/activate" ]]; then
  echo "[ERROR] Python virtual environment not found: ${PROJECT_DIR}/.venv/bin/activate"
  echo "Create it with: python3 -m venv .venv"
  exit 1
fi

if is_port_listening "${BACKEND_PORT}"; then
  echo "[ERROR] Port ${BACKEND_PORT} is already in use. Backend cannot start."
  echo "Check with: lsof -i :${BACKEND_PORT}"
  echo "Or stop old process with: fuser -k ${BACKEND_PORT}/tcp"
  exit 1
fi

cd "${PROJECT_DIR}"
source .venv/bin/activate

echo "========================================"
echo "Starting FastAPI backend"
echo "Backend URL: http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "========================================"
echo

exec python -m uvicorn app.server:app \
  --host "${BACKEND_HOST}" \
  --port "${BACKEND_PORT}" \
  --reload
