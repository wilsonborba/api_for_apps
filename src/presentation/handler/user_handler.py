from fastapi import Request
from src.presentation.handler.exchange_auth_app_handler import get_user_info_from_redis_sync
from src.core.utils import get_redis_adapter
from src.domain.services.user_service import UserService

user_service = UserService()


async def modify_user_info(request: Request,  sid: str, first_name: str = None, last_name: str = None, phone_number: str = None):
    """
    Update user information.
    
    This endpoint updates user information based on the provided session ID and new data.
    """

    adapter = get_redis_adapter(request)

    user_info = await get_user_info_from_redis_sync(adapter=adapter, session_id=sid)
    # {
    #     'session_id': 'UFAOWP2XLrJQe4JU-uR1sr1_OgtheU91qQLqhehms_I', 
    #     'firebase_id': 'fB68zTp1JFaOHWbrTuHav3o03vk2', 
    #     'access_level': 1, 
    #     'user_id': 1, 
    #     'user_uuid_id': 'b7e96850-7be3-4d8e-8bb7-3f2716e29917', 
    #     'email': 'wilsonmatheuslimaborba@gmail.com', 
    #     'nonce': 'OJygrObablG-T3-3gV1Y4M91npaqoaaI'
    # }

    user_id = user_info.get("user_id")

    user_data = {
        "first_name": first_name,
        "last_name": last_name,
        "phone_number": phone_number
    }

    updated_user = user_service.update_user(
        user_id=user_id,
        user_data=user_data
    )

    return updated_user  # Return the updated user information


def get_all_user_info_from_db():
    """
    Get all user information.
    
    This endpoint returns all user information from the database.
    """

    users = user_service.get_all_users()
    
    return users


def sign_up_user(raw_user_data):
    """
    Sign up a new user.
    
    This endpoint handles the creation of a new user in both the database and Firebase.
    """

    sign_up_data = user_service.sign_up(raw_user_data)  # This will handle both DB and Firebase user creation

    return sign_up_data  # Return the result of the sign-up operation, which could be a success message or user data


def log_in_user(raw_user_data):
    """
    Log in a user.
    
    This endpoint handles user authentication and returns user data if successful.
    """

    login_data = user_service.log_in(raw_user_data)  # This will handle user authentication

    return login_data  # Return the result of the login operation, which could be user data or an error message
    