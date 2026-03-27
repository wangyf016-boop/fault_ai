#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.ubuntu.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "[ERROR] docker is not installed or not in PATH."
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "[ERROR] docker compose is not available."
  exit 1
fi

echo "========================================"
echo "Starting Neo4j and Qdrant with Docker"
echo "Project root: ${SCRIPT_DIR}"
echo "========================================"

"${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" up -d

echo
echo "Neo4j:  http://localhost:${NEO4J_HTTP_PORT:-7474}"
echo "Qdrant: http://localhost:${QDRANT_HTTP_PORT:-6333}"
echo
echo "Use ./stop_infra.sh to stop the containers."
