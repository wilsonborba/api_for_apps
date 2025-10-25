from fastapi import Request, Response
from src.presentation.handler.responses import AppNotFoundError
from starlette.responses import StreamingResponse
import httpx
import asyncio
from src.core.settings import app_settings as settings


class LocalProxyService:
    
    def __init__(self):
        self.available_apps = settings().available_apps
        self.host = "localhost"  # or any other host you want to use


    def get_port(self, app_name: str) -> int:
        app_ports = {
            self._parse_app_name(self.available_apps.certifications): 8001,
        }
        if app_name not in app_ports:
            raise AppNotFoundError(f"App '{app_name}' not found.")
        return app_ports.get(app_name)

    def _parse_app_name(self, app: str) -> str:
        return app.strip().lower().replace("/", "")

    def get_full_url(self, app: str, path: str) -> str:
        app_name = self._parse_app_name(app)
        port = self.get_port(app_name)
        return f"http://{self.host}:{port}{path}"

    def adjust_request_headers(self, headers: dict) -> dict:
        hop_by_hop_headers = [
            "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
            "te", "trailers", "transfer-encoding", "upgrade"
        ]
        return {k: v for k, v in headers.items() if k.lower() not in hop_by_hop_headers and k.lower() != "host"}
    
    def adjust_response_headers(self, headers: dict) -> dict:
        hop_by_hop_headers = [
            "x-uuid", "x-test"
        ]
        return {k: v for k, v in headers.items() if k.lower()  in hop_by_hop_headers and k.lower() != "host"}

    async def _retry_request(self, client: httpx.AsyncClient, **kwargs) -> httpx.Response:
        for attempt in range(3):
            try:
                return await client.request(**kwargs)
            except (httpx.ConnectTimeout, httpx.ReadTimeout):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.2 * (attempt + 1))
        raise RuntimeError("retry logic fell through")

    async def forward_request(self, app: str, path: str, request: Request, response: Response) -> StreamingResponse:
        target_url = self.get_full_url(app, path)
        if request.url.query:
            target_url += f"?{request.url.query}"

        # for big uploads, you can stream the request too; keeping simple here:
        body = await request.body()
        request_headers = self.adjust_request_headers(dict(request.headers))
        response_headers = self.adjust_response_headers(dict(response.headers))
        headers = {**request_headers, **response_headers}

        # add forwarded headers
        if request.client:
            headers["x-forwarded-for"] = request.client.host
        headers["x-forwarded-proto"] = request.url.scheme
        headers["x-forwarded-host"]  = request.url.hostname or "localhost"

        if settings().API_ADMIN_KEY_NAME in headers:
            del headers[settings().API_ADMIN_KEY_NAME]  # remove admin key if any

        timeout = httpx.Timeout(connect=2.0, read=360, write=30.0, pool=2.0)
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)

        async def iterator():
            try:
                async with client.stream(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    content=body,
                ) as r:
                    # propagate response headers + status out of the context
                    nonlocal upstream_status, upstream_headers, upstream_media_type
                    upstream_status = r.status_code
                    upstream_headers = self.adjust_request_headers(dict(r.headers))
                    upstream_media_type = r.headers.get("content-type")

                    async for chunk in r.aiter_raw():
                        yield chunk
            finally:
                await client.aclose()

        upstream_status = 200
        upstream_headers = {}
        upstream_media_type = None

        return StreamingResponse(
            iterator(),
            status_code=upstream_status,
            headers=upstream_headers,
            media_type=upstream_media_type,
        )