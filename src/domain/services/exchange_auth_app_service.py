# domain/services/exchange_auth_app_service.py
import json
import secrets
import time
from typing import Dict, Optional, Tuple

from src.core.logs import debug, error
from src.core.settings import app_settings
from src.dal.remote.firebase_adapter import FirebaseAdapter
from src.domain.models.user_model import UserCookieModel
from src.domain.services.cryptography_service import CryptographyService

settings = app_settings()


class ExchangeAuthService:
    def __init__(self):
        self.cryptography_service = CryptographyService()
        self.server_private_crypto_service = CryptographyService(
            key=settings.SERVER_FERNET_KEY_SECRET.encode("utf-8")
        )
        self._firebase_adapter: FirebaseAdapter | None = None

    @property
    def firebase_adapter(self) -> FirebaseAdapter:
        if self._firebase_adapter is None:
            self._firebase_adapter = FirebaseAdapter()
        return self._firebase_adapter

    def now_in_seconds(self) -> int:
        return int(time.time())

    def decrypt_auth_exchange_token(self, auth_exchange_token: str) -> dict:
        """
        Example of decrypted token:

         {
         "id": 1, "uuid_id": "b7e96850-7be3-4d8e-8bb7-3f2716e29917",
           "username": "wilsonborba", "first_name": null, "last_name": null,
           "email": "wilsonmatheuslimaborba@gmail.com",
           "access_level": 1, "is_active": true, "last_login": "2025-10-02T11:25:18",
           "date_joined": "2025-07-08 14:49:00+07:00", "phone_number": null,
           "firebase_id": "fB68zTp1JFaOHWbrTuHav3o03vk2",
           "firebase_info": {"uid": "fB68zTp1JFaOHWbrTuHav3o03vk2", "email": "wilsonmatheuslimaborba@gmail.com",
           "password": null, "display_name": null,
           "phone_number": null, "photo_url": null,
           "email_verified": true,
           "provider_data": [{"_data":
           {"providerId": "password",
           "federatedId": "wilsonmatheuslimaborba@gmail.com",
           "email": "wilsonmatheuslimaborba@gmail.com",
           "rawId": "wilsonmatheuslimaborba@gmail.com"}}],
           "is_new_user": false, "metadata": {}},
           "exp": 1759404499
           }


        """

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
            "uuid_id",
            "email",
            "access_level",
            "is_active",
            "id",
            "firebase_id",
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
            "firebase_id",
        ]
        for field in important_fields:
            if auth_exchange_payload[field] is None:
                error(f"Token field {field} is None")
                return False, f"There is a field with None value"

        # Tokens minted from the backend's Supabase session exchange are already
        # provider-validated before encryption, so preserve compatibility here
        # without forcing a Firebase lookup for non-Firebase identities.
        if auth_exchange_payload.get("provider") != "supabase":
            frb_user = self.firebase_adapter.get_user_info(
                auth_exchange_payload["firebase_id"]
            )

            if frb_user is None:
                return False, "User does not exist"

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
            firebase_id=auth_exchange_payload["firebase_id"],
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
