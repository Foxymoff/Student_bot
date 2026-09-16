"""
Middleware уровня сессии бота.
"""

from aiogram import Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.methods.base import Response, TelegramMethod, TelegramType


class SilentByDefaultMiddleware(BaseRequestMiddleware):
    """Рядовые сообщения бот отправляет без звука.

    Для исходящих методов, поддерживающих ``disable_notification``, проставляем
    беззвучную отправку, если звук не задан явно в самом вызове.

    Осознанные уведомления (ежедневное расписание в scheduler.py, алерты об
    изменениях от старосты в handlers/starosta.py) сами передают
    ``disable_notification`` по настройке пользователя — их значение не None,
    поэтому middleware их не трогает и звук у таких уведомлений сохраняется.
    """

    async def __call__(
        self,
        make_request: NextRequestMiddlewareType[TelegramType],
        bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        if (
            "disable_notification" in type(method).model_fields
            and method.disable_notification is None
        ):
            method.disable_notification = True
        return await make_request(bot, method)
