# api_for_apps

Central API Gateway, Reverse Proxy, and Authentication Middleware for Asodya Applications.

## Overview

`api_for_apps` serves as the central hub and control plane for Asodya's ecosystem of applications. It manages session exchange, role-scoped routing, real-time client error telemetry, and reverse-proxying requests to internal backend services (such as `certifications_api`).

## Key Features

- **Authentication & Session Exchange**: Centralized Supabase session token verification, exchange, and role-scoped authorization.
- **Client Telemetry Engine**: Ingests client errors (`POST /telemetry/v1/client-errors`) with Redis IP-based rate limiting (10 requests/min/IP), asynchronous CouchDB persistence (`client_errors` database), and admin retrieval (`GET /telemetry/v1/client-errors`).
- **Reverse Proxying**: Dynamic, authenticated proxy routing to domain-specific microservices with secure header forwarding and attestation.
- **CORS & Multi-App Support**: Preconfigured cross-origin sharing and routing tailored for Asodya frontend clients (`auth.asodya.com`, `certifications.asodya.com`).

## Architecture & Tech Stack

- **Runtime**: Python 3.12+ / FastAPI / Uvicorn
- **Databases & Cache**:
  - PostgreSQL (via SQLAlchemy & Alembic for user/app schema)
  - CouchDB (for structured client telemetry logs)
  - Redis (for caching, token lookup, and rate limiting)
- **Deployment**: Systemd service (`asodya-api.service`) managed via Cloudflare Tunnel / Reverse Proxy.

## Getting Started

### Prerequisites

- Python 3.12+
- `uv` or `pip`
- Running instances of PostgreSQL, CouchDB, and Redis

### Installation

```bash
# Clone the repository
git clone git@github.com:wilsonborba/api_for_apps.git
cd api_for_apps

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate
uv pip install -e .
```

### Environment Configuration

Create a `.env` file based on `.env.example`:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/asodya
COUCHDB_URL=http://admin:password@localhost:5984
REDIS_URL=redis://localhost:6379/0
SUPABASE_URL=https://<your-project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-key
```

### Running Locally

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

## Changelog & Releases

Changelogs are automatically generated using [git-cliff](https://git-cliff.org) adhering to Conventional Commits.

```bash
# Generate changelog for next release
git cliff -o CHANGELOG.md --tag <tag>
```

## License

Proprietary © Asodya. All rights reserved.
