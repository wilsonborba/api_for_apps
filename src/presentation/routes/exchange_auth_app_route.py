from fastapi import APIRouter, Request, Response, status

from src.core.utils import get_redis_adapter
from src.presentation.handler.exchange_auth_app_handler import (
    exchange_auth_sync,
    set_csrf_cookie_for_auth_sync,
    set_http_only_cookies_for_auth_sync,
)
from src.presentation.handler.auth_artifact_params import read_auth_exchange_token

from ..handler.responses import ExchangeAuthError, MyResponseModel, MyResponse
from src.core.logs import error
from src.core.settings import app_settings

settings = app_settings()

exchange_app_route_v1 = APIRouter(prefix="/v1")

@exchange_app_route_v1.post(
    "/exchange",
    summary="Exchange Endpoint for Apps get authentication",
    description="This endpoint attach the authentication to the app.",
    response_model=MyResponseModel,
)
async def exchange_app(request: Request, response: Response):

    # Build the response object you intend to RETURN
    resp = MyResponse(
        status_code=status.HTTP_200_OK,
        message="Success",
        data=None,
    )

    try:
        body = await request.json()
    except Exception as e:
        error(f"Error occurred while parsing request body : {e}")
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Bad request",
            data=None,
        )

    auth_exchange_token = read_auth_exchange_token(body)
    if not auth_exchange_token:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Authentication is required",
            data=None,
        )

    adapter = get_redis_adapter(request)
    # Existing Accredit clients omit app and therefore use the historical
    # certifications default. New app frontends must state their own app id.
    expected_app = (body.get("app") or settings.DEFAULT_EXCHANGE_APP).strip().lower()
    if expected_app not in settings.EXCHANGE_ALLOWED_APPS:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Unsupported application",
            data=None,
        )

    try:
        user_cookie = await exchange_auth_sync(
            adapter, auth_exchange_token, expected_app=expected_app
        )

        # ✅ Set cookies/headers on the SAME object you will return
        resp = await set_http_only_cookies_for_auth_sync(adapter, request, resp, user_cookie)
        resp = await set_csrf_cookie_for_auth_sync(request, resp, user_cookie)
        
    except ExchangeAuthError as e:
        error(f"ExchangeAuthError occurred while exchanging auth token : {e}")
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(e),
            data=None,
        )
    except Exception as e:
        error(f"Error occurred while exchanging auth token : {e}")
        return MyResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="Internal Server Error",
            data=None,
        )

    return resp
