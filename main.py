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
    allow_origins=["http://localhost:1165", "http://127.0.0.1:1165", "http://localhost:7000", "http://127.0.0.1:7000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=[
        "Content-Type",
        # your custom request headers:
        "A-A-N",     # settings.ACTUAL_AUTH_NONCE_HEADER_KEY_NAME
        "T-A-N",     # settings.TEMPORARY_AUTH_NONCE_HEADER_KEY_NAME
    ],
    expose_headers=[
        # headers you want the browser to be able to read:
        "n-a-n",     # settings.NEXT_AUTH_NONCE_HEADER_KEY_NAME
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
    schemas_from_apps.routes.apps_proxy_v1,
    prefix=f"{schemas_from_apps.path_segment}",
    tags=[schemas_from_apps.tag]
)
