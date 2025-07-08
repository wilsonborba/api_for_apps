from fastapi import APIRouter, status
from fastapi.params import Depends

from src.presentation.handler.user_handler import get_all_user_info_from_db
from ..handler.responses import MyResponse

from src.presentation.handler.auth import verify_api_key



user_v1 = APIRouter(prefix='/v1')

@user_v1.get(f"/all",
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