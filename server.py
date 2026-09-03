from api.main import create_app
from application.container import ApplicationContainer


container = ApplicationContainer.from_environment()

app = create_app(container=container)

__all__ = ["app"]