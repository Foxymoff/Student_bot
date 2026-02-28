"""
Регистрация всех роутеров обработчиков.
"""

from aiogram import Router

from handlers.start import router as start_router
from handlers.schedule import router as schedule_router
from handlers.homework import router as homework_router
from handlers.deadlines import router as deadlines_router
from handlers.motivation import router as motivation_router


def setup_routers() -> Router:
    """Создать корневой роутер и подключить все обработчики."""
    root = Router()
    root.include_router(start_router)
    root.include_router(schedule_router)
    root.include_router(homework_router)
    root.include_router(deadlines_router)
    root.include_router(motivation_router)
    return root
