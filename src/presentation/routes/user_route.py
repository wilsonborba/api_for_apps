import asyncio
import secrets
import time
from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.params import Depends
from pydantic import BaseModel

from src.dal.remote.supabase_auth_adapter import SupabaseAuthAdapter
from src.presentation.handler.user_handler import (
    get_all_user_info_from_db,
    get_fields_info_about_user,
    get_specific_user_info,
    modify_user_info,
    log_in_user_from_auth_session,
    sign_up_user_from_auth_session,
    sign_up_user_with_active_provider,
    log_in_user_with_active_provider,
    send_password_recovery_email,
    update_password_with_recovery_token,
    resend_signup_confirmation_email,
)
from src.presentation.handler.exchange_auth_app_handler import register_auth_exchange_artifact
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
supabase_auth_adapter = SupabaseAuthAdapter()


class AuthRequestModel(BaseModel):
    uid: str | None = None
    email: str | None = None
    password: str | None = None
    display_name: str | None = None
    phone_number: str | None = None
    access_token: str | None = None
    app: str | None = None


class PasswordRecoveryRequestModel(BaseModel):
    email: str


class EmailConfirmationResendRequestModel(BaseModel):
    email: str


class PasswordResetRequestModel(BaseModel):
    access_token: str
    new_password: str


class OAuthStartRequestModel(BaseModel):
    provider: str
    intent: str | None = None


class OAuthCallbackRequestModel(BaseModel):
    code: str | None = None
    state: str | None = None
    error: str | None = None
    error_description: str | None = None


def _normalize_oauth_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "microsoft":
        return "azure"
    if normalized not in settings.OAUTH_PROVIDERS:
        raise ValueError("Unsupported OAuth provider")
    return normalized


def _oauth_scopes(provider: str) -> str | None:
    if provider == "azure":
        return "email"
    return None


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

       

@user_sync_v1.post(
    "/log-out",
    summary="Log out user",
    description="Revokes the opaque api_for_apps session and clears its cookies.",
    response_model=MyResponseModel,
)
async def post_log_out_user(request: Request, response: Response, _auth: str = Depends(verify_auth)):
    adapter = get_redis_adapter(request)
    sid = request.cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)
    if sid:
        await adapter.delete(adapter.k(settings.CACHE_AUTH_PREFIX, sid))
    resp = MyResponse(status_code=status.HTTP_200_OK, message="Logged out successfully.", data=None)
    resp.delete_cookie(settings.HTTP_ONLY_COOKIE_KEY_NAME, path="/", domain=settings.cookie_domain)
    resp.delete_cookie(settings.CSRF_COOKIE_KEY_NAME, path="/", domain=settings.cookie_domain)
    return resp


@user_sync_v1.post(f"/sign-up",
             summary="Sign Up User", 
             description="This endpoint creates a Supabase account and returns a short-lived app exchange artifact when a session exists.",
             response_model=MyResponseModel,
             status_code=status.HTTP_201_CREATED,

             )
