from src.core.settings import app_settings
from src.dal.remote.firebase_adapter import FirebaseAdapter
from src.dal.remote.supabase_auth_adapter import SupabaseAuthAdapter


class AuthProviderAdapter:
    def __init__(self):
        self.settings = app_settings()
        self._firebase_adapter: FirebaseAdapter | None = None
        self.supabase_auth_adapter = SupabaseAuthAdapter()

    @property
    def firebase_adapter(self) -> FirebaseAdapter:
        if self._firebase_adapter is None:
            self._firebase_adapter = FirebaseAdapter()
        return self._firebase_adapter

    def get_user_info(self, access_token: str) -> dict:
        provider = self.settings.AUTH_PROVIDER.lower()

        if provider == "supabase":
            return self.supabase_auth_adapter.get_user_info(access_token)

        if provider == "firebase":
            claims = self.firebase_adapter.verify_token(access_token)
            uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
            if not uid:
                raise ValueError("Firebase token does not contain a user identifier")
            return self.firebase_adapter.get_user_info(uid)

        raise ValueError(f"Unsupported auth provider: {self.settings.AUTH_PROVIDER}")
