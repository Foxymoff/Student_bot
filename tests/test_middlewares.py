from aiogram.methods import EditMessageText, SendMessage

from middlewares import SilentByDefaultMiddleware


async def _run(method):
    """Прогнать метод через middleware, вернуть (метод, дошедший до отправки)."""
    seen = {}

    async def make_request(bot, m):
        seen["method"] = m
        return "sent"

    result = await SilentByDefaultMiddleware()(make_request, bot=None, method=method)
    return result, seen["method"]


async def test_ordinary_message_becomes_silent():
    """Рядовое сообщение без явного флага уходит без звука."""
    method = SendMessage(chat_id=1, text="hi")
    assert method.disable_notification is None

    result, sent = await _run(method)

    assert result == "sent"
    assert sent.disable_notification is True


async def test_explicit_sound_is_preserved():
    """Уведомление со звуком (disable_notification=False) не заглушается."""
    method = SendMessage(chat_id=1, text="alert", disable_notification=False)

    _, sent = await _run(method)

    assert sent.disable_notification is False


async def test_explicit_silent_is_preserved():
    """Явно беззвучное уведомление остаётся беззвучным."""
    method = SendMessage(chat_id=1, text="silent", disable_notification=True)

    _, sent = await _run(method)

    assert sent.disable_notification is True


async def test_method_without_notification_field_is_untouched():
    """Методы без disable_notification (например, edit) проходят без изменений."""
    method = EditMessageText(chat_id=1, message_id=2, text="edit")

    result, sent = await _run(method)

    assert result == "sent"
    assert sent is method
    assert "disable_notification" not in type(sent).model_fields


from unittest.mock import MagicMock  # noqa: E402

from middlewares import ThrottleMiddleware  # noqa: E402


async def test_throttle_drops_repeat_within_interval():
    mw = ThrottleMiddleware(min_interval=10.0)
    calls = []

    async def handler(event, data):
        calls.append(1)
        return "ok"

    ev = MagicMock()
    ev.from_user.id = 1

    assert await mw(handler, ev, {}) == "ok"
    # повтор сразу же — отброшен
    assert await mw(handler, ev, {}) is None
    assert len(calls) == 1


async def test_throttle_is_per_user_and_allows_after_interval():
    mw = ThrottleMiddleware(min_interval=0.0)
    seen = []

    async def handler(event, data):
        seen.append(event.from_user.id)
        return "ok"

    a = MagicMock()
    a.from_user.id = 1
    b = MagicMock()
    b.from_user.id = 2

    assert await mw(handler, a, {}) == "ok"
    assert await mw(handler, b, {}) == "ok"  # другой юзер не заблокирован
    assert await mw(handler, a, {}) == "ok"  # интервал 0 — снова можно
    assert seen == [1, 2, 1]
