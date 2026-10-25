# Asodya Application Gateway

Rust API for Asodya authentication, application proxying, support tickets, and frontend error reports.

The public API is `https://api.asodya.com`. Public English documentation uses Scalar at `/docs`. Administrative operations remain protected even though their descriptions are public.

## Requirements

- Rust stable and Cargo.
- PostgreSQL, Redis or Valkey, CouchDB, and configured Supabase/FSM services.
- Python 3 for the build-time source documentation extractor and development measurement tools. The API process runs entirely in Rust.

Keep private connection values and credentials in the canonical `.env`. Start from `.env.example`. Non-secret defaults and application registration live in `src/core/defaults.json` and `src/core/apps.json`.

## Build and run

```sh
python3 tools/generate_docs.py
cargo build --release --locked
scripts/app_prod_run.sh
```

The production listener defaults to `0.0.0.0:8101`. `HOST`, `PORT`, and `TOKIO_WORKER_THREADS` can override process settings. The production launcher defaults to four Tokio workers.

```sh
sudo scripts/install_service.sh
```

The installer builds as the repository owner, installs `asodya-api.service`, and restarts the service. It does not run migrations.

For local development:

```sh
scripts/app_dev_run.sh
```

## Architecture

- `src/core`: configuration and logging.
- `src/dal`: PostgreSQL/SQLite, Redis MessagePack, and CouchDB adapters.
- `src/domain`: authentication, support, proxying, and central source discovery.
- `src/presentation`: request handlers, validation, Scalar, and documentation assets.
- `src/main.rs`: startup, listener, operational commands, and shutdown.

The gateway forwards `/apps/{app}/v1/{path}` to each registered backend. It validates sessions and permissions before adding internal identity headers. Authentication uses Supabase through the gateway, single-use Fernet exchange artifacts, and Redis-backed `sid`/`csrf` sessions.

PostgreSQL remains the identity and ticket index store. CouchDB stores support threads and frontend telemetry. SQLite is limited to isolated test fixtures.

## Central documentation

All gateway and downstream documentation content belongs to this repository. No downstream OpenAPI endpoint is required.

`tools/generate_docs.py` reads configured sibling service sources without importing or starting them. It builds detailed central contracts. English descriptions and reviewed exceptions live in `src/presentation/assets/`. Use `--check` to detect an outdated generated inventory.

The running Rust API also checks available source registrations when `/openapi.json` is requested. It caches the result for ten seconds. Source checksums flag changes to routes or imported models. New routes appear with explicit contract gaps until central generation or a reviewed override supplies their details. The running API reloads centrally generated contracts without a restart. Missing source repositories retain their last verified contracts and report their status. Source scanning never changes service code.

Only `/docs` serves the gateway documentation UI. `/scalar` is not a gateway documentation page.

## Administrative live logs

- `GET /apps/api/v1/logs/stream`: gateway Server-Sent Events.
- `WS /apps/cortex/v1/logs/stream`: existing Cortex backend stream through the gateway.
- `WS /apps/certifications/v1/logs/stream`: existing Certifications stream through the gateway.

These require an administrator session or administrative credential. The gateway rechecks authorization during each connection. Streams use bounded buffering and create no new archive. Existing system logging continues normally.

## Verification and existing database history

```sh
cargo test
cargo clippy --all-targets -- -D warnings
python3 -m unittest discover -s tools -p 'test_docs_generation.py'
target/release/api-for-apps check-storage
scripts/migration_status.sh
```

`check-storage` and `migration-status` perform reads only. The Rust application recognizes the existing Alembic revision `20260909_01`. Historical revision IDs, source hashes, and the Python reference tag are recorded in `src/dal/data/migration_history.json`. Startup and installation never replay historical migrations.

Use designated isolated fixtures for mutation tests. The tools reject production benchmark targets. Real snapshots and measurements stay in the ignored local `docs/` directory. SQLite verification does not establish PostgreSQL locking or concurrency parity.

## Historical Python baseline

The previous Python runtime remains recoverable from Git tag `v1.1.0`. Temporary migration worktrees and the old Python virtual environment were removed after the Rust cutover. Future application changes happen in the canonical `api_for_apps` Rust checkout. Recreate a separate checkout and development environment explicitly if you need to repeat the historical Python benchmarks. Preserve local `.env` and measurement files.

Scalar 1.76.0 and Ubuntu fonts are bundled under `src/presentation/assets/vendor/`, with source/license notices. `/docs` loads its browser assets from this API, without CDN or external font requests. The Scalar script is gzip-compressed and cached. The page displays a readable error if its API description cannot load.

Browser verification uses `tools/test_docs_browser.py` with an optional Playwright installation and an existing Chrome executable; it blocks external requests, checks rendered routes, captures a screenshot and verifies schema-load failure feedback.
