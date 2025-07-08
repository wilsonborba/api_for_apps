    # src/dal/external/firebase_adapter.py

from src.core.settings import app_settings
import firebase_admin
from firebase_admin import credentials, auth
from typing import Optional, Dict
import os

from src.domain.models.user_model import FirebaseUserModel





class FirebaseAdapter:
    def __init__(self, service_account_path: Optional[str] = None):
        if not firebase_admin._apps:
            cred_path = service_account_path or app_settings().FIREBASE_SERVICE_ACCOUNT_PATH
            if not cred_path:
                raise ValueError("Firebase service account path not provided")

            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)

    def get_user_info(self, uid: str) -> Dict:
        """
        Fetch user info from Firebase Authentication by UID.
        """
        try:
            user = auth.get_user(uid)
            return FirebaseUserModel(
                uid=user.uid,
                email=user.email,
                display_name=user.display_name,
                phone_number=user.phone_number,
                photo_url=user.photo_url,
                email_verified=user.email_verified,
                disabled=user.disabled,
                provider_data=[p.__dict__ for p in user.provider_data]
            ).model_dump()
        

        except auth.UserNotFoundError:
            raise ValueError(f"User with UID '{uid}' not found")

    def verify_token(self, id_token: str) -> dict:
        """
        Verify Firebase ID token (JWT) and return claims.
        """
        try:
            return auth.verify_id_token(id_token)
        except auth.InvalidIdTokenError:
            raise ValueError("Invalid Firebase ID token")
        except auth.ExpiredIdTokenError:
            raise ValueError("Expired Firebase ID token")
