import httpx

from src.core.settings import app_settings


class SupabaseAdapter:
    def __init__(self):
        self.settings = app_settings()

    def get_user_info(self, access_token: str) -> dict:
        if not self.settings.SUPABASE_URL or not self.settings.SUPABASE_ANON_KEY:
            raise ValueError("Supabase configuration is missing")

        response = httpx.get(
            f"{self.settings.SUPABASE_URL}/auth/v1/user",
            headers={
                "apikey": self.settings.SUPABASE_ANON_KEY,
                "Authorization": f"Bearer {access_token}",
            },
            timeout=15.0,
        )
        response.raise_for_status()
        return response.json()
