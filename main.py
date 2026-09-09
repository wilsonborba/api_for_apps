from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

from src.dal.local.redis_adapter import RedisAdapter
from src.presentation.schema.apps_schema import schemas_from_apps
from src.presentation.schema.user_schema import schemas_from_user
from src.presentation.routes.waitlist_route import waitlist_router
from src.presentation.routes.support_route import support_v1
from src.presentation.routes.telemetry_route import telemetry_router
from src.core.settings import app_settings


settings = app_settings()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    adapter = RedisAdapter(settings.REDIS_URL, namespace=settings.REDIS_NAMESPACE)
    await adapter.connect()
    app.state.redis = adapter

    yield  # <---- aqui a app roda normalmente

    # Shutdown
    await adapter.close()

from fastapi.responses import HTMLResponse
from scalar_fastapi import get_scalar_api_reference, Layout, Theme

app = FastAPI(
    lifespan=lifespan,
    title="Asodya Apps Gateway API", 
    description="Backend API Gateway for mobile and web applications across the Asodya ecosystem.",
    root_path="/", 
    root_path_in_servers=False, 
    redirect_slashes=True,
    docs_url=None,
    redoc_url=None,
)


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
@app.get("/scalar", response_class=HTMLResponse, include_in_schema=False)
async def scalar_docs():
    return get_scalar_api_reference(
        openapi_url="/openapi.json",
        title="Asodya Apps API Gateway Reference",
        theme=Theme.PURPLE,
        layout=Layout.MODERN,
        hide_dark_mode_toggle=False,
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Localhost (Flutter web / local tools)
        "http://localhost:8100",
        "http://127.0.0.1:8100",
        "http://localhost:8102",
        "http://127.0.0.1:8102",

        # Auth & Certifications domain
        "https://auth.asodya.com",
        "https://certifications.asodya.com",
        "https://cortex.asodya.com",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|172\.\d+\.\d+\.\d+|100\.\d+\.\d+\.\d+)(:\d+)?",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["*"],
)


app.include_router(
    schemas_from_apps.routes.hello_apps_v1, 
    prefix=f"{schemas_from_apps.path_segment}{schemas_from_apps.available_apps.api}",
    tags=[schemas_from_apps.tag]
)

app.include_router(
    schemas_from_user.routes.hello_user_v1, 
    prefix=f"{schemas_from_user.path_segment}",
    tags=[schemas_from_user.tag]
)

app.include_router(
    schemas_from_user.routes.user_info_v1, 
    prefix=f"{schemas_from_user.path_segment}{schemas_from_user.segments_path.info}",
    tags=[schemas_from_user.tag]
)

app.include_router(
    schemas_from_user.routes.user_sync_v1, 
    prefix=f"{schemas_from_user.path_segment}{schemas_from_user.segments_path.sync}",
    tags=[schemas_from_user.tag]
)

app.include_router(
    schemas_from_apps.routes.exchange_app_route_v1, 
    prefix=f"{schemas_from_apps.path_segment}{schemas_from_apps.available_apps.api}",
    tags=[schemas_from_apps.tag]
)

app.include_router(
    telemetry_router,
    prefix=f"{schemas_from_apps.path_segment}{schemas_from_apps.available_apps.api}",
    tags=["telemetry"],
    include_in_schema=False,
)

app.include_router(
    waitlist_router,
    tags=["waitlist"],
    include_in_schema=False,
)

app.include_router(
    support_v1,
    prefix=f"{schemas_from_apps.path_segment}/support/v1",
    tags=["support"],
    include_in_schema=False,
)

app.include_router(
    schemas_from_apps.routes.apps_proxy_v1,
    prefix=f"{schemas_from_apps.path_segment}",
    tags=[schemas_from_apps.tag]
)
