#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export ENVIRONMENT=development
export HOST=${HOST:-127.0.0.1} PORT=${PORT:-18102}
CARGO_BIN=${CARGO_BIN:-$HOME/.cargo/bin/cargo}
exec "$CARGO_BIN" run -- "$@"
