"""
Точка входа: запуск бота «Ассистент студента».
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN
from database import init_db
from handlers import setup_routers
from scheduler import setup_scheduler

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    """Инициализация и запуск бота."""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не задан! Проверь файл .env")
        return

    # Инициализация базы данных
    await init_db()

    # Создание бота и диспетчера
    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None),
    )
    dp = Dispatcher()

    # Подключение роутеров
    root_router = setup_routers()
    dp.include_router(root_router)

    # Запуск планировщика
    scheduler = setup_scheduler(bot)
    scheduler.start()

    logger.info("Бот запущен!")

    try:
        # Удаляем вебхук (если был) и запускаем polling
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    asyncio.run(main())
