



from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FirebaseUserModel:
    uid: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    phone_number: Optional[str] = None
    photo_url: Optional[str] = None
    email_verified: Optional[bool] = None
    disabled: Optional[bool] = None
    provider_data: Optional[list] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "uid": self.uid,
            "email": self.email,
            "display_name": self.display_name,
            "phone_number": self.phone_number,
            "photo_url": self.photo_url,
            "email_verified": self.email_verified,
            "disabled": self.disabled,
            "provider_data": self.provider_data, 
        }