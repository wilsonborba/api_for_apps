
from abc import abstractmethod
from dataclasses import dataclass
from src.presentation.routes.hello_apps_route import hello_apps_v1


@abstractmethod
@dataclass
class AppsBaseSchema:
    """
    Base schema for apps.
    """

    path_segment: str = "/apps"

    @property
    @abstractmethod
    def routes(self):
        """
        Abstract property to define routes.
        """
        pass

    @property
    @abstractmethod
    def available_apps(self):
        """
        Abstract property to define available apps.
        """
        pass




class AppsRoutes:

    hello_apps_v1 = hello_apps_v1


class AvailableApps:

    api = "/api"


class AppsSchema(AppsBaseSchema):
    """
    Schema for managing apps.
    """


    routes = AppsRoutes()

    available_apps = AvailableApps()




schemas_from_apps = AppsSchema()