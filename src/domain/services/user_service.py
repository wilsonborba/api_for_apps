import json
import re
import secrets
import time

import httpx
from argon2 import PasswordHasher

from src.core.settings import app_settings
from src.dal.local.db_adapter import DBAdapter
from src.dal.remote.supabase_auth_adapter import SupabaseAuthAdapter
from src.domain.services.cryptography_service import CryptographyService


class UserService:
    """Application-user projection backed exclusively by Supabase identity."""

    _table_name = "defaultdb_user"

    def __init__(self):
        self.settings = app_settings()
        self.db_adapter = DBAdapter()
        self.supabase_auth_adapter = SupabaseAuthAdapter()
        self.cryptography_service = CryptographyService()
        self._ph = PasswordHasher()

    def fields(self):
        return self.db_adapter.get_fields(self._table_name)

    def _hash_password(self, password: str) -> str:
        return self._ph.hash(password)

    def _validate_email(self, email: str) -> bool:
        return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None

    @staticmethod
    def _provider_error(exc: httpx.HTTPStatusError) -> ValueError:
        try:
            payload = exc.response.json()
            detail = (
                payload.get("msg") or payload.get("message")
                or payload.get("error_description") or payload.get("error") or ""
            )
        except Exception:
            detail = str(exc)
        lowered = detail.lower()
        if "already registered" in lowered or "already been registered" in lowered:
            return ValueError("This email is already registered. Check your inbox or sign in.")
        if "not confirmed" in lowered or "not verified" in lowered:
            return ValueError("Email not verified. Please confirm your email before signing in.")
        return ValueError(detail or "Supabase authentication failed")

    def _sync_supabase_user(self, access_token: str) -> dict:
        provider_user = self.supabase_auth_adapter.get_user_info(access_token)
        email = provider_user.get("email")
        provider_user_id = provider_user.get("id")
        if not email or not provider_user_id:
            raise ValueError("Supabase user payload is missing email or id")

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        metadata = provider_user.get("user_metadata") or {}
        display_name = (metadata.get("display_name") or metadata.get("full_name") or "").strip()
        name_parts = display_name.split(maxsplit=1)
        first_name = name_parts[0] if name_parts else None
        last_name = name_parts[1] if len(name_parts) > 1 else None
        db_user = self.db_adapter.read_by_id(self._table_name, email, id_column="email")

        if db_user is None:
            # `firebase_id` is a legacy physical column; it now stores only the
            # Supabase subject until a separate database migration can rename it.
            inserted = self.db_adapter.insert_row(self._table_name, {
                "uuid_id": secrets.token_hex(16),
                "username": email.split("@", 1)[0],
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "password": self._hash_password(secrets.token_urlsafe(32)),
                "access_level": 3,
                "is_active": True,
                "last_login": now,
                "date_joined": now,
                "phone_number": None,
                "firebase_id": provider_user_id,
            })
            db_user = self.db_adapter.read_by_id(self._table_name, inserted[0], id_column="id")
        else:
            self.db_adapter.update_row(self._table_name, db_user["id"], {
                "last_login": now,
                "firebase_id": provider_user_id,
                "first_name": db_user.get("first_name") or first_name,
                "last_name": db_user.get("last_name") or last_name,
            })
            db_user = self.db_adapter.read_by_id(self._table_name, db_user["id"], id_column="id")

        if not db_user or not db_user.get("is_active", False):
            raise ValueError("User account is inactive.")
        return {**dict(db_user), "provider_user_id": provider_user_id, "last_login": now}

    def exchange_authenticated_session(self, access_token: str, app: str | None = None) -> str:
        db_user = self._sync_supabase_user(access_token)
        app_id = (app or self.settings.DEFAULT_EXCHANGE_APP).strip().lower()
        if app_id not in self.settings.EXCHANGE_ALLOWED_APPS:
            raise ValueError("Unsupported initiating application")
        payload = {
            "jti": secrets.token_urlsafe(24),
            "app": app_id,
            "provider": "supabase",
            "id": db_user["id"],
            "uuid_id": db_user["uuid_id"],
            "email": db_user["email"],
            "access_level": db_user["access_level"],
            "is_active": db_user["is_active"],
            "provider_user_id": db_user["provider_user_id"],
            "exp": int(time.time()) + self.settings.EXCHANGE_ARTIFACT_TTL_SECONDS,
        }
        return self.cryptography_service.encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")

    def sign_up_with_active_provider(self, email: str, password: str, display_name: str | None = None, app: str | None = None) -> str | None:
        if not self._validate_email(email):
            raise ValueError("Invalid email format.")
        try:
            response = self.supabase_auth_adapter.sign_up(email, password, display_name, self.settings.auth_app_callback_url)
        except httpx.HTTPStatusError as exc:
            raise self._provider_error(exc) from exc
        access_token = (response.get("session") or {}).get("access_token")
        return self.exchange_authenticated_session(access_token, app) if access_token else None

    def log_in_with_active_provider(self, email: str, password: str, app: str | None = None) -> str:
        if not self._validate_email(email):
            raise ValueError("Invalid email format.")
        try:
            response = self.supabase_auth_adapter.sign_in_with_password(email, password)
        except httpx.HTTPStatusError as exc:
            raise self._provider_error(exc) from exc
        access_token = (response.get("session") or {}).get("access_token")
        if not access_token:
            raise ValueError("Supabase did not return an authenticated session")
        return self.exchange_authenticated_session(access_token, app)

    def send_password_recovery(self, email: str) -> None:
        self.supabase_auth_adapter.send_password_recovery(email, self.settings.auth_app_reset_url)

    def resend_signup_confirmation(self, email: str) -> None:
        self.supabase_auth_adapter.resend_signup_confirmation(email, self.settings.auth_app_callback_url)

    def update_password_with_recovery_token(self, access_token: str, new_password: str) -> None:
        self.supabase_auth_adapter.update_password(access_token, new_password)

    def get_user_by_id(self, user_id):
        user = self.db_adapter.read_by_id(self._table_name, user_id, id_column="id")
        if user:
            user.pop("password", None)
        return user

    def update_user(self, user_id, user_data):
        return self.db_adapter.update_row(self._table_name, user_id, user_data, id_column="id")

    def get_all_users(self):
        users = self.db_adapter.read_all(self._table_name)
        for user in users:
            user.pop("password", None)
        return users
