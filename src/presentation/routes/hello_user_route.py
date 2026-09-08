from fastapi import APIRouter, status
import pythonbible as bible



from src.presentation.handler.hello_word_handler import get_random_verse
from ..handler.responses import MyResponseModel, MyResponse

hello_user_v1 = APIRouter(prefix='/v1')

@hello_user_v1.get("/hello_user",
                    summary="Hello User Endpoint",
                    description="This endpoint returns a random verse from the Bible.",
                    response_model=MyResponseModel)
def hello_user():
    return MyResponse(
        status_code=status.HTTP_200_OK,
        message="Hello, World, this is an opened test endpoint.",
        data=get_random_verse(bible.Version.KING_JAMES),
    )



