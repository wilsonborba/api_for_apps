


from src.dal.local.db_adapter import DBAdapter


class UserService:

    _table_name = "defaultdb_user"

    def __init__(self):
        self.adapter = DBAdapter()
    


    def create_user(self, user_data):
        return self.user_repository.create(user_data)

    def get_user(self, user_id):
        return self.user_repository.get(user_id)

    def update_user(self, user_id, user_data):
        return self.user_repository.update(user_id, user_data)

    def delete_user(self, user_id):
        return self.user_repository.delete(user_id)
    
    def get_all_users(self):
        return self.adapter.read_all(self._table_name)