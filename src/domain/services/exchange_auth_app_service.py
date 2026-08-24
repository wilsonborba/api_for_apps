# domain/services/exchange_auth_app_service.py
import json
import secrets
import time
from typing import Optional, Tuple

from src.core.logs import error
from src.core.settings import app_settings
from src.domain.models.user_model import UserCookieModel
from src.domain.services.cryptography_service import CryptographyService

settings = app_settings()


class ExchangeAuthService:
    def __init__(self):
        self.cryptography_service = CryptographyService()
        self.server_private_crypto_service = CryptographyService(
            key=settings.SERVER_FERNET_KEY_SECRET.encode("utf-8")
        )
    def now_in_seconds(self) -> int:
        return int(time.time())

    def decrypt_auth_exchange_token(self, auth_exchange_token: str) -> dict:
        """Decrypt an api_for_apps-issued, short-lived exchange artifact."""

        decrypted_auth_exchange_token = self.cryptography_service.decrypt(
            auth_exchange_token.encode("utf-8")
        )
        loaded_auth_exchange_payload = json.loads(
            decrypted_auth_exchange_token.decode("utf-8")
        )
        return loaded_auth_exchange_payload

    def validate_auth_exchange_payload(
        self, auth_exchange_payload: dict
    ) -> Tuple[bool, Optional[str]]:
        # check the expiration comparing with current time

        # debug(f"Token to validate: {json.dumps(auth_exchange_payload)}")

        exp_from_token = auth_exchange_payload.get("exp", None)
        if exp_from_token is None:
            return False, "Token does not have expiration field"
        current_time = self.now_in_seconds()
        if current_time > exp_from_token:
            return False, "Token has expired"

        # check if has necessary fields
        necessary_fields = [
            "jti",
            "app",
            "uuid_id",
            "email",
            "access_level",
            "is_active",
            "id",
            "provider_user_id",
        ]

        for field in necessary_fields:
            if field not in auth_exchange_payload:
                error(f"Token is missing field: {field}")
                return False, f"Token is missing field..."

        # check if important fields are not None
        important_fields = [
            "uuid_id",
            "email",
            "access_level",
            "is_active",
            "id",
            "provider_user_id",
        ]
        for field in important_fields:
            if auth_exchange_payload[field] is None:
                error(f"Token field {field} is None")
                return False, f"There is a field with None value"

        if auth_exchange_payload.get("provider") != "supabase":
            return False, "Unsupported identity provider"

        # check if access level is valid need to be in [1, 2,]

        if auth_exchange_payload["access_level"] not in [1, 2, 3]:
            return False, "Invalid access level"

        if not auth_exchange_payload["is_active"]:
            return False, "User is not active"

        return True, "Token is valid"

    def generate_sid(self) -> str:
        return secrets.token_urlsafe(32)

    def generate_csrf_token(self) -> str:
        return secrets.token_urlsafe(24)

    def build_user_cookie(self, auth_exchange_payload: dict) -> UserCookieModel:
        return UserCookieModel(
            session_id=self.generate_sid(),
            provider_user_id=auth_exchange_payload["provider_user_id"],
            access_level=auth_exchange_payload["access_level"],
            user_id=auth_exchange_payload["id"],
            user_uuid_id=auth_exchange_payload["uuid_id"],
            email=auth_exchange_payload["email"],
            csrf_token=self.generate_csrf_token(),
        )

    def encrypt_user_cookie(self, user_cookie: UserCookieModel) -> str:
        user_cookie_dict = user_cookie.to_dict()
        user_cookie_json = json.dumps(user_cookie_dict)
        encrypted_cookie = self.server_private_crypto_service.encrypt(
            user_cookie_json.encode("utf-8")
        )
        return encrypted_cookie.decode("utf-8")
