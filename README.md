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

The gateway forwards `/apps/{app}/v1/{path}` to each registered backend. It validates sessions and permissions before adding internal identity headers. Authentication uses Supabase through the gateway, single-use Fernet exchange artifacts, and Redis-backed `sid`/`csrf` sessions. Installed apps use the same routes: the browser login stores a one-use handoff, and the app finishes it with one `POST /apps/api/v1/exchange` carrying `handoff_id` and `secret` (no polling, no new route). Add `cancel:true` to cancel a pending login with the same device secret, even before browser completion. Cancelled logins answer `HANDOFF_CANCELLED`; a late browser login cannot complete them. The browser can check once on focus with `status:true`, `app`, `handoff_id`, and `challenge` to show cancellation. Finish and retry return optional `data.location` from trusted Cloudflare browser-login location headers, with city and/or ISO country code. Clients show a localized country name when available, otherwise the code. The success message uses `Logged in from <city, country>` or `Logged in` when absent. Their sessions renew a 30 day idle limit on each use and end after 90 days. `NATIVE_HANDOFF_ENABLED=false` turns this path off. The central API documentation lists the fields and answers.

Backends receive `x-display-name` when an authenticated account has a first or last name. The gateway reads the current account record, joins nonblank stored first and last names with one space, and percent-encodes the UTF-8 bytes. Decode once with a UTF-8 percent decoder, not a form decoder. For example, `Jos%C3%A9%20Silva` decodes to `José Silva`. The header is omitted when no name exists or no account identity is attached. Client-sent copies are always removed, including on public routes. This adds no route or user setting.


PostgreSQL stores identity, the ticket index, logs and frontend telemetry. CouchDB stores support threads. SQLite is limited to isolated test fixtures.

## Central documentation

All gateway and downstream documentation content belongs to this repository. No downstream OpenAPI endpoint is required.

`tools/generate_docs.py` reads configured sibling service sources without importing or starting them. It builds detailed central contracts. English descriptions and reviewed exceptions live in `src/presentation/assets/`. Use `--check` to detect an outdated generated inventory.

The running Rust API also checks available source registrations when `/openapi.json` is requested. It caches the result for ten seconds. Source checksums flag changes to routes or imported models. New routes appear with explicit contract gaps until central generation or a reviewed override supplies their details. The running API reloads centrally generated contracts without a restart. Missing source repositories retain their last verified contracts and report their status. Source scanning never changes service code.

Only `/docs` serves the gateway documentation UI. `/scalar` is not a gateway documentation page.

## Administrative live logs

- `GET /apps/api/v1/logs/stream`: gateway Server-Sent Events.
- `GET /apps/cortex/v1/logs/stream`: Cortex backend Server-Sent Events stream through the gateway.
- `WS /apps/certifications/v1/logs/stream`: existing Certifications stream through the gateway (adapted to SSE at `/apps/certifications/v1/logs/stream`).

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

The installed-app handoff Valkey tests run only when `TEST_VALKEY_URL` points at a disposable loopback instance (not port 6379), for example `TEST_VALKEY_URL=redis://127.0.0.1:16379/0 cargo test valkey_handoff`. Without it they are skipped. Use designated isolated fixtures for mutation tests. The tools reject production benchmark targets. Real snapshots and measurements stay in the ignored local `docs/` directory. SQLite verification does not establish PostgreSQL locking or concurrency parity.

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
Annotations Rust `lib/presentation` routes and namespaced request contracts. The
Annotations public browser origin (`https://annotations.asodya.com`) and loopback
defaults (`http://localhost:8112`, `http://127.0.0.1:8112`) are registered in
`APP_EXCHANGE_ORIGINS` for `POST /apps/api/v1/exchange`; any deployment-specific
development/preview origins are configured through runtime `APP_EXCHANGE_ORIGINS`.

## App catalog schema foundation

`appdb.public.defaultdb_app` (`id`, `name`, `is_active`) is the relational target
for app-scoped features such as plans, waitlists and support tickets. The
migration contains schema only and adds no rows.

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

## Central plan catalog

The gateway stores plans and features as normalized rows linked to
`defaultdb_app`. Free (`code: free`) is the only plan that can be active.
There is no billing, paid priority, quota enforcement or automatic subscription.

Apply the schema explicitly before using plan operations:

```sh
python scripts/migrate_plans.py --env-file /path/to/canonical/.env --dry-run
python scripts/migrate_plans.py --env-file /path/to/canonical/.env --yes
```

The migration adds no application, plan or feature rows. Administrators manage
plans, features and their memberships through `/apps/api/v1/admin/...`.
`GET /apps/api/v1/plans?app_id=certifications` is public and returns active plans
and active linked features for an active application. The API reads SQL directly
and disables response caching, so changes are visible on the next read.
The central API documentation lists the request and response contracts.

## Central waitlist and support tickets

