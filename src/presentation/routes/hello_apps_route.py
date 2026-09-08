from fastapi import APIRouter, status, Depends
import pythonbible as bible


from src.presentation.handler.auth import verify_auth
from src.presentation.handler.hello_word_handler import get_random_verse
from ..handler.responses import MyResponseModel, MyResponse

hello_apps_v1 = APIRouter(prefix='/v1')

@hello_apps_v1.get("/hello_apps", 
                    summary="Hello Apps Endpoint",
                    description="This endpoint returns a random verse from the Bible.",
                    response_model=MyResponseModel)
def hello_apps():
    return MyResponse(
        status_code=status.HTTP_200_OK,
        message="Hello, World, this is an opened test endpoint.",
        data=get_random_verse(bible.Version.KING_JAMES),
    )


# @hello_word.get("/tests/hello_world/closed", tags=["Hello World Closed"])
# def get_hello_word_closed(api_key_secret: str = Depends(verify_api_key)):
#     return MyResponse(
#         status=status.HTTP_200_OK,
#         message="Hello, World, this is a closed test endpoint.",
#         data=get_random_verse(bible.Version.KING_JAMES),
#     )
