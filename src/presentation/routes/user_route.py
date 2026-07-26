import asyncio
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.params import Depends
from pydantic import BaseModel

from src.domain.models.user_model import FirebaseUserModel
from src.presentation.handler.user_handler import get_all_user_info_from_db, get_fields_info_about_user, get_specific_user_info, modify_user_info, sign_up_user, log_in_user
from ..handler.responses import MyResponseModel, MyResponse
from src.core.logs import error, debug
from src.presentation.handler.auth import verify_auth
from src.presentation.handler.user_security_handler import (
    enforce_ip_rate,
    enforce_username_rate,   # now using email
    enforce_fail_lock,
    progressive_backoff_delay_ms,
)
from src.core.utils import get_redis_adapter
from src.core.settings import app_settings

settings = app_settings()


class SupabaseSessionRequest(BaseModel):
    access_token: str


user_info_v1 = APIRouter(prefix='/v1')
user_sync_v1 = APIRouter(prefix='/v1')

@user_info_v1.get(f"/all",
            summary="Get All User Info", 
            description="This endpoint returns all user information.",
            response_model=MyResponseModel,
            status_code=status.HTTP_200_OK)
def get_all_user_info( response: Response, api_key_secret: str = Depends(verify_auth), ):
    
    all_user_info = get_all_user_info_from_db()

    try:
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="All user information retrieved successfully.",
            data=all_user_info
        )
    except Exception as e:
        error(str(e))
        
        return MyResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to retrieve user information.",
            data=None
        )

@user_info_v1.get(f"/",
            summary="Get User Info", 
            description="This endpoint returns user information.",
            response_model=MyResponseModel,
            status_code=status.HTTP_200_OK)
async def get_user_info(response: Response, api_key_secret: str = Depends(verify_auth), request: Request = None):
    """
    Get user information.
    This endpoint returns user information.
    """
    cookies = request.cookies


    sid = cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)

    try:
        user_info = await get_specific_user_info(request=request, sid=sid)
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="User information retrieved successfully.",
            data=user_info
        )
    except Exception as e:
        error(str(e))

        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to retrieve user information.",
            data=None
        )

@user_info_v1.get(f"/fields",
            summary="Get User Info Fields", 
            description="This endpoint returns specific fields of user information.",
            response_model=MyResponseModel,
            status_code=status.HTTP_200_OK)
async def get_user_info_fields(response: Response, api_key_secret: str = Depends(verify_auth), request: Request = None):
    """
    Get specific fields of user information.
    This endpoint returns specific fields of user information.
    """

    try:
        user_fields = await get_fields_info_about_user()
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="User information fields retrieved successfully.",
            data=user_fields
        )
    
    except Exception as e:
        error(str(e))

        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to retrieve user information fields.",
            data=None
        )




@user_info_v1.patch(f"/",
                    summary="Update User Info",
                    description="This endpoint updates user information.",
                    response_model=MyResponseModel,
                    status_code=status.HTTP_200_OK)
async def update_user_info(response: Response, api_key_secret: str = Depends(verify_auth), request: Request = None):
    """
    Update user information.
    This endpoint updates user information.
    """
    try:
        # debug(f"Request Headers {request.headers}")
        # debug(f"Response Headers {response.headers}")
        # debug(f"Request Body {await request.body()}")

        # headers = request.headers
        cookies = request.cookies

        sid = cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)

        body = await request.json()

        first_name = body.get("first_name")
        last_name = body.get("last_name")
        phone_number = body.get("phone_number")



        user_modified = await modify_user_info(
            request=request, 
            sid=sid, 
            first_name=first_name, 
            last_name=last_name, 
            phone_number=phone_number
        )

        debug(f"Updated User Info: {user_modified}")

        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="User information updated successfully.",
            data=None
        )
    except Exception as e:
        error(str(e))
        
        return MyResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="Failed to update user information.",
            data=None
        )
       


@user_sync_v1.post(f"/sign-up",
             summary="Sign Up User", 
             description="This endpoint handles the creation of a new user in both the database and Firebase.",
             response_model=MyResponseModel,
             status_code=status.HTTP_201_CREATED,

             )
async def post_sign_up_user(response: Response, request: Request, raw_user_data: FirebaseUserModel):
    """
    Sign up a new user.
    This endpoint handles the creation of a new user in both the database and Firebase.

    """
    adapter = get_redis_adapter(request)

        # Basic validation (ensure we can key by email)
    if not getattr(raw_user_data, "email", None):
        raise HTTPException(status_code=400, detail="email is required")
    
    await enforce_ip_rate(adapter, request=request, action="signup", limits=((5, 60), (30, 3600)))
    await enforce_username_rate(adapter, action="signup", user_email=raw_user_data.email, limits=((3, 60), (10, 600)))

    delay_ms = await progressive_backoff_delay_ms(adapter, request=request, user_email=raw_user_data.email)
    await asyncio.sleep(delay_ms / 1000.0)


    try:
        debug(str(raw_user_data))
        return MyResponse(
            status_code=status.HTTP_201_CREATED,
            message="User signed up successfully.",
            data=sign_up_user(raw_user_data)
        )
    except Exception as e:
        error(str(e))
        
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="User sign-up failed. Please check the provided data.",
            data=None
        )

@user_sync_v1.patch(f"/log-in",
             summary="Log In User", 
             description="This endpoint handles user authentication and returns user data if successful.",
             response_model=MyResponseModel,
             status_code=status.HTTP_200_OK)
async def post_log_in_user(response: Response, request: Request, raw_user_data: FirebaseUserModel):
    """
    Log in a user.
    This endpoint handles user authentication and returns user data if successful.
    """
    adapter = get_redis_adapter(request)


    if not getattr(raw_user_data, "email", None):
        raise HTTPException(status_code=400, detail="email is required")

    # 1) Rate-limit by IP and by email
    await enforce_ip_rate(adapter, request=request, action="login", limits=((5, 60), (20, 3600)))
    await enforce_username_rate(adapter, action="login", user_email=raw_user_data.email, limits=((3, 60), (10, 600)))

    # 2) (Optional) backoff
    delay_ms = await progressive_backoff_delay_ms(adapter, request=request, user_email=raw_user_data.email)
    await asyncio.sleep(delay_ms / 1000.0)

    try:
        
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="User logged in successfully.",
            data=log_in_user(raw_user_data)
        )
    except Exception as e:

        error(str(e))
       
        return MyResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Authentication failed. Please check your credentials.",
            data=None
        )


@user_sync_v1.post(
    "/supabase-session",
    summary="Exchange Supabase session for auth exchange token",
    description="This endpoint validates a frontend Supabase access token and returns the platform auth exchange token.",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def post_supabase_session(
    response: Response,
    request: Request,
    body: SupabaseSessionRequest,
):
    if not body.access_token:
        raise HTTPException(status_code=400, detail="access_token is required")

    try:
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Supabase session accepted.",
            data=log_in_user_from_supabase(body.access_token),
        )
    except Exception as e:
        error(str(e))
        return MyResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Supabase authentication failed.",
            data=None,
        )
