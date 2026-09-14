from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.params import Depends
from pydantic import BaseModel

from src.core.logs import error
from src.core.settings import app_settings
from src.core.utils import get_redis_adapter
from src.domain.services.legal_acceptance_service import (
    InvalidLegalDocumentTypeError,
    LegalAcceptanceService,
)
from src.presentation.handler.auth import verify_auth
from src.presentation.handler.exchange_auth_app_handler import get_user_info_from_redis_sync
from src.presentation.handler.responses import MyResponse, MyResponseModel

settings = app_settings()
legal_acceptance_service = LegalAcceptanceService()

# Native router, mounted directly in main.py at "/legal/v1" (like /user/*),
# never registered as a proxied app behind apps_proxy_v1: this endpoint is
# api_for_apps's own shared acceptance state, not a forward to another
# microservice.
legal_v1 = APIRouter()


class AcceptLegalDocumentRequestModel(BaseModel):
    document_type: str


async def _require_user_uuid_id(request: Request) -> str:
    """Same session-derived identity pattern as support_route._require_identity:
    an admin API key alone (which is all verify_auth by itself requires) is
    never enough here, a real authenticated user session is always required."""
    session_id = request.cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)
    user_info = None
    if session_id:
        adapter = get_redis_adapter(request)
        user_info = await get_user_info_from_redis_sync(adapter=adapter, session_id=session_id)
    if not user_info or not user_info.get("user_uuid_id"):
        raise HTTPException(status_code=403, detail="Legal acceptance requires an authenticated user session")
    return user_info["user_uuid_id"]


@legal_v1.get(
    "/status",
    summary="Get the caller's legal acceptance status",
    description=(
        "Reports, for every configured legal document, whether the caller has "
        "accepted its current version."
    ),
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def get_legal_status(
    request: Request,
    response: Response,
    _auth: bool = Depends(verify_auth),
):
    user_uuid_id = await _require_user_uuid_id(request)
    try:
        data = legal_acceptance_service.get_status(user_uuid_id)
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Legal acceptance status retrieved",
            data=data,
        )
    except Exception as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to retrieve legal acceptance status.",
            data=None,
        )


@legal_v1.post(
    "/accept",
    summary="Accept a legal document",
    description=(
        "Records the caller's acceptance of the current version of a legal "
        "document (terms_of_service or privacy_policy)."
    ),
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def post_accept_legal_document(
    payload: AcceptLegalDocumentRequestModel,
    request: Request,
    response: Response,
    _auth: bool = Depends(verify_auth),
):
    user_uuid_id = await _require_user_uuid_id(request)
    try:
        data = legal_acceptance_service.accept(user_uuid_id, payload.document_type)
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Accepted",
            data=data,
        )
    except InvalidLegalDocumentTypeError as exc:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=str(exc),
            data=None,
        )
    except Exception as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to record legal document acceptance.",
            data=None,
        )
