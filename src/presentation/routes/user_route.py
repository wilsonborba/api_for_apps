from fastapi import APIRouter, status
from fastapi.params import Depends

from src.domain.models.user_model import FirebaseUserModel
from src.presentation.handler.user_handler import get_all_user_info_from_db, sign_up_user, log_in_user
from ..handler.responses import MyResponse
from src.core.logs import error
from src.presentation.handler.auth import verify_api_key



user_info_v1 = APIRouter(prefix='/v1')
user_sync_v1 = APIRouter(prefix='/v1')

@user_info_v1.get(f"/all",
            summary="Get All User Info", tags=["User"],
            description="This endpoint returns all user information.",
            response_model=MyResponse,
            status_code=status.HTTP_200_OK)
def get_all_user_info(api_key_secret: str = Depends(verify_api_key)):
    
    all_user_info = get_all_user_info_from_db()

    return MyResponse(
        status=status.HTTP_200_OK,
        message="All user information retrieved successfully.",
        data=all_user_info
    )

@user_sync_v1.post(f"/sign-up",
             summary="Sign Up User", tags=["User"],
             description="This endpoint handles the creation of a new user in both the database and Firebase.",
             response_model=MyResponse,
             status_code=status.HTTP_201_CREATED,

             )
def post_sign_up_user(raw_user_data: FirebaseUserModel):
    """
    Sign up a new user.
    This endpoint handles the creation of a new user in both the database and Firebase.
    """
    try:

        return MyResponse(
            status=status.HTTP_201_CREATED,
            message="User signed up successfully.",
            data=sign_up_user(raw_user_data)
        )
    except Exception as e:
        error(str(e))
        return MyResponse(
            status=status.HTTP_400_BAD_REQUEST,
            message="User sign-up failed. Please check the provided data.",
            data=None
        )

@user_sync_v1.patch(f"/log-in",
             summary="Log In User", tags=["User"],
             description="This endpoint handles user authentication and returns user data if successful.",
             response_model=MyResponse,
             status_code=status.HTTP_200_OK)
def post_log_in_user(raw_user_data: FirebaseUserModel):
    """
    Log in a user.
    This endpoint handles user authentication and returns user data if successful.
    """
    try:
        return MyResponse(
            status=status.HTTP_200_OK,
            message="User logged in successfully.",
            data=log_in_user(raw_user_data)
        )
    except Exception as e:
        error(str(e))
        return MyResponse(
            status=status.HTTP_401_UNAUTHORIZED,
            message="Authentication failed. Please check your credentials.",
            data=None
        )
