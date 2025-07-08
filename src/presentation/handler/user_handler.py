



def get_all_user_info_from_db():
    """
    Get all user information.
    
    This endpoint returns all user information from the database.
    """
    from src.domain.services.user_service import UserService

    user_service = UserService()
    users = user_service.get_all_users()
    
    return users