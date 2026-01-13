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
        self.firebase_adapter = FirebaseAdapter()

    def now_in_seconds(self) -> int:
        return int(time.time())

    def encrypt_new_nonce(self, nonce: str) -> str:
        encrypted_nonce = self.cryptography_service.encrypt(nonce.encode("utf-8"))
        return encrypted_nonce.decode("utf-8")

    def decrypt_token(self, token: str) -> str:
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

        decrypted_token = self.cryptography_service.decrypt(token.encode("utf-8"))
        loaded_token = json.loads(decrypted_token.decode("utf-8"))
        # debug(f"Loaded token type: {type(loaded_token)}")
        return loaded_token

    def validate_token(self, token: str) -> Tuple[bool, Optional[str]]:
        # check the expiration comparing with current time

        # debug(f"Token to validate: {json.dumps(token)}")

        exp_from_token = token.get("exp", None)
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
            if field not in token:
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
            if token[field] is None:
                error(f"Token field {field} is None")
                return False, f"There is a field with None value"

        # check if user exist in firebase
        frb_user = self.firebase_adapter.get_user_info(token["firebase_id"])

        if frb_user is None:
            return False, "User does not exist"

        # check if access level is valid need to be in [1, 2,]

        if token["access_level"] not in [1, 2, 3]:
            return False, "Invalid access level"

        if not token["is_active"]:
            return False, "User is not active"

        return True, "Token is valid"

    def generate_sid(self) -> str:
        return secrets.token_urlsafe(32)

    def generate_nonce(self) -> str:
        return secrets.token_urlsafe(24)

    def build_user_cookie(self, token: str) -> UserCookieModel:
        return UserCookieModel(
            session_id=self.generate_sid(),
            firebase_id=token["firebase_id"],
            access_level=token["access_level"],
            user_id=token["id"],
            user_uuid_id=token["uuid_id"],
            email=token["email"],
            nonce=self.generate_nonce(),
        )

    def encrypt_user_cookie(self, user_cookie: UserCookieModel) -> str:
        user_cookie_dict = user_cookie.to_dict()
        user_cookie_json = json.dumps(user_cookie_dict)
        encrypted_cookie = self.server_private_crypto_service.encrypt(
            user_cookie_json.encode("utf-8")
        )
        return encrypted_cookie.decode("utf-8")
