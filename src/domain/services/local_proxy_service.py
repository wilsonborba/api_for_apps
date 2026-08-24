from typing import Optional
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
            self._parse_app_name(self.available_apps.certifications): 8103,
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

    async def forward_request(
        self,
        app: str,
        path: str,
        request: Request,
        response: Response
    ) -> StreamingResponse:
        """
        Forward the request to the target app while preserving the original
        percent-encoded path. Works with mount prefixes like '/apps/{app}/v1/...'.
        """

        # ---- 1) Build upstream URL using RAW (percent-encoded) path ----
        raw_path_bytes: Optional[bytes] = request.scope.get("raw_path")
        raw_path = (raw_path_bytes or request.url.path.encode("ascii")).decode("ascii")
        # Example raw_path: "/apps/certifications/v1/context/wikipedia/3I%2FATLAS"

        # We want the suffix after "/{app}/v1"
        anchor = f"/{app}/v1"
        idx = raw_path.find(anchor)
        if idx != -1:
            # keep what's after "/{app}/v1"
            raw_suffix = raw_path[idx + len(anchor):]   # still percent-encoded
        else:
            # Fallback: use FastAPI's decoded {path} (older behavior)
            raw_suffix = f"/{path}"                     # may be decoded

        # Normalize leading slash: exactly one leading slash
        if not raw_suffix.startswith("/"):
            raw_suffix = "/" + raw_suffix
        # Avoid accidental double slashes like "//context/..."
        while raw_suffix.startswith("//"):
            raw_suffix = raw_suffix[1:]

        # Base upstream URL + raw suffix; query is already percent-encoded
        target_url = self.get_full_url(app, raw_suffix)
        if request.url.query:
            target_url += f"?{request.url.query}"

        # ---- 2) Prepare body and headers ----
        body = await request.body()

        request_headers  = self.adjust_request_headers(dict(request.headers))
        response_headers = self.adjust_response_headers(dict(response.headers))
        headers = {**request_headers, **response_headers}

        if request.client:
            headers["x-forwarded-for"] = request.client.host
        headers["x-forwarded-proto"] = request.url.scheme
        headers["x-forwarded-host"]  = request.url.hostname or "localhost"

        # Do not leak admin key downstream
        if settings().API_ADMIN_KEY_NAME in headers:
            del headers[settings().API_ADMIN_KEY_NAME]

        # ---- 3) Send upstream request (streaming) ----
        timeout = httpx.Timeout(connect=2.0, read=3000, write=3000, pool=2.0)
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=False)

        try:
            req = client.build_request(
                method=request.method,
                url=target_url,                       # keeps %2F intact
                headers=headers,
                content=body if request.method != "HEAD" else None,
            )
            upstream = await client.send(req, stream=True)

            status_code = upstream.status_code
            media_type  = upstream.headers.get("content-type")

            # Strip hop-by-hop & Host from upstream response headers
            passthrough_headers = self.adjust_request_headers(dict(upstream.headers))

            async def iterator():
                try:
                    if request.method != "HEAD":
                        async for chunk in upstream.aiter_raw():
                            yield chunk
                finally:
                    await upstream.aclose()
                    await client.aclose()

            return StreamingResponse(
                iterator(),
                status_code=status_code,
                headers=passthrough_headers,
                media_type=media_type,
            )
        except Exception:
            await client.aclose()
            raise
