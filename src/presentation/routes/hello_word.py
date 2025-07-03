from fastapi import APIRouter, status

from ..handler.responses import MyResponse

hello_word = APIRouter()

@hello_word.get("/tests")
def get_tests():
    
    return MyResponse(
        status=status.HTTP_200_OK,
        message="Hello, World!",
        data="This is a test response"
    )