async def post_sign_up_user(response: Response, request: Request, raw_user_data: AuthRequestModel):
    """
    Sign up a new user.
    This endpoint delegates identity creation to Supabase.

    """
    adapter = get_redis_adapter(request)

    if raw_user_data.access_token:
        await enforce_ip_rate(adapter, request=request, action="signup", limits=((5, 60), (30, 3600)))
        try:
            auth_exchange_token = sign_up_user_from_auth_session(
                raw_user_data.access_token, raw_user_data.app
            )
            await register_auth_exchange_artifact(adapter, auth_exchange_token)
            return MyResponse(
                status_code=status.HTTP_201_CREATED,
                message="User signed up successfully.",
                data=auth_exchange_token,
            )
        except Exception as e:
            error(str(e))
            return MyResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="User sign-up failed. Please check the provided data.",
                data=None,
            )

        # Basic validation (ensure we can key by email)
    if not raw_user_data.email:
        raise HTTPException(status_code=400, detail="email is required")
    
    await enforce_ip_rate(adapter, request=request, action="signup", limits=((5, 60), (30, 3600)))
    await enforce_username_rate(adapter, action="signup", user_email=raw_user_data.email, limits=((3, 60), (10, 600)))

    delay_ms = await progressive_backoff_delay_ms(adapter, request=request, user_email=raw_user_data.email)
    await asyncio.sleep(delay_ms / 1000.0)

    try:
        auth_exchange_token = sign_up_user_with_active_provider(
            raw_user_data.email, raw_user_data.password or "", raw_user_data.display_name, raw_user_data.app,
        )
        if auth_exchange_token is None:
            return MyResponse(
                status_code=status.HTTP_201_CREATED,
                message="User signed up successfully. Email confirmation is required before sign in can continue.",
                data=None,
            )
        await register_auth_exchange_artifact(adapter, auth_exchange_token)
        return MyResponse(
            status_code=status.HTTP_201_CREATED,
            message="User signed up successfully.",
            data=auth_exchange_token,
        )
    except Exception as e:
        error(str(e))
        
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e) or "User sign-up failed. Please check the provided data.",
            data=None
        )

@user_sync_v1.patch(f"/log-in",
             summary="Log In User", 
             description="This endpoint handles user authentication and returns user data if successful.",
             response_model=MyResponseModel,
             status_code=status.HTTP_200_OK)
async def post_log_in_user(response: Response, request: Request, raw_user_data: AuthRequestModel):
    """
    Log in a user.
    This endpoint handles user authentication and returns user data if successful.
    """
    adapter = get_redis_adapter(request)

    if raw_user_data.access_token:
        await enforce_ip_rate(adapter, request=request, action="login", limits=((5, 60), (20, 3600)))
        try:
            auth_exchange_token = log_in_user_from_auth_session(
                raw_user_data.access_token, raw_user_data.app
            )
            await register_auth_exchange_artifact(adapter, auth_exchange_token)
            return MyResponse(
                status_code=status.HTTP_200_OK,
                message="User logged in successfully.",
                data=auth_exchange_token,
            )
        except Exception as e:
            error(str(e))
            return MyResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=str(e) or "Authentication failed. Please check your credentials.",
                data=None,
            )


    if not raw_user_data.email:
        raise HTTPException(status_code=400, detail="email is required")

    # 1) Rate-limit by IP and by email
    await enforce_ip_rate(adapter, request=request, action="login", limits=((5, 60), (20, 3600)))
    await enforce_username_rate(adapter, action="login", user_email=raw_user_data.email, limits=((3, 60), (10, 600)))

    # 2) (Optional) backoff
    delay_ms = await progressive_backoff_delay_ms(adapter, request=request, user_email=raw_user_data.email)
    await asyncio.sleep(delay_ms / 1000.0)

    try:
        auth_exchange_token = log_in_user_with_active_provider(
            raw_user_data.email, raw_user_data.password or "", raw_user_data.app,
        )
        await register_auth_exchange_artifact(adapter, auth_exchange_token)
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="User logged in successfully.",
            data=auth_exchange_token,
        )
    except Exception as e:

        error(str(e))
       
        return MyResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=str(e) or "Authentication failed. Please check your credentials.",
            data=None
        )


@user_sync_v1.post(
    "/password-recovery",
    summary="Send Password Recovery Email",
    description="This endpoint sends a password recovery email using the active auth provider.",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def post_password_recovery(
    request: Request,
    raw_request: PasswordRecoveryRequestModel,
):
    adapter = get_redis_adapter(request)
    await enforce_ip_rate(adapter, request=request, action="password_recovery", limits=((5, 60), (20, 3600)))
    await enforce_username_rate(adapter, action="password_recovery", user_email=raw_request.email, limits=((3, 60), (10, 600)))

    try:
        send_password_recovery_email(raw_request.email)
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Password recovery email sent successfully.",
            data=None,
        )
    except Exception as e:
        error(str(e))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to send password recovery email.",
            data=None,
        )


