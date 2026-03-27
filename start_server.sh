#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

if [[ ! -f ".venv/bin/activate" ]]; then
  echo "[ERROR] Python virtual environment not found at .venv/bin/activate"
  echo "Create it first with: python3 -m venv .venv"
  exit 1
fi

source .venv/bin/activate

HOST="${BACKEND_HOST:-0.0.0.0}"
PORT="${BACKEND_PORT:-8000}"

echo "========================================"
echo "Starting FastAPI backend"
echo "Project root: ${SCRIPT_DIR}"
echo "Backend URL:  http://${HOST}:${PORT}"
echo "========================================"
echo

exec python -m uvicorn app.server:app \
  --host "${HOST}" \
  --port "${PORT}" \
  --reload
