#!/usr/bin/env bash
set -euo pipefail
if [[ $(id -u) -ne 0 ]]; then echo 'Run sudo scripts/install_service.sh' >&2; exit 1; fi
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
BUILD_USER=${SUDO_USER:-$(stat -c %U "$PROJECT_DIR")}
BUILD_HOME=$(getent passwd "$BUILD_USER" | cut -d: -f6)
CARGO_BIN="$BUILD_HOME/.cargo/bin/cargo"
if [[ ! -x "$CARGO_BIN" ]]; then echo "Cargo is missing for $BUILD_USER: $CARGO_BIN" >&2; exit 1; fi
if [[ ! -f "$PROJECT_DIR/.env" ]]; then echo 'The canonical .env is required.' >&2; exit 1; fi
cd "$PROJECT_DIR"
# Discovery reads source code only. Its Python helper is build tooling, not the API runtime.
runuser -u "$BUILD_USER" -- python3 tools/generate_docs.py
runuser -u "$BUILD_USER" -- "$CARGO_BIN" build --release --locked
# Installation never runs migrations. Existing PostgreSQL/Alembic history stays intact.
cat > /etc/systemd/system/asodya-api.service <<UNIT
[Unit]
Description=Asodya API Service (Rust)
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PROJECT_DIR}/scripts/app_prod_run.sh
Restart=always
RestartSec=5
StandardOutput=append:/var/log/asodya-api.log
StandardError=append:/var/log/asodya-api.log

[Install]
WantedBy=multi-user.target
UNIT
touch /var/log/asodya-api.log
chmod 644 /var/log/asodya-api.log
systemctl daemon-reload
systemctl enable asodya-api.service
systemctl restart asodya-api.service
systemctl is-active --quiet asodya-api.service
echo "Installed Rust asodya-api. Bangkok deployment time: $(TZ=Asia/Bangkok date --iso-8601=seconds)"
