


from src.domain.services.cryptography_service import CryptographyService
from src.domain.models.user_model import FirebaseUserModel
from src.dal.remote.firebase_adapter import FirebaseAdapter
from src.dal.local.db_adapter import DBAdapter
from src.core.logs import debug
import time
import json

class UserService:

    _table_name = "defaultdb_user"

    def __init__(self):
        self.db_adapter = DBAdapter()
        self.firebase_adapter = FirebaseAdapter()
        self.cryptography_service = CryptographyService()
    

    def sign_up(self, raw_user_data):
        firebase_user = raw_user_data

        # 1) build your Pydantic model for the DB row
        db_user = firebase_user.to_database_user(
            last_login=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            date_joined=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            access_level=3,
        )

        

        # 2) insert into Postgres and get the new integer ID
        inserted = self.db_adapter.insert_row(self._table_name, db_user.model_dump(exclude={"id", "firebase_info", "exp"}))
        db_user.id = inserted[0]

        # 3) tack on the rest of your token payload
        db_user.firebase_info = self.firebase_adapter.get_user_info(db_user.firebase_id)
        db_user.exp = int(time.time()) + (3 * 24 * 3600)  # 3 days

        # 4) now let Pydantic do the JSON serialization
        json_bytes = db_user.model_dump_json().encode("utf-8")
        token = self.cryptography_service.encrypt(json_bytes)
        return token

    def log_in(self, raw_user_data):
        """
        Log in a user.
        This method should handle user authentication and return user data if successful.

        """


        db_user = self.db_adapter.read_by_id(
            self._table_name, 
            raw_user_data.email, 
            id_column="email"
        )

        last_login = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())

        debug(f"Database user data: {db_user}")

        self.db_adapter.update_row(
            self._table_name, 
            db_user['id'], 
            {'last_login': last_login}
        )

        dumped_db_user = dict(db_user)

        dumped_db_user['last_login'] = last_login
        dumped_db_user['firebase_info'] = self.firebase_adapter.get_user_info(dumped_db_user['firebase_id'])
        # Set expiration time to 3 minutes from now
        dumped_db_user['exp'] = int(time.time()) + 180

        # 1) JSON‑encode your Python dict (double‑quotes, valid JSON)
        json_str: str = json.dumps(dumped_db_user, default=str)

        # 2) Turn it into bytes and encrypt
        encrypted_usr_as_cookie = self.cryptography_service.encrypt(
            json_str.encode('utf-8')
        )

        return encrypted_usr_as_cookie





    def get_user(self, user_id):
        return self.user_repository.get(user_id)

    def update_user(self, user_id, user_data):
        return self.user_repository.update(user_id, user_data)

    def delete_user(self, user_id):
        return self.user_repository.delete(user_id)
    
    def get_all_users(self):
        
        all_user_from_db = self.db_adapter.read_all(self._table_name)

        for user in all_user_from_db:
            user['firebase_info'] = self.firebase_adapter.get_user_info(user['firebase_id'])

        return all_user_from_db

