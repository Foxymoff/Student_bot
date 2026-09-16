"""
Точка входа: запуск бота «Ассистент студента».
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand, MenuButtonCommands

from config import BOT_TOKEN, FSM_DB_PATH
from database import init_db
from handlers import setup_routers
from middlewares import (
    ProfileTrackingMiddleware,
    SilentByDefaultMiddleware,
    ThrottleMiddleware,
)
from scheduler import setup_scheduler, warm_profiles
from storage import SQLiteStorage

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
    # Рядовые сообщения (ответы на кнопки, навигация по меню) — без звука.
    # Звук остаётся только у уведомлений, которые явно задают disable_notification
    # по настройке пользователя (ежедневное расписание, алерты старосты).
    bot.session.middleware(SilentByDefaultMiddleware())
    # Персистентное FSM-хранилище: состояние (ui_msg_ids, навигация, флоу)
    # переживает рестарт контейнера.
    dp = Dispatcher(storage=SQLiteStorage(FSM_DB_PATH))

    # Троттлинг спама кнопок — внешний слой, чтобы отбрасывать лишнее до всего
    # остального (сериализует работу с ui_msg_ids, снимает нагрузку).
    throttle = ThrottleMiddleware()
    dp.message.outer_middleware(throttle)
    dp.callback_query.outer_middleware(throttle)

    # Держим в БД актуальные имя/@username для поиска в админке.
    profile_tracking = ProfileTrackingMiddleware()
    dp.message.outer_middleware(profile_tracking)
    dp.callback_query.outer_middleware(profile_tracking)

    # Подключение роутеров
    root_router = setup_routers()
    dp.include_router(root_router)

    # Запуск планировщика
    scheduler = setup_scheduler(bot)
    scheduler.start()

    # Разовый прогрев профилей (имя/@username) для поиска в админке — в фоне,
    # чтобы не задерживать запуск polling.
    asyncio.create_task(warm_profiles(bot))

    # Меню команд не должно блокировать запуск polling, если Telegram API отвечает долго.
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Главное меню"),
                BotCommand(command="profile", description="Учебный профиль"),
                BotCommand(command="groups", description="Расписание другой группы"),
                BotCommand(command="settings", description="Настройки"),
                BotCommand(command="help", description="Помощь"),
            ],
            request_timeout=60,
        )
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands(), request_timeout=60)
    except Exception as exc:
        logger.warning("Не удалось установить меню команд бота: %s", exc)

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
