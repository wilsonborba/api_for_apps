import unittest

from src.domain.services.user_service import UserService


class _SupabasePasswordAuth:
    def sign_in_with_password(self, email, password):
        return {"access_token": "supabase-access-token"}


class SupabasePasswordTokenContractTests(unittest.TestCase):
    def test_password_sign_in_uses_top_level_access_token(self):
        service = UserService.__new__(UserService)
        service.supabase_auth_adapter = _SupabasePasswordAuth()
        service._validate_email = lambda email: True
        service.exchange_authenticated_session = lambda token, app: token

        result = service.log_in_with_active_provider(
            "user@example.com",
            "valid-password",
            "certifications",
        )

        self.assertEqual(result, "supabase-access-token")
