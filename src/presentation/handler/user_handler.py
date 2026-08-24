from fastapi import Request
from src.presentation.handler.exchange_auth_app_handler import get_user_info_from_redis_sync
from src.core.utils import get_redis_adapter
from src.domain.services.user_service import UserService
from src.core.logs import debug

user_service = UserService()


async def get_fields_info_about_user():
    """
    Get fields information about the user table.
    
    This endpoint returns the fields (column names and types) of the user table.
    """

    fields_info = user_service.fields()
    return fields_info  # Return the fields information


async def get_specific_user_info(request: Request, sid: str):
    """
    Get specific user information.
    
    This endpoint returns user information based on the provided session ID.
    """

    

    adapter = get_redis_adapter(request)


    user_info = await get_user_info_from_redis_sync(adapter=adapter, session_id=sid)
    
    debug(f"User Info: {user_info}")

    user_id = user_info.get("user_id")

    user_data = user_service.get_user_by_id(user_id=user_id)
    return user_data  # Return the user information


async def modify_user_info(request: Request,  sid: str, first_name: str = None, last_name: str = None, phone_number: str = None):
    """
    Update user information.
    
    This endpoint updates user information based on the provided session ID and new data.
    """

    adapter = get_redis_adapter(request)

    user_info = await get_user_info_from_redis_sync(adapter=adapter, session_id=sid)
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


def log_in_user_from_auth_session(access_token: str, app: str | None = None):
    return user_service.exchange_authenticated_session(access_token, app)


def sign_up_user_from_auth_session(access_token: str, app: str | None = None):
    return user_service.exchange_authenticated_session(access_token, app)


def sign_up_user_with_active_provider(
    email: str, password: str, display_name: str | None = None, app: str | None = None
):
    # Supabase may establish an immediate session depending on confirmation policy.
    token = user_service.sign_up_with_active_provider(email, password, display_name, app)
    return token


def log_in_user_with_active_provider(email: str, password: str, app: str | None = None):
    return user_service.log_in_with_active_provider(email, password, app)


def send_password_recovery_email(email: str):
    return user_service.send_password_recovery(email)


def update_password_with_recovery_token(access_token: str, new_password: str):
    return user_service.update_password_with_recovery_token(access_token, new_password)


def resend_signup_confirmation_email(email: str):
    return user_service.resend_signup_confirmation(email)
