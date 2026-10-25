#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export SUPPORT_COUCHDB_URL= TELEMETRY_COUCHDB_URL= FSM_APP_KEY=fixture FSM_MEDIA_ENDPOINT=http://127.0.0.1:18190
export HOST=127.0.0.1 PORT=${PORT:-18102} ENVIRONMENT=production
export REDIS_URL=${FIXTURE_REDIS_URL:-memory://} API_KEY_SECRET=fixture-admin
export SUPABASE_URL=http://127.0.0.1:18190 SUPABASE_SECRET_KEY=fixture CERTIFICATIONS_SERVICE_KEY=fixture-service
export FERNET_KEY_SECRET=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
export SERVER_FERNET_KEY_SECRET=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
export TEST_SQLITE_PATH=${TEST_SQLITE_PATH:-$PWD/docs/rust-migration/rust-snapshot.sqlite}
export CERTIFICATIONS_UPSTREAM=http://127.0.0.1:18190 CORTEX_UPSTREAM=http://127.0.0.1:18190 DOMAIN_UPSTREAM=http://127.0.0.1:18190 WILSON_BORBA_UPSTREAM=http://127.0.0.1:18190 REPORTS_UPSTREAM=http://127.0.0.1:18190
export PUBLIC_PROXY_ROUTES='{"reports":{"GET":["/catalog","/bytes/*","/delay/*","/failure","/projects/*"]},"domain":{"GET":["/projects/*"]}}'
export TOKIO_WORKER_THREADS=4
exec target/release/api-for-apps
