from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile, status
from fastapi.params import Depends
from pydantic import BaseModel, Field

from src.core.logs import error
from src.core.settings import app_settings
from src.core.utils import get_redis_adapter
from src.dal.remote.fsm_media_adapter import FsmConfigurationError, FsmMediaAdapter, FsmStorageError
from src.domain.models.support_ticket_model import SUPPORT_TICKET_STATUSES
from src.domain.services.support_ticket_service import (
    SupportTicketNotFoundError,
    SupportTicketService,
)
from src.presentation.handler.auth import verify_auth
from src.presentation.handler.exchange_auth_app_handler import get_user_info_from_redis_sync
from src.presentation.handler.responses import MyResponse, MyResponseModel

settings = app_settings()
support_ticket_service = SupportTicketService()


def _fsm_adapter() -> FsmMediaAdapter:
    return FsmMediaAdapter(
        endpoint=settings.FSM_MEDIA_ENDPOINT, app=settings.FSM_APP_NAME, app_key=settings.FSM_APP_KEY
    )


# Per-file cap for a support attachment, well under FSM's own upload limit.
SUPPORT_ATTACHMENT_MAX_BYTES = 15 * 1024 * 1024

# Support is an application in its own right, even though it has no
# dedicated backend service of its own (unlike certifications, hippocampus,
# etc, which each have one behind the /apps/{app}/v1 proxy). It is mounted
# at /apps/support/v1, the same URL shape as every other app, with "support"
# itself filling the {app} slot, registered ahead of the generic proxy so
# this specific path is handled here instead of being forwarded there.
# One single set of endpoints serves every caller, regular users and admins
# alike: which app a ticket belongs to (source_app) is a normal request
# parameter, same as any other field, not something derived from the route.
# What the caller is allowed to see is decided inside each handler based on
# who they are (see _is_admin), never by a different URL.
support_v1 = APIRouter()


class CreateSupportTicketRequestModel(BaseModel):
    source_app: str = Field(min_length=2, max_length=64)
    subject: str | None = Field(default=None, max_length=200)
    body: str = Field(min_length=1, max_length=8000)
    attachment_reference: str | None = Field(default=None, max_length=2000)


class PostSupportMessageRequestModel(BaseModel):
    body: str = Field(min_length=1, max_length=8000)
    attachment_reference: str | None = Field(default=None, max_length=2000)


async def _require_identity(request: Request) -> str:
    """Support tickets are never anonymous: even a valid admin API key
    (see verify_auth) is not enough on its own, a real authenticated user
    session is always required, the same identity apps_route.py injects
    downstream as the x-uuid header."""
    session_id = request.cookies.get(settings.HTTP_ONLY_COOKIE_KEY_NAME)
    user_info = None
    if session_id:
        adapter = get_redis_adapter(request)
        user_info = await get_user_info_from_redis_sync(adapter=adapter, session_id=session_id)
    if not user_info or not user_info.get("user_uuid_id"):
        raise HTTPException(status_code=403, detail="Support tickets require an authenticated user session")
    return user_info["user_uuid_id"]


def _is_admin(user_id: str) -> bool:
    """Extension point for the admin authorization mechanism tracked in
    #18, not built yet. Every caller is treated as a regular, non-admin
    user until that lands: this always returns False today, on purpose,
    so behavior is unchanged until the real mechanism replaces this."""
    return False


@support_v1.post(
    "/attachments",
    summary="Upload a support ticket attachment",
    description=(
        "Uploads a file to FSM's media storage and returns its reference. "
        "Pass the returned attachment_reference when creating a ticket or "
        "posting a message; this endpoint never touches a ticket itself."
    ),
    response_model=MyResponseModel,
    status_code=status.HTTP_201_CREATED,
)
async def post_upload_attachment(
    request: Request,
    response: Response,
    file: UploadFile = File(...),
    _auth: bool = Depends(verify_auth),
):
    user_id = await _require_identity(request)
    body = await file.read()
    if len(body) > SUPPORT_ATTACHMENT_MAX_BYTES:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Attachment exceeds the maximum allowed size.",
            data=None,
        )
    try:
        key = await _fsm_adapter().upload(
            album=f"support-{user_id}",
            filename=file.filename or "attachment",
            body=body,
            content_type=file.content_type or "application/octet-stream",
        )
        return MyResponse(
            status_code=status.HTTP_201_CREATED,
            message="Attachment uploaded successfully.",
            data={"attachment_reference": key},
        )
    except FsmConfigurationError as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="Attachment storage is not configured.",
            data=None,
        )
    except FsmStorageError as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="Failed to upload the attachment.",
            data=None,
        )


