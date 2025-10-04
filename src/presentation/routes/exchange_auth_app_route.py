from fastapi import APIRouter, Request, Response, status

from src.core.utils import get_redis_adapter
from src.presentation.handler.exchange_auth_app_handler import (
    exchange_auth_sync,
    generate_new_nonce_sync,
    set_http_only_cookies_for_auth_sync,
    set_public_cookies_for_auth_sync,
)

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

    token = body.get("token") if body else None
    if not token:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Authentication is required",
            data=None,
        )

    adapter = get_redis_adapter(request)

    try:
        user_cookie = exchange_auth_sync(token)

        # ✅ Set cookies/headers on the SAME object you will return
        resp = await set_http_only_cookies_for_auth_sync(adapter, request, resp, user_cookie)
        resp = await set_public_cookies_for_auth_sync(adapter, request, resp, user_cookie)
        resp.headers[settings.NEXT_AUTH_NONCE_HEADER_KEY_NAME] = await generate_new_nonce_sync(adapter)
        
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
