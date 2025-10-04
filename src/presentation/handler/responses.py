
from typing import Optional, Any
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ExchangeAuthError(Exception):
    pass

class AppNotFoundError(Exception):
    pass


class MyResponse(JSONResponse):
    def __init__(
        self,
        status_code: int,
        message: Optional[str] = None,
        data: Optional[Any] = None
    ):
        content = {
            "message": message,
            "data": data,
        }
        super().__init__(status_code=status_code, content=content)

class MyResponseModel(BaseModel):
    message: Optional[str] = None
    data: Optional[Any] = None
    # add `status: int` here if you want it in the body