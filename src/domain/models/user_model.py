from pydantic import BaseModel, Field
from typing import Optional, List, Dict
import uuid


class DatabaseUserModel(BaseModel):

    id: Optional[int] = None  # Auto-incremented ID, optional for new users
    uuid_id: str
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: str
    password: str  # In practice, this should be hashed
    access_level: int = 1  # Default access level
    is_active: bool = True  # Default to active
    last_login: Optional[str] = None  # ISO format datetime string
    date_joined: str  # ISO format datetime string
    phone_number: Optional[str] = None
    firebase_id: Optional[str] = None  # Firebase UID if linked to Firebase user

    def to_firebase_user(self, email_verified: bool) -> 'FirebaseUserModel':
        """
        Convert DatabaseUserModel to FirebaseUserModel.
        """
        return FirebaseUserModel(
            uid=self.firebase_id,
            email=self.email,
            password=self.password,  # In practice, this should be hashed
            display_name=f"{self.first_name} {self.last_name}" if self.first_name or self.last_name else None,
            phone_number=self.phone_number,
            email_verified=email_verified,  # Default to false, should be updated based on verification status
            disabled=not self.is_active,
            provider_data=[{"providerId": "password", "email": self.email}]
        )

class FirebaseUserModel(BaseModel):
    uid: str
    email: Optional[str] = None
    password: Optional[str] = Field(None, alias="password")
    display_name: Optional[str] = Field(None, alias="displayName")
    phone_number: Optional[str] = Field(None, alias="phoneNumber")
    photo_url: Optional[str] = Field(None, alias="photoURL")
    email_verified: Optional[bool] = Field(None, alias="emailVerified")

    provider_data: Optional[List[Dict]] = Field(default_factory=list, alias="providerData")
    is_new_user: Optional[bool] = Field(False, alias="isNewUser")  # Indicates if this is a new user
    metadata: Optional[Dict] = Field(default_factory=dict, alias="metadata")  # Additional metadata

    class Config:
        validate_by_name  = True  # Allows loading from both snake_case and camelCase


    def to_database_user(self,last_login, date_joined, access_level, uuid_id=None, first_name = None, last_name = None) -> DatabaseUserModel:
        """
        Convert FirebaseUserModel to a dictionary suitable for database storage.
        """
        _uuid_id = str(uuid.uuid4()) if uuid_id is None else uuid_id  # Generate a new UUID if not provided


        return DatabaseUserModel(
            uuid_id=_uuid_id,  # Generate a new UUID for the database user
            username=self.email.split('@')[0] if self.email else f"user_{_uuid_id[:8]}",
            email=self.email,
            password=self.password,  # In practice, this should be hashed
            first_name=first_name,
            last_name=last_name,
            access_level=access_level,  # Default access level
            is_active=True,  # Default to active
            last_login=last_login,
            date_joined=date_joined,  # Example date, should be current time in practice
            phone_number=self.phone_number,
            firebase_id=self.uid
        )