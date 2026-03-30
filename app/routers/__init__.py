from .sensors import router as sensors_router
from .zones import router as zones_router
from .alerts import router as alerts_router
from .reports import router as reports_router
from .analytics import router as analytics_router
from .auth import router as auth_router
from .admin import router as admin_router

__all__ = [
    "sensors_router",
    "zones_router",
    "alerts_router",
    "reports_router",
    "analytics_router",
    "auth_router",
    "admin_router"
]