# src/core/settings.py


from typing import Dict, List, Tuple
from functools import lru_cache

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.domain.models.db_config_model import DatabaseConfig

load_dotenv()  # Loads .env file


class Settings(BaseSettings):
    # Existing local .env files can contain retired Firebase/development keys;
    # ignore those rather than turning a non-secret compatibility setting into
    # a startup failure.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    # API
    API_ADMIN_KEY_NAME: str = "Authorization"
    API_KEY_SECRET: str  # Will be loaded from .env
    DEFAULT_DB_HOST: str
    DEFAULT_DB_PORT: int
    DEFAULT_DB_USER: str
    DEFAULT_DB_PASSWORD: str
    DEFAULT_DB_NAME: str
    DEFAULT_DB_SSLMODE: str = "require"  # Default SSL mode for PostgreSQL
    # Supabase is the only runtime identity provider.  The Firebase fields in
    # older database rows remain a schema compatibility concern, not an auth
    # integration.
    AUTH_PROVIDER: str = "supabase"
    SUPABASE_URL: str = ""
    SUPABASE_PROJECT_REF: str = ""
    # Server-only credential. Frontends never communicate with Supabase.
    SUPABASE_SECRET_KEY: str
    # Service credential used only for gateway -> Certifications API calls.
    CERTIFICATIONS_SERVICE_KEY: str
    FERNET_KEY_SECRET: str  # Secret key for Fernet encryption, loaded from .env

    # private server key for fernet encryption/decryption
    SERVER_FERNET_KEY_SECRET: str  # Secret key for Fernet encryption, loaded

    # cookies key name
    HTTP_ONLY_COOKIE_KEY_NAME: str = "sid"
    CSRF_COOKIE_KEY_NAME: str = "csrf"

    # REDIS
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    REDIS_NAMESPACE: str = "api_for_apps:"

    # Support tickets document store. Reuses hippocampus's own CouchDB server
    # (see hippocampus's HIPPOCAMPUS_COUCHDB_* settings) in a database
    # dedicated to tickets, never hippocampus's own memories database.
    # Left blank, the document store degrades to an in-memory fallback:
    # PostgreSQL's support_tickets index remains authoritative either way.
    SUPPORT_COUCHDB_URL: str = ""
    SUPPORT_COUCHDB_USERNAME: str = ""
    SUPPORT_COUCHDB_PASSWORD: str = ""
    SUPPORT_COUCHDB_DATABASE: str = "support_tickets"

    # Telemetry client errors document store.
    TELEMETRY_COUCHDB_URL: str = ""
    TELEMETRY_COUCHDB_USERNAME: str = ""
    TELEMETRY_COUCHDB_PASSWORD: str = ""
    TELEMETRY_COUCHDB_DATABASE: str = "client_errors"

    # FSM's Media API uses a private per-application bearer key, same
    # protocol certifications_api already uses for study-source uploads
    # (see FsmMediaAdapter). This is api_for_apps's own app registration
    # ("api_for_apps"), used only for support-ticket attachments. Loaded only
    # from `.env`; no frontend is ever given the credential.
    FSM_MEDIA_ENDPOINT: str = "http://192.168.1.106:8484"
    FSM_APP_NAME: str = "api_for_apps"
    FSM_APP_KEY: str | None = None

    # redis cache prefix
    CACHE_AUTH_PREFIX: str = "exchange_auth_app"
    EXCHANGE_ARTIFACT_PREFIX: str = "exchange_artifact"
    OAUTH_STATE_PREFIX: str = "oauth_state"
    SESSION_TTL_SECONDS: int = 60 * 60 * 25
    CSRF_TTL_SECONDS: int = 60 * 60 * 24
    EXCHANGE_ARTIFACT_TTL_SECONDS: int = 60
    DEFAULT_EXCHANGE_APP: str = "certifications"
    EXCHANGE_ALLOWED_APPS: Tuple[str, ...] = ("certifications", "cortex")
    # Browser origins permitted to redeem an app's short-lived exchange
    # artifact. This is a server-owned allowlist, not frontend context.
    APP_EXCHANGE_ORIGINS: Dict[str, Tuple[str, ...]] = {
        "certifications": (
            "http://localhost:8102",
            "http://127.0.0.1:8102",
            "http://192.168.1.103:8102",
            "http://172.20.10.4:8102",
            "http://100.93.16.79:8102",
            "http://172.17.0.1:8102",
            "https://certifications.asodya.com",
        ),
        # certifications' web build always serves from a fixed LAN port
        # (8102), so its dev origins can be hardcoded above. Cortex's web
        # build (`flutter run -d chrome`) has no fixed dev port unless one
        # is pinned with `--web-port`, so its local origin cannot be
        # guessed here: it is loaded from CORTEX_WEB_LOCAL_ORIGIN (see
        # below) and merged in by `_add_cortex_local_exchange_origin`.
        "cortex": (
            "http://localhost:8105",
            "http://127.0.0.1:8105",
            "http://192.168.1.103:8105",
            "http://172.20.10.4:8105",
            "http://100.93.16.79:8105",
            "http://172.17.0.1:8105",
            "https://cortex.asodya.com",
        ),
    }
    # Optional override for custom Cortex Web App local dev origin.
    CORTEX_WEB_LOCAL_ORIGIN: str = ""

    @model_validator(mode="after")
    def _add_cortex_local_exchange_origin(self) -> "Settings":
        if self.CORTEX_WEB_LOCAL_ORIGIN:
            cortex_origins = self.APP_EXCHANGE_ORIGINS.get("cortex", ())
            if self.CORTEX_WEB_LOCAL_ORIGIN not in cortex_origins:
                self.APP_EXCHANGE_ORIGINS["cortex"] = cortex_origins + (
                    self.CORTEX_WEB_LOCAL_ORIGIN,
                )
        return self

    # Runtime mode is selected by the development/production launch script.
    environment: str = "development"
    ASODYA_MAIN_DOMAIN: str = "asodya.com"
    AUTH_APP_LOCAL_URL: str = "http://192.168.1.103:8100"
    AUTH_APP_PROD_URL: str = "https://auth.asodya.com"
    COOKIE_DOMAIN_PROD: str = ".asodya.com"

    # Public proxy routes (app -> method -> path patterns). Adding another
    # app/route here does not weaken the authenticated generic proxy.
    PUBLIC_PROXY_ROUTES: Dict[str, Dict[str, List[str]]] = {
        "certifications": {
            "GET": ["/quiz/certifications/*"],
            "HEAD": ["/quiz/certifications/*"],
            "OPTIONS": ["/quiz/certifications/*"],
            "POST": ["/waitlist"],
        },
    }
    PUBLIC_PROXY_ALLOWED_METHODS: Tuple[str, ...] = ("GET", "HEAD", "OPTIONS")
    OAUTH_PROVIDERS: Tuple[str, ...] = ("google", "github", "microsoft", "azure")

    # cortex_api proxy (see src/presentation/routes/cortex_route.py). Serves
    # anonymous/guest chat requests, so it deliberately sits outside the
    # session-based verify_auth check used by the generic apps proxy.
    CORTEX_API_HOST: str = "localhost"
    CORTEX_API_PORT: int = 8003
    # Shared HMAC secret used to validate the official Web App's
    # X-Asodya-App-Proof header. Loaded only from `.env`; never hardcode a
    # real value here.
    CORTEX_PROOF_SECRET: str = ""
    CORTEX_APP_ID: str = "cortex_web_app"
    # Requests without a valid X-Asodya-App-Proof are capped at this many
    # per calendar day, per client IP (see enforce_daily_quota).
    CORTEX_DAILY_TEST_LIMIT: int = 5

    @property
    def auth_app_callback_url(self) -> str:
        base_url = self.AUTH_APP_LOCAL_URL if self.development_mode else self.AUTH_APP_PROD_URL
        return f"{base_url}/callback"

    @property
    def auth_app_reset_url(self) -> str:
        base_url = self.AUTH_APP_LOCAL_URL if self.development_mode else self.AUTH_APP_PROD_URL
        return f"{base_url}/reset-password"

    @property
    def cookie_domain(self) -> str | None:
        if self.development_mode:
            return None
        return self.COOKIE_DOMAIN_PROD

    @property
    def development_mode(self) -> bool:
        return self.environment.lower() in {"development", "dev", "local"}

    @property
    def default_db(self) -> DatabaseConfig:
        return DatabaseConfig(
            dialect="postgresql",
            username=self.DEFAULT_DB_USER,
            password=self.DEFAULT_DB_PASSWORD,
            host=self.DEFAULT_DB_HOST,
            port=self.DEFAULT_DB_PORT,
            database=self.DEFAULT_DB_NAME,
            options={"sslmode": self.DEFAULT_DB_SSLMODE},
        )

    # Schema related settings

    class AvailableApps:
        api = "/api"
        certifications = "/certifications"
        cortex = "/cortex"

    @property
    def available_apps(self) -> AvailableApps:
        return self.AvailableApps()


# Singleton
@lru_cache()
def app_settings() -> Settings:
    return Settings()
