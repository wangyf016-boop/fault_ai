#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/ubuntu_common.sh"

echo "========================================"
echo "Stopping Docker services (Neo4j + Qdrant)"
echo "========================================"

run_compose down

echo
echo "[OK] Docker services stopped."
