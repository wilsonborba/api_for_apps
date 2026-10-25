#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
# Read-only. No schema migration runs at application startup or installation.
exec target/release/api-for-apps migration-status
