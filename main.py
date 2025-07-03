from fastapi import FastAPI

app = FastAPI()

from src.presentation.routes.hello_word import hello_word

app.include_router(hello_word, prefix="/v1", tags=["Hello World"])