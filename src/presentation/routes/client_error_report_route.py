from fastapi import APIRouter, Request, status
from pydantic import BaseModel, Field

from src.core.logs import error
from src.domain.services.client_error_report_service import ClientErrorReportService
from src.presentation.handler.responses import MyResponse, MyResponseModel

client_error_report_v1 = APIRouter(prefix="/api/v1")
client_error_report_service = ClientErrorReportService()


class ClientErrorReportRequestModel(BaseModel):
    app_name: str = Field(min_length=2, max_length=80)
    environment: str = Field(min_length=2, max_length=32)
    route: str | None = Field(default=None, max_length=300)
    error_title: str = Field(min_length=2, max_length=160)
    error_message: str = Field(min_length=2, max_length=4000)
    error_code: str | None = Field(default=None, max_length=80)
    details: dict | None = None


@client_error_report_v1.post(
    "/client-error-report",
    summary="Submit frontend error report",
    description="Accepts a sanitized frontend error report for later debugging.",
    response_model=MyResponseModel,
    status_code=status.HTTP_201_CREATED,
)
async def post_client_error_report(
    request: Request,
    raw_request: ClientErrorReportRequestModel,
):
    try:
        details_json = raw_request.details or {}
        if len(str(details_json)) > 12000:
            return MyResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="The error report details are too large.",
                data=None,
            )

        report_id = client_error_report_service.create_report(
            app_name=raw_request.app_name.strip(),
            environment=raw_request.environment.strip(),
            route=raw_request.route.strip() if raw_request.route else None,
            error_title=raw_request.error_title.strip(),
            error_message=raw_request.error_message.strip(),
            error_code=raw_request.error_code.strip() if raw_request.error_code else None,
            details=details_json,
            user_agent=request.headers.get("user-agent"),
        )
        return MyResponse(
            status_code=status.HTTP_201_CREATED,
            message="Error report submitted successfully.",
            data={"report_id": report_id},
        )
    except Exception as exc:
        error(str(exc))
        return MyResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="Failed to submit the error report.",
            data=None,
        )
