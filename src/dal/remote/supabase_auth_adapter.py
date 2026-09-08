import base64
import hashlib
import secrets
from urllib.parse import urlencode

import httpx

from src.core.settings import app_settings


class SupabaseAuthAdapter:
    def __init__(self):
        self.settings = app_settings()

    def sign_in_with_password(self, email: str, password: str) -> dict:
        response = httpx.post(
            f"{self.settings.SUPABASE_URL}/auth/v1/token",
            headers=self._default_headers(),
            params={"grant_type": "password"},
            json={"email": email, "password": password},
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()

    def sign_up(
        self,
        email: str,
        password: str,
        display_name: str | None = None,
        redirect_to: str | None = None,
    ) -> dict:
        payload = {"email": email, "password": password}
        if display_name:
            payload["data"] = {"display_name": display_name}
        response = httpx.post(
            f"{self.settings.SUPABASE_URL}/auth/v1/signup",
            headers=self._default_headers(),
            params={"redirect_to": redirect_to} if redirect_to else None,
            json=payload,
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()

    def send_password_recovery(self, email: str, redirect_to: str) -> None:
        response = httpx.post(
            f"{self.settings.SUPABASE_URL}/auth/v1/recover",
            headers=self._default_headers(),
            json={"email": email},
            params={"redirect_to": redirect_to},
            timeout=20.0,
        )
        response.raise_for_status()

    def resend_signup_confirmation(self, email: str, redirect_to: str) -> None:
        response = httpx.post(
            f"{self.settings.SUPABASE_URL}/auth/v1/resend",
            headers=self._default_headers(),
            json={
                "type": "signup",
                "email": email,
            },
            params={"redirect_to": redirect_to},
            timeout=20.0,
        )
        response.raise_for_status()

    def update_password(self, access_token: str, new_password: str) -> dict:
        response = httpx.put(
            f"{self.settings.SUPABASE_URL}/auth/v1/user",
            headers={
                **self._default_headers(),
                "Authorization": f"Bearer {access_token}",
            },
            json={"password": new_password},
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()

    def get_user_info(self, access_token: str) -> dict:
        response = httpx.get(
            f"{self.settings.SUPABASE_URL}/auth/v1/user",
            headers={
                **self._default_headers(),
                "Authorization": f"Bearer {access_token}",
            },
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()

    def user_exists_by_email(self, email: str) -> bool:
        """Check Auth users server-side using GoTrue's paginated admin API."""
        normalized_email = email.strip().lower()
        page = 1
        per_page = 1000
        while True:
            response = httpx.get(
                f"{self.settings.SUPABASE_URL}/auth/v1/admin/users",
                headers=self._default_headers(),
                params={"page": page, "per_page": per_page},
                timeout=20.0,
            )
            response.raise_for_status()
            users = response.json().get("users", [])
            if any(
                str(user.get("email") or "").strip().lower() == normalized_email
                for user in users
            ):
                return True
            if len(users) < per_page:
                return False
            page += 1

    def get_oauth_authorization_url(
        self,
        provider: str,
        redirect_to: str,
        state: str,
        code_challenge: str,
        scopes: str | None = None,
    ) -> str:
        query_params = {
            "provider": provider,
            "redirect_to": redirect_to,
            "state": state,
            "flow_type": "pkce",
            "code_challenge": code_challenge,
            "code_challenge_method": "s256",
        }
        if scopes:
            query_params["scopes"] = scopes
        return f"{self.settings.SUPABASE_URL}/auth/v1/authorize?{urlencode(query_params)}"

    def exchange_code_for_session(self, code: str, code_verifier: str) -> dict:
        response = httpx.post(
            f"{self.settings.SUPABASE_URL}/auth/v1/token",
            headers=self._default_headers(),
            params={"grant_type": "pkce"},
            json={"auth_code": code, "code_verifier": code_verifier},
            timeout=20.0,
        )
        response.raise_for_status()
        return response.json()

    def generate_pkce_verifier(self) -> str:
        return secrets.token_urlsafe(64)

    def generate_pkce_challenge(self, verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")

    def _default_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "apikey": self.settings.SUPABASE_SECRET_KEY,
        }
