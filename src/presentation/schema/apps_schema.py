
from abc import abstractmethod
from dataclasses import dataclass
from src.core.settings import app_settings
from src.presentation.routes.hello_apps_route import hello_apps_v1
from src.presentation.routes.exchange_auth_app_route import exchange_app_route_v1
from src.presentation.routes.apps_route import apps_proxy_v1
from src.presentation.routes.client_error_report_route import client_error_report_v1

settings = app_settings()

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
    exchange_app_route_v1 = exchange_app_route_v1
    apps_proxy_v1 = apps_proxy_v1
    client_error_report_v1 = client_error_report_v1






class AppsSchema(AppsBaseSchema):
    """
    Schema for managing apps.
    """


    routes = AppsRoutes()

    available_apps = settings.available_apps




schemas_from_apps = AppsSchema()
