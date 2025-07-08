from fastapi import FastAPI
from src.presentation.schema.apps_schema import schemas_from_apps
from src.presentation.schema.user_schema import schemas_from_user



app = FastAPI(root_path="/", root_path_in_servers=False, redirect_slashes=True)




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