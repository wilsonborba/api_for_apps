#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR/.."
export ENVIRONMENT=production
export HOST=${HOST:-0.0.0.0} PORT=${PORT:-8101}
export TOKIO_WORKER_THREADS=${TOKIO_WORKER_THREADS:-4}
BINARY="$PWD/target/release/api-for-apps"
if [[ ! -x "$BINARY" ]]; then
  echo 'Rust binary missing. Run scripts/install_service.sh with sudo first.' >&2
  exit 1
fi
exec "$BINARY"
