from fastapi import FastAPI
from src.presentation.routes.hello_word_route import hello_word


app = FastAPI(root_path="/", root_path_in_servers=False, redirect_slashes=True)


app.include_router(hello_word, prefix="/v1", tags=["Hello World"])