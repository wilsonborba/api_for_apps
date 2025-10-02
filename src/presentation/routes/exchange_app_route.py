from fastapi import APIRouter, Request, status, Depends



from ..handler.responses import MyResponseModel, MyResponse
from src.core.logs import debug


exchange_app_route = APIRouter(prefix='/v1')

@exchange_app_route.post("/exchange",
                    summary="Exchange Endpoint for Apps get authentication",
                    description="This endpoint attach the authentication to the app.",
                    response_model=MyResponseModel
                    )
async def exchange_app(request: Request):

    body = await request.json()


    data = {
        "method": request.method,
        "url": str(request.url),
        "headers": dict(request.headers),
        "client": request.client.host if request.client else None,
        "path_params": request.path_params,
        "query_params": dict(request.query_params),
        "cookies": request.cookies,
        "state": dict(request.state.__dict__),

        "body": body,
        

    }

    debug(f"Exchange App Data: {data}")
    

    # raise http
    return MyResponse(
        status_code=status.HTTP_200_OK,
        message="Exchange endpoint for apps.",
        data=data
    )