@user_sync_v1.post(
    "/email-confirmation-resend",
    summary="Resend Signup Confirmation Email",
    description="This endpoint resends the signup confirmation email using the active auth provider.",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def post_email_confirmation_resend(
    request: Request,
    raw_request: EmailConfirmationResendRequestModel,
):
    adapter = get_redis_adapter(request)
    await enforce_ip_rate(adapter, request=request, action="email_confirmation_resend", limits=((5, 60), (20, 3600)))
    await enforce_username_rate(adapter, action="email_confirmation_resend", user_email=raw_request.email, limits=((3, 60), (10, 600)))

    try:
        resend_signup_confirmation_email(raw_request.email)
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Confirmation email sent successfully.",
            data=None,
        )
    except Exception as e:
        error(str(e))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to resend confirmation email.",
            data=None,
        )


@user_sync_v1.post(
    "/reset-password",
    summary="Reset Password",
    description="This endpoint updates a password using a recovery access token.",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def post_reset_password(raw_request: PasswordResetRequestModel):
    try:
        update_password_with_recovery_token(
            raw_request.access_token,
            raw_request.new_password,
        )
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Password updated successfully.",
            data=None,
        )
    except Exception as e:
        error(str(e))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to update password.",
            data=None,
        )


@user_sync_v1.post(
    "/oauth/start",
    summary="Start OAuth flow",
    description="This endpoint builds the backend-driven OAuth authorization URL.",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def post_oauth_start(request: Request, raw_request: OAuthStartRequestModel):
    adapter = get_redis_adapter(request)
    try:
        provider = _normalize_oauth_provider(raw_request.provider)
    except ValueError as e:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
            data=None,
        )

    state = secrets.token_urlsafe(32)
    code_verifier = supabase_auth_adapter.generate_pkce_verifier()
    code_challenge = supabase_auth_adapter.generate_pkce_challenge(code_verifier)
    scopes = _oauth_scopes(provider)

    redis_key = adapter.k(settings.OAUTH_STATE_PREFIX, state)
    await adapter.set(
        key=redis_key,
        value={
            "provider": provider,
            "intent": raw_request.intent or "login",
            "code_verifier": code_verifier,
            "created_at": int(time.time()),
        },
        ex=10 * 60,
    )

    authorization_url = supabase_auth_adapter.get_oauth_authorization_url(
        provider=provider,
        redirect_to=settings.auth_app_callback_url,
        state=state,
        code_challenge=code_challenge,
        scopes=scopes,
    )

    return MyResponse(
        status_code=status.HTTP_200_OK,
        message="OAuth authorization URL created successfully.",
        data={"authorization_url": authorization_url},
    )


@user_sync_v1.post(
    "/oauth/callback",
    summary="Complete OAuth callback",
    description="This endpoint exchanges the PKCE code for a provider session and returns the auth exchange token.",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def post_oauth_callback(request: Request, raw_request: OAuthCallbackRequestModel):
    if raw_request.error:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=raw_request.error_description or raw_request.error,
            data=None,
        )

    if not raw_request.code or not raw_request.state:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="OAuth callback is missing code or state.",
            data=None,
        )

    adapter = get_redis_adapter(request)
    redis_key = adapter.k(settings.OAUTH_STATE_PREFIX, raw_request.state)
    oauth_state = await adapter.get(redis_key)
    if not oauth_state:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="OAuth state is missing or expired.",
            data=None,
        )

    try:
        exchanged = supabase_auth_adapter.exchange_code_for_session(
            raw_request.code,
            oauth_state["code_verifier"],
        )
        access_token = ((exchanged.get("session") or {}).get("access_token"))
        if not access_token:
            raise ValueError("The auth provider did not return an authenticated session")

        auth_exchange_token = log_in_user_from_auth_session(access_token)
        await register_auth_exchange_artifact(adapter, auth_exchange_token)
        await adapter.delete(redis_key)
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="OAuth callback completed successfully.",
            data=auth_exchange_token,
        )
    except Exception as e:
        error(str(e))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to complete the OAuth callback.",
            data=None,
        )
