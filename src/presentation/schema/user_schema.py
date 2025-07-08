

from abc import abstractmethod
from dataclasses import dataclass
from fastapi import APIRouter
from src.presentation.routes.hello_user_route import hello_user_v1

@abstractmethod
@dataclass
class UserBaseSchema:
    """
    Base schema for user-related endpoints.
    """

    path_segment: str = "/user"

    @property
    @abstractmethod
    def routes(self):
        """
        Abstract property to define routes.
        """
        pass


class UserRoutes:

    hello_user_v1 = hello_user_v1


class UserSchema(UserBaseSchema):
    


    routes = UserRoutes()


schemas_from_user = UserSchema()