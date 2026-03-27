#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="${SCRIPT_DIR}/frontend"

if ! command -v npm >/dev/null 2>&1; then
  echo "[ERROR] npm is not installed or not in PATH."
  exit 1
fi

if [[ ! -d "${FRONTEND_DIR}" ]]; then
  echo "[ERROR] frontend directory not found: ${FRONTEND_DIR}"
  exit 1
fi

cd "${FRONTEND_DIR}"

if [[ ! -f "package.json" ]]; then
  echo "[ERROR] package.json not found in ${FRONTEND_DIR}"
  exit 1
fi

if [[ ! -d "node_modules" ]]; then
  echo "node_modules not found, installing frontend dependencies..."
  npm install
fi

HOST="${FRONTEND_HOST:-0.0.0.0}"
PORT="${FRONTEND_PORT:-5173}"

echo "========================================"
echo "Starting Vite frontend"
echo "Frontend URL: http://localhost:${PORT}"
echo "========================================"
echo

exec npm run dev -- --host "${HOST}" --port "${PORT}"
