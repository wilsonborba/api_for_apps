from fastapi import APIRouter, Request, Response, status, Depends

from src.core.utils import get_redis_adapter
from src.presentation.handler.exchange_auth_app_handler import exchange_auth_sync, save_on_redis_sync, set_http_only_cookies_for_auth_sync, set_public_cookies_for_auth_sync



from ..handler.responses import ExchangeAuthError, MyResponseModel, MyResponse
from src.core.logs import debug, error


exchange_app_route_v1 = APIRouter(prefix='/v1')

@exchange_app_route_v1.post("/exchange",
                    summary="Exchange Endpoint for Apps get authentication",
                    description="This endpoint attach the authentication to the app.",
                    response_model=MyResponseModel
                    )
async def exchange_app(request: Request, response: Response):

    try:

        body = await request.json()
    
    except Exception as e:
        error(f"Error occurred while parsing request body : {e}")
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Bad request",
            data=None
        )

    token = body.get("token") if body else None

    if not token:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Authentication is required",
            data=None
        )
    
    adapter = get_redis_adapter(request)
    
    try:
        user_cookie = exchange_auth_sync(token)


        response = set_http_only_cookies_for_auth_sync(response, user_cookie)
        response = set_public_cookies_for_auth_sync(response, user_cookie)

        is_saved = save_on_redis_sync(adapter, user_cookie)

        if not is_saved:
            return MyResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message="Failed to save session data",
                data=None
            )
        
    except ExchangeAuthError as e:
        error(f"ExchangeAuthError occurred while exchanging auth token : {e}")
        return MyResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=str(e), # return secure error message
            data=None
        )

    except Exception as e:
        error(f"Error occurred while exchanging auth token : {e}")
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Bad request",
            data=None
        )

    return MyResponse(
        status_code=status.HTTP_204_NO_CONTENT,
        message="Success",
        data=None
    )
