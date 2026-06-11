"""
Регистрация всех роутеров обработчиков.
"""

from aiogram import Router

from handlers.start import router as start_router
from handlers.schedule import router as schedule_router
from handlers.extra import router as extra_router
from handlers.info import router as info_router
from handlers.admin import router as admin_router
from handlers.starosta import router as starosta_router


def setup_routers() -> Router:
    """Создать корневой роутер и подключить все обработчики."""
    root = Router()
    root.include_router(start_router)
    root.include_router(schedule_router)
    root.include_router(extra_router)
    root.include_router(info_router)
    root.include_router(admin_router)
    root.include_router(starosta_router)
    return root
