"""
Middleware уровня сессии бота и диспетчера.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.client.session.middlewares.base import (
    BaseRequestMiddleware,
    NextRequestMiddlewareType,
)
from aiogram.methods.base import Response, TelegramMethod, TelegramType
from aiogram.types import CallbackQuery, Message, TelegramObject

from database import update_user_profile

logger = logging.getLogger(__name__)


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


class ProfileTrackingMiddleware(BaseMiddleware):
    """Держит в БД актуальные имя и @username пользователя — для поиска в админке.

    Обновление идёт только когда профиль реально изменился (кэш в памяти),
    чтобы не писать в базу на каждый тап. Для незарегистрированных пользователей
    запрос в БД ничего не меняет.
    """

    def __init__(self) -> None:
        self._seen: dict[int, tuple[str | None, str | None, str | None]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is not None and not getattr(user, "is_bot", False):
            snapshot = (user.username, user.first_name, user.last_name)
            if self._seen.get(user.id) != snapshot:
                try:
                    await update_user_profile(user.id, *snapshot)
                    self._seen[user.id] = snapshot
                except Exception as exc:
                    logger.debug("Не удалось обновить профиль %s: %s", user.id, exc)
        return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """Защита от спама кнопками (в т.ч. «Назад»).

    Обрабатывает не больше одного апдейта на пользователя одновременно и не чаще
    одного раза в ``min_interval`` секунд. Лишние нажатия отбрасываются: у
    callback гасим «часики», спам-сообщения удаляем. Это сериализует работу с
    ui_msg_ids и убирает гонки, из-за которых сбивалось бесшовное автоудаление
    сообщений, а заодно снимает нагрузку с сервера.
    """

    def __init__(self, min_interval: float = 0.4) -> None:
        self._min_interval = min_interval
        self._busy: set[int] = set()
        self._last: dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        uid = getattr(user, "id", None)
        if uid is None:
            return await handler(event, data)

        now = time.monotonic()
        if uid in self._busy or now - self._last.get(uid, 0.0) < self._min_interval:
            await self._reject(event)
            return None

        self._busy.add(uid)
        self._last[uid] = now
        try:
            return await handler(event, data)
        finally:
            self._busy.discard(uid)

    @staticmethod
    async def _reject(event: TelegramObject) -> None:
        """Мягко отклонить лишний апдейт."""
        try:
            if isinstance(event, CallbackQuery):
                await event.answer()  # погасить «часики» на кнопке
            elif isinstance(event, Message):
                await event.delete()  # убрать спам-сообщение из чата
        except Exception:
            pass