`app_waitlist_entries` stores one row per application, target and email. The
target is a plan or a feature of the same application (composite foreign keys)
or a stated communication-interest code. Status is `pending`, `contacted`,
`converted` or `declined`. There are no JSON columns, seed rows or legacy data
copies. Old waitlist rows are not copied.
Support tickets get foreign keys from `source_app` to `defaultdb_app` and from
`user_id` to `defaultdb_user(uuid_id)` (no cascade; the gateway never deletes
users), and a status check (`open`, `pending`, `resolved`, `closed`).

```sh
python scripts/migrate_waitlist_support.py --env-file /path/to/canonical/.env --dry-run
python scripts/migrate_waitlist_support.py --env-file /path/to/canonical/.env --yes
```

The dry run only reads and lists existing tickets that would violate the new
constraints (for example a `source_app` that is not registered, or the ids of
tickets whose `user_id` has no matching user). These findings are informational.
Apply adds `NOT VALID` foreign keys and checks, so old rows remain unchanged
and do not block installation. PostgreSQL enforces the constraints for new
writes. The tool still refuses incompatible column types or a missing unique
user key. It never deletes, copies or rewrites rows.

`POST /apps/api/v1/waitlist` is public and rate limited. Repeated sign-ups are
no-ops, and the response is the same whether or not the email was already listed.
Administrators list entries with filters and bounded pagination and update their
status under `/apps/api/v1/admin/waitlist`. `GET /apps/support/v1/tickets` filters
and paginates in the database (`limit` up to 100, `offset` up to 10000). The
existing app-specific waitlist routes keep working until each app switches.
Run the isolated tests with
`python -m unittest discover -s tools -p test_waitlist_support_migration.py`.

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
Cortex uses its SSE `/logs/stream` endpoint; Certifications keeps its existing WebSocket upgrade, and the gateway
adapts that stream to SSE without changing its backend. Other app streams
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

The shared Flutter package is [`screen_trail`](https://pub.dev/packages/screen_trail).
Each app passes the gateway events and errors URLs to `HttpTrailTransport`.
Each app commits a manifest of its screens and stable dot-path elements.
Sensitive input values are dropped on the device before queueing. Routes omit
query strings and fragments.
The gateway adds a defensive sensitive-name check and redacts credentials.
Existing consent remains unchanged. No additional banner is required.

The old `client-error` and `client-reports` routes remain compatible with deployed
reporters but write to the relational error table. The gateway no longer initializes
or writes the telemetry CouchDB store. Historical CouchDB data remains untouched.

## Recent service contracts (pending review / unreleased cutover)

- **Annotations v2 (`annotations_api`, accepted source snapshot `7e97d15`)**:
  - Notes embed references accept the explicit `(project_slug, report_slug, dataset_id)`
    tuple and owner UUID (`report_id`) for `source: "upload"` (retaining unreleased cutover distinction; no claim deployed).
  - Scoped note-deletion cascade (`annotations_api` backend integration):
    `POST /apps/annotations/v1/me/notes/{note_id}/reports`,
    `GET /apps/annotations/v1/me/notes/{note_id}/reports/delete-preview`,
    `DELETE /apps/annotations/v1/me/notes/{note_id}?delete_owned_reports=true`, and
    `POST /apps/annotations/v1/me/notes/{note_id}/reports/retry-cleanup`.
- **Certifications Rust v2 rewrite (`certifications_api`, accepted source `bb6b70e5`)**:
  - `POST /apps/certifications/v1/studies/{study_id}/sources` (dual request formats: JSON `UploadSourceBody` with reference constraints + `multipart/form-data` with bounded `file`/`filename`/`mime_type` fields, bounded by `max_file_bytes + 64 KiB`, audio magic-byte validation),
    `GET .../content` (`Range` 200/206/416 bounded by `max_file_bytes`, `Cache-Control: no-store`),
    `GET .../preview` (`content_url`, `supports_range`, PDF structure `page_count`, WAV `duration_seconds`),
    `POST /studies/prepared` (`x-service-key` or owned `sources.fsm_ref`), and
    `GET|POST /studies/{study_id}/analysis/stream` (SSE optional analysis).
  - Attempt history/overview, public stats, and public question-version reuse
    are tracked against accepted source (`bb6b70e5`) while explicitly retaining unreleased cutover distinction (no claim deployed).
- **Reports v2 (`reports#70` consumer definitions, pending review)**:
  - Reproducible `aggregate_snapshot` v1 schema, `technical-aggregates` public report, and
    7 card/dataset IDs (`projects-by-status`, `categories-distribution`,
    `languages-distribution`, `project-language-bytes`, `skill-frequency`,
    `issuer-counts`, `certification-type-counts`) in `scripts/catalog/aggregates.py`
    (activated only with explicit `--project <slug>` / `REPORTS_AGGREGATE_PROJECT`).
