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

PostgreSQL stores identity, the ticket index, logs and frontend telemetry. CouchDB stores support threads. SQLite is limited to isolated test fixtures.

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

## Annotations integration

Annotations is registered on listener 8111 (`ANNOTATIONS_API_PORT` or an explicit
`ANNOTATIONS_UPSTREAM` override). Its route boundary is explicit even when an older
`.env` overrides the shared proxy policy tables. Public catalog/post/media reads,
link previews, waitlist registration and temporary room operations are anonymous.
All `/admin/` operations require existing administrator authentication; an ordinary
session from another application grants no publishing/private-read access.

Temporary multipart uploads stream through the gateway with a bounded byte count;
JSON bodies are limited to 2 MiB. Client identity headers supplied by a browser are
removed. Client IP comes from the socket, except that a loopback reverse proxy may
supply a validated `CF-Connecting-IP`. Annotations receives the resulting IP for
its aggregate temporary upload quota. No downstream service credential or LAN
authentication system was introduced. Central source discovery includes the
Annotations Rust `lib/presentation` routes and namespaced request contracts.

## App catalog schema foundation

Issue #57 currently provides only `appdb.public.defaultdb_app`: `id`, `name` and
`is_active`. This table is the relational target for later app-scoped features.
The waitlist, support-ticket changes and data transfers from #57 remain deferred
until the owner requests them. The migration contains schema only and adds no rows.

Use an operations Python environment with `python-dotenv` and PostgreSQL `psql`:

```
python scripts/migrate_app_catalog.py --env-file /path/to/canonical/.env --dry-run
python scripts/migrate_app_catalog.py --env-file /path/to/canonical/.env --yes
```

The script accepts only the explicit `appdb` target. It reads credentials through
`python-dotenv`, passes them through the PostgreSQL environment and does not log
them. The dry run only inspects the schema. Application startup and installation
never apply this migration. An existing table is inspected and left unchanged.
Run the isolated schema and dry-run tests with
`python -m unittest discover -s tools -p test_app_catalog.py`.

## Live logs and recording

`core/logs` provides `debug`, `info`, `warning` and `error`. Debug requires
`settings.development()`; an explicit `DEVELOPMENT_MODE` overrides the mode derived
from `ENVIRONMENT`. Info, warning and error remain enabled. Every emitted line has
this format:

```
<RFC3339 timestamp> <LEVEL> api_for_apps <module> <message>
```

The same complete, redacted line goes to stderr/journald and the live broadcast.
Multiline messages are escaped. Secrets, authorization values and cookies are
removed before output. The installer uses journald and creates no rotating log
files. Existing historical files are not deleted by installation.

Administrators can read SSE at `/apps/api/v1/logs/stream` and
`/apps/{registered-app}/v1/logs/stream`. Ordinary sessions and guests receive 403.
Cortex and Certifications keep their existing WebSocket upgrades; the gateway can
also adapt those streams to SSE without changing their backends. Other app streams
use the LAN `/logs/stream` endpoint. An unavailable or not-yet-migrated source
returns 503. App targets come from the server registry, never from a caller URL.
The gateway does not forward browser cookies or credentials to the LAN stream.

Explicit setup, after the read-only dry run:

```
python scripts/migrate_logs.py --env-file /path/to/canonical/.env --dry-run
python scripts/migrate_logs.py --env-file /path/to/canonical/.env --yes
# With the canonical environment loaded by the application:
target/release/api-for-apps sync-log-apps
```

The SQL files contain schema only. The separate sync command registers the known
apps, including `api_for_apps`, and preserves an existing inactive flag. Startup
and installation do not migrate or populate the catalog.

All recording and saved-log routes require administrator access:

- `POST /apps/api/v1/logs/recordings` with `{"app_id":"reports"}` starts saving.
- `GET /apps/api/v1/logs/recordings` lists active recordings and their expiry time.
- `DELETE /apps/api/v1/logs/recordings/{app_id}` stops saving. Streaming continues.
- `GET /apps/api/v1/logs?app_id=&level=&from=&to=&limit=` reads saved rows.

Two deliberate safety locks are code constants in `core/logs`: recordings stop
after **30 minutes (1800 seconds)**, and rows older than **15 days** are purged.
Only one app can be recorded at a time. The monotonic recording deadline cannot
be extended by activity. Recording stops on database failure; a disconnected
source can reconnect within the same deadline. Cleanup runs every ten minutes. Saved-log reads always enforce the 15-day window,
even before the next cleanup tick. A stream gap is stored as a warning.
Retention uses the trusted gateway receipt time, not the source's clock. Removing
these locks requires an explicit future decision. Backends never write `appdb`.
The saved table is relational and contains no JSON columns.

## Frontend telemetry

Errors and usage are separate normalized records in appdb. Run the explicit
schema migration after a dry run with the canonical environment:

```sh
.venv/bin/python scripts/migrate_telemetry.py --env-file .env --dry-run
.venv/bin/python scripts/migrate_telemetry.py --env-file .env --yes
ENVIRONMENT=production target/release/api-for-apps sync-telemetry-apps
```

The CLI registers frontend applications separately from log sources. Installation
and normal startup never create schemas or populate application data.

- `POST /apps/api/v1/telemetry/errors` stores an error with app/session UUID,
  route, error type, message, stack and build version.
- `POST /apps/api/v1/telemetry/events` accepts a session UUID, app, locale, theme,
  viewport width/height and up to 50 mapped events. Every event has a sequence,
  type, screen, route template, path and human-readable element id/label/tree path.
- Batches are atomic and retries are idempotent by session and sequence. A session
  can link anonymous activity to its first authenticated user. Changing users or
  logging out requires a fresh UUID; identity conflicts return 409.
- Writes accept anonymous users. The gateway derives the user from its session
  and the IP from its connection (trusted local Cloudflare ingress only).
  Client-supplied identity fields are rejected. The limit is 120 requests per IP
  per minute and 65,536 bytes per request. Unavailable rate limits fail closed.
- `GET` on `errors`, `events` and `sessions` requires an administrator. Filter by
  app/session/from/to/limit; errors/events support a `before_id` cursor.
- PostgreSQL has relational tables and foreign keys, with no JSON, JSONB or array
  columns. Unit tests use the equivalent SQLite schema only.

The shared Flutter package is `wilsonborba/asodya_tracking`. Each app commits a
manifest of its screens and stable dot-path elements. Sensitive input values are
dropped on the device before queueing. Routes omit query strings and fragments.
The gateway adds a defensive sensitive-name check and redacts credentials.
Existing consent remains unchanged. No additional banner is required.

The old `client-error` and `client-reports` routes remain compatible with deployed
reporters but write to the relational error table. The gateway no longer initializes
or writes the telemetry CouchDB store. Historical CouchDB data remains untouched.
