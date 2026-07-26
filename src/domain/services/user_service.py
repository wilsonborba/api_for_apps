import json
import re
import secrets
import time

from argon2 import PasswordHasher

from src.core.logs import debug, error
from src.dal.local.db_adapter import DBAdapter
from src.dal.remote.firebase_adapter import FirebaseAdapter
from src.dal.remote.supabase_adapter import SupabaseAdapter
from src.domain.models.user_model import FirebaseUserModel
from src.domain.services.cryptography_service import CryptographyService


class UserService:
    _table_name = "defaultdb_user"

    def __init__(self):
        self.db_adapter = DBAdapter()
        self.firebase_adapter = FirebaseAdapter()
        self.supabase_adapter = SupabaseAdapter()
        self.cryptography_service = CryptographyService()
        self._ph = PasswordHasher()

    def fields(self):
        return self.db_adapter.get_fields(self._table_name)

    def _hash_password(self, password: str) -> str:
        return self._ph.hash(password)

    def _verify_password(self, hashed_password: str, plain_password: str) -> bool:
        try:
            return self._ph.verify(hashed_password, plain_password)
        except:
            return False

    def _validate_email(self, email: str) -> bool:
        # Basic email validation logic

        email_regex = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        return re.match(email_regex, email) is not None

    def sign_up(self, raw_user_data):
        firebase_user = raw_user_data

        # 1) build your Pydantic model for the DB row
        db_user = firebase_user.to_database_user(
            last_login=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            date_joined=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            access_level=3,
        )

        # validate email
        if not self._validate_email(db_user.email):
            raise ValueError("Invalid email format.")

        db_user.password = self._hash_password(raw_user_data.password)

        # 2) insert into Postgres and get the new integer ID
        inserted = self.db_adapter.insert_row(
            self._table_name, db_user.model_dump(exclude={"id", "firebase_info", "exp"})
        )
        db_user.id = inserted[0]

        # 3) tack on the rest of your token payload
        db_user.firebase_info = self.firebase_adapter.get_user_info(db_user.firebase_id)
        db_user.exp = int(time.time()) + (3 * 24 * 3600)  # 3 days

        # 4) now let Pydantic do the JSON serialization
        json_bytes = db_user.model_dump_json().encode("utf-8")
        auth_exchange_token = self.cryptography_service.encrypt(json_bytes)
        return auth_exchange_token.decode("utf-8")

    def log_in(self, raw_user_data):
        """
        Log in a user.
        This method should handle user authentication and return user data if successful.

        """

        if not self._validate_email(raw_user_data.email):
            raise ValueError("Invalid email format.")

        db_user = self.db_adapter.read_by_id(
            self._table_name, raw_user_data.email, id_column="email"
        )

        last_login = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        # 3) Verify password
        if not self._verify_password(
            db_user.get("password", ""), raw_user_data.password
        ):
            raise ValueError("Invalid credentials.")

        debug(f"Database user data: {db_user}")

        self.db_adapter.update_row(
            self._table_name, db_user["id"], {"last_login": last_login}
        )

        dumped_db_user = dict(db_user)

        dumped_db_user["last_login"] = last_login
        dumped_db_user["firebase_info"] = self.firebase_adapter.get_user_info(
            dumped_db_user["firebase_id"]
        )
        # Set expiration time to 3 minutes from now
        dumped_db_user["exp"] = int(time.time()) + 180

        # remove password before creating the auth exchange token
        if "password" in dumped_db_user:
            del dumped_db_user["password"]

        # verify is user is active
        if not dumped_db_user.get("is_active", False):
            raise ValueError("User account is inactive.")

        # 1) JSON‑encode your Python dict (double‑quotes, valid JSON)
        json_str: str = json.dumps(dumped_db_user, default=str)

        # 2) Turn it into bytes and encrypt
        auth_exchange_token = self.cryptography_service.encrypt(
            json_str.encode("utf-8")
        )

        return auth_exchange_token.decode("utf-8")

    def exchange_supabase_session(self, access_token: str) -> str:
        supabase_user = self.supabase_adapter.get_user_info(access_token)

        email = supabase_user.get("email")
        provider_user_id = supabase_user.get("id")
        if not email or not provider_user_id:
            raise ValueError("Supabase user payload is missing email or id")

        db_user = self.db_adapter.read_by_id(
            self._table_name, email, id_column="email"
        )

        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        display_name = (
            (supabase_user.get("user_metadata") or {}).get("display_name")
            or (supabase_user.get("user_metadata") or {}).get("full_name")
            or ""
        ).strip()
        first_name = display_name.split(" ")[0] if display_name else None
        last_name = display_name.split(" ")[-1] if display_name and " " in display_name else None

        if db_user is None:
            insert_data = {
                "uuid_id": secrets.token_hex(16),
                "username": email.split("@")[0],
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "password": self._hash_password(secrets.token_urlsafe(32)),
                "access_level": 3,
                "is_active": True,
                "last_login": now,
                "date_joined": now,
                "phone_number": None,
                "firebase_id": provider_user_id,
            }
            inserted = self.db_adapter.insert_row(self._table_name, insert_data)
            db_user = self.db_adapter.read_by_id(
                self._table_name, inserted[0], id_column="id"
            )
        else:
            self.db_adapter.update_row(
                self._table_name,
                db_user["id"],
                {
                    "last_login": now,
                    "firebase_id": provider_user_id,
                    "first_name": db_user.get("first_name") or first_name,
                    "last_name": db_user.get("last_name") or last_name,
                },
            )
            db_user = self.db_adapter.read_by_id(
                self._table_name, db_user["id"], id_column="id"
            )

        dumped_db_user = dict(db_user)
        dumped_db_user["last_login"] = now
        dumped_db_user["firebase_info"] = supabase_user
        dumped_db_user["provider"] = "supabase"
        dumped_db_user["exp"] = int(time.time()) + 180
        dumped_db_user.pop("password", None)

        json_str = json.dumps(dumped_db_user, default=str)
        auth_exchange_token = self.cryptography_service.encrypt(
            json_str.encode("utf-8")
        )
        return auth_exchange_token.decode("utf-8")

    def get_user_by_id(self, user_id):
        user = self.db_adapter.read_by_id(
            table_name=self._table_name, id_value=user_id, id_column="id"
        )

        if user and "password" in user:
            user.pop("password")

        return user

    def update_user(self, user_id, user_data):
        return self.db_adapter.update_row(
            table_name=self._table_name,
            id_value=user_id,
            data=user_data,
            id_column="id",
        )

    def delete_user(self, user_id):
        return self.user_repository.delete(user_id)

    def get_all_users(self):
        all_user_from_db = self.db_adapter.read_all(self._table_name)

        for user in all_user_from_db:
            # remove sensitive field
            user.pop("password", None)

            # optional: attach firebase info
            try:
                user["firebase_info"] = self.firebase_adapter.get_user_info(
                    user["firebase_id"]
                )
            except Exception as e:
                error(f"Error fetching Firebase info for user {user.get('id')}: {e}")

        return all_user_from_db
