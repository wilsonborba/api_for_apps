
from abc import abstractmethod
from dataclasses import dataclass
from src.presentation.routes.hello_apps_route import hello_apps_v1
from src.presentation.routes.exchange_app_route import exchange_app_route


@abstractmethod
@dataclass
class AppsBaseSchema:
    """
    Base schema for apps.
    """

    path_segment: str = "/apps"
    tag: str = "Apps"

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
    exchange_app_route = exchange_app_route


class AvailableApps:

    api = "/api"



class AppsSchema(AppsBaseSchema):
    """
    Schema for managing apps.
    """


    routes = AppsRoutes()

    available_apps = AvailableApps()




schemas_from_apps = AppsSchema()