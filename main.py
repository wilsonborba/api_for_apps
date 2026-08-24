from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

from src.dal.local.redis_adapter import RedisAdapter
from src.presentation.schema.apps_schema import schemas_from_apps
from src.presentation.schema.user_schema import schemas_from_user
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

app = FastAPI(
    lifespan=lifespan,
    title="API for Asodya Apps", 
    description="Backend API for mobile and web applications from Asodya Co.",
    root_path="/", 
    root_path_in_servers=False, 
    redirect_slashes=True
    )


app.add_middleware(
    CORSMiddleware,
    #allow_origins=["*"],
    allow_origins=[
    # Localhost (Flutter web / local tools)
    "http://localhost:8100",
    "http://127.0.0.1:8100",
    "http://localhost:8102",
    "http://127.0.0.1:8102",
    "http://192.168.1.103:8100",
    "http://192.168.1.103:8102",

    # Local network / hotspot IPs (example ports — adjust if needed)
    "http://172.20.10.4:8100",
    "http://172.20.10.4:8102",
    "http://100.93.16.79:8100",
    "http://100.93.16.79:8102",
    "http://172.17.0.1:8100",
    "http://172.17.0.1:8102",

    # Auth domain
    "https://auth.asodya.com",
    "https://certifications.asodya.com",
    ],

    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=[
        "Content-Type",
        "X-CSRF-Token",
    ],
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
    schemas_from_apps.routes.client_error_report_v1,
    prefix=f"{schemas_from_apps.path_segment}",
    tags=[schemas_from_apps.tag],
)

app.include_router(
    schemas_from_apps.routes.apps_proxy_v1,
    prefix=f"{schemas_from_apps.path_segment}",
    tags=[schemas_from_apps.tag]
)
