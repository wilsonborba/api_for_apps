


from src.dal.remote.firebase_adapter import FirebaseAdapter
from src.dal.local.db_adapter import DBAdapter


class UserService:

    _table_name = "defaultdb_user"

    def __init__(self):
        self.db_adapter = DBAdapter()
        self.firebase_adapter = FirebaseAdapter()
    


    def create_user(self, user_data):
        return self.user_repository.create(user_data)

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

