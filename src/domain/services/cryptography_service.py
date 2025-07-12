from cryptography.fernet import Fernet

from src.core.settings import app_settings


settings = app_settings()

class CryptographyService:

    def __init__(self, key: bytes = None):
        """Initialize the CryptographyService with a given key."""
        self.default_key = settings.FERNET_KEY_SECRET.encode('utf-8')

        self.cipher = Fernet(key if key else self.default_key)

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt the given data."""
        return self.cipher.encrypt(data)

    def decrypt(self, token: bytes) -> bytes:
        """Decrypt the given token."""
        return self.cipher.decrypt(token)
