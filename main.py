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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(
    schemas_from_apps.routes.hello_apps_v1, 
    prefix=f"{schemas_from_apps.path_segment}{schemas_from_apps.available_apps.api}"
)

app.include_router(
    schemas_from_user.routes.hello_user_v1, 
    prefix=f"{schemas_from_user.path_segment}"
)

app.include_router(
    schemas_from_user.routes.user_info_v1, 
    prefix=f"{schemas_from_user.path_segment}{schemas_from_user.segments_path.info}"
)

app.include_router(
    schemas_from_user.routes.user_sync_v1, 
    prefix=f"{schemas_from_user.path_segment}{schemas_from_user.segments_path.sync}"
)