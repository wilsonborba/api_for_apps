from dataclasses import dataclass
from typing import Any, Dict, Optional

from pydantic import BaseModel


class DatabaseUserModel(BaseModel):
    id: Optional[int] = None
    uuid_id: str
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: str
    password: str
    access_level: int = 1
    is_active: bool = True
    last_login: Optional[str] = None
    date_joined: str
    phone_number: Optional[str] = None
    supabase_user_id: Optional[str] = None
    exp: Optional[int] = None


@dataclass
class UserCookieModel:
    session_id: str
    provider_user_id: str
    access_level: int
    user_id: int
    user_uuid_id: str
    email: str
    csrf_token: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "provider_user_id": self.provider_user_id,
            "access_level": self.access_level,
            "user_id": self.user_id,
            "user_uuid_id": self.user_uuid_id,
            "email": self.email,
            "csrf_token": self.csrf_token,
        }
