#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ubuntu_common.sh"

echo "========================================"
echo "Starting Docker services (Neo4j + Qdrant)"
echo "========================================"

run_compose up -d neo4j qdrant

echo
echo "[OK] Docker services started."
echo "Neo4j:  http://localhost:${NEO4J_HTTP_PORT}"
echo "Qdrant: http://localhost:${QDRANT_HTTP_PORT}"