@support_v1.post(
    "/tickets",
    summary="Create a support ticket",
    description="Opens a new cross-app support ticket with its first message.",
    response_model=MyResponseModel,
    status_code=status.HTTP_201_CREATED,
)
async def post_create_ticket(
    payload: CreateSupportTicketRequestModel,
    request: Request,
    response: Response,
    _auth: bool = Depends(verify_auth),
):
    user_id = await _require_identity(request)
    try:
        ticket = support_ticket_service.create_ticket(
            user_id=user_id,
            source_app=payload.source_app.strip().lower(),
            subject=payload.subject.strip() if payload.subject else None,
            body=payload.body.strip(),
            attachment_reference=payload.attachment_reference,
        )
        return MyResponse(
            status_code=status.HTTP_201_CREATED,
            message="Support ticket created successfully.",
            data=ticket,
        )
    except Exception as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to create the support ticket.",
            data=None,
        )


@support_v1.get(
    "/tickets",
    summary="List the caller's support tickets",
    description="Lists the authenticated caller's tickets (every user's, if the caller is an admin), optionally filtered by source_app and status.",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def get_list_tickets(
    request: Request,
    response: Response,
    source_app: str | None = Query(default=None, max_length=64),
    status_filter: str | None = Query(default=None, alias="status", max_length=32),
    _auth: bool = Depends(verify_auth),
):
    user_id = await _require_identity(request)
    if status_filter and status_filter not in SUPPORT_TICKET_STATUSES:
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=f"Invalid status filter. Expected one of {SUPPORT_TICKET_STATUSES}.",
            data=None,
        )
    try:
        tickets = support_ticket_service.list_tickets(
            user_id=user_id,
            source_app=source_app.strip().lower() if source_app else None,
            status=status_filter,
            is_admin=_is_admin(user_id),
        )
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Support tickets retrieved successfully.",
            data=tickets,
        )
    except Exception as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to retrieve support tickets.",
            data=None,
        )


@support_v1.get(
    "/tickets/{ticket_id}",
    summary="Get a support ticket with its full thread",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def get_ticket(
    ticket_id: str,
    request: Request,
    response: Response,
    _auth: bool = Depends(verify_auth),
):
    user_id = await _require_identity(request)
    try:
        ticket = support_ticket_service.get_ticket(
            ticket_id=ticket_id, user_id=user_id, is_admin=_is_admin(user_id)
        )
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Support ticket retrieved successfully.",
            data=ticket,
        )
    except SupportTicketNotFoundError:
        return MyResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Support ticket not found.",
            data=None,
        )
    except Exception as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to retrieve the support ticket.",
            data=None,
        )


@support_v1.post(
    "/tickets/{ticket_id}/messages",
    summary="Post a message onto a support ticket",
    description="Appends a message, with an optional attachment reference, to the ticket's thread.",
    response_model=MyResponseModel,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    ticket_id: str,
    payload: PostSupportMessageRequestModel,
    request: Request,
    response: Response,
    _auth: bool = Depends(verify_auth),
):
    user_id = await _require_identity(request)
    try:
        message = support_ticket_service.post_message(
            ticket_id=ticket_id,
            user_id=user_id,
            body=payload.body.strip(),
            attachment_reference=payload.attachment_reference,
            is_admin=_is_admin(user_id),
        )
        return MyResponse(
            status_code=status.HTTP_201_CREATED,
            message="Message posted successfully.",
            data=message,
        )
    except SupportTicketNotFoundError:
        return MyResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Support ticket not found.",
            data=None,
        )
    except Exception as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to post the message.",
            data=None,
        )


@support_v1.patch(
    "/tickets/{ticket_id}/read",
    summary="Mark every message on a ticket as read",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def patch_mark_ticket_read(
    ticket_id: str,
    request: Request,
    response: Response,
    _auth: bool = Depends(verify_auth),
):
    user_id = await _require_identity(request)
    try:
        changed = support_ticket_service.mark_ticket_read(
            ticket_id=ticket_id, user_id=user_id, is_admin=_is_admin(user_id)
        )
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Support ticket marked as read.",
            data={"messages_marked_read": changed},
        )
    except SupportTicketNotFoundError:
        return MyResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Support ticket not found.",
            data=None,
        )
    except Exception as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to mark the support ticket as read.",
            data=None,
        )


@support_v1.patch(
    "/tickets/{ticket_id}/messages/{message_id}/read",
    summary="Mark a single message as read",
    response_model=MyResponseModel,
    status_code=status.HTTP_200_OK,
)
async def patch_mark_message_read(
    ticket_id: str,
    message_id: str,
    request: Request,
    response: Response,
    _auth: bool = Depends(verify_auth),
):
    user_id = await _require_identity(request)
    try:
        found = support_ticket_service.mark_message_read(
            ticket_id=ticket_id, user_id=user_id, message_id=message_id, is_admin=_is_admin(user_id)
        )
        if not found:
            return MyResponse(
                status_code=status.HTTP_404_NOT_FOUND,
                message="Message not found on this support ticket.",
                data=None,
            )
        return MyResponse(
            status_code=status.HTTP_200_OK,
            message="Message marked as read.",
            data=None,
        )
    except SupportTicketNotFoundError:
        return MyResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            message="Support ticket not found.",
            data=None,
        )
    except Exception as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to mark the message as read.",
            data=None,
        )
