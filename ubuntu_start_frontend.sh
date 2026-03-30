#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ubuntu_common.sh"

FRONTEND_DIR="${PROJECT_DIR}/frontend"

require_command npm

if [[ ! -d "${FRONTEND_DIR}" ]]; then
  echo "[ERROR] Frontend directory not found: ${FRONTEND_DIR}"
  exit 1
fi

if [[ ! -f "${FRONTEND_DIR}/package.json" ]]; then
  echo "[ERROR] package.json not found in ${FRONTEND_DIR}"
  exit 1
fi

if is_port_listening "${FRONTEND_PORT}"; then
  echo "[ERROR] Port ${FRONTEND_PORT} is already in use. Frontend cannot start."
  echo "Check with: lsof -i :${FRONTEND_PORT}"
  echo "Or stop old process with: fuser -k ${FRONTEND_PORT}/tcp"
  exit 1
fi

cd "${FRONTEND_DIR}"

if [[ ! -d "node_modules" ]]; then
  echo "[INFO] node_modules missing, running npm install..."
  npm install
fi

echo "========================================"
echo "Starting Vite frontend"
echo "Frontend URL: http://localhost:${FRONTEND_PORT}"
echo "========================================"
echo

exec npm run dev -- --host "${FRONTEND_HOST}" --port "${FRONTEND_PORT}"
