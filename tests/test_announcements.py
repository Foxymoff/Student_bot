"""Сводка обновления: беззвучно, «Скрыть», автоудаление через 24 ч, без дублей."""

from html.parser import HTMLParser
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)

import announcements
from handlers import admin
from keyboards import alert_delete_kb


@pytest.fixture
def storage(monkeypatch):
    """Подмена БД: список получателей, отметки об отправке, записи на автоудаление."""
    state = {"users": [1, 2, 3], "marked": [], "pending": [], "sleeps": []}

    async def get_users_without_announcement(announcement_id):
        return [{"user_id": uid} for uid in state["users"] if uid not in state["marked"]]

    async def mark_announcement_sent(user_id, announcement_id):
        assert announcement_id == announcements.ANNOUNCEMENT_ID
        state["marked"].append(user_id)

    async def add_pending_alert(user_id, message_id):
        state["pending"].append((user_id, message_id))

    async def sleep(seconds):
        state["sleeps"].append(seconds)

    monkeypatch.setattr(
        announcements, "get_users_without_announcement", get_users_without_announcement
    )
    monkeypatch.setattr(announcements, "mark_announcement_sent", mark_announcement_sent)
    monkeypatch.setattr(announcements, "add_pending_alert", add_pending_alert)
    monkeypatch.setattr(announcements.asyncio, "sleep", sleep)
    return state


def _bot(side_effects=None) -> MagicMock:
    bot = MagicMock()
    counter = iter(range(100, 200))

    async def send_message(**kwargs):
        effect = (side_effects or {}).get(kwargs["chat_id"])
        if effect:
            error = effect.pop(0) if isinstance(effect, list) else effect
            if error is not None:
                raise error
        return MagicMock(message_id=next(counter))

    bot.send_message = AsyncMock(side_effect=send_message)
    return bot


async def test_broadcast_is_silent_with_hide_button_and_autodelete(storage):
    bot = _bot()

    assert await announcements.broadcast_announcement(bot) == (3, 0)

    for call in bot.send_message.await_args_list:
        assert call.kwargs["disable_notification"] is True
        assert call.kwargs["reply_markup"] == alert_delete_kb()  # «Скрыть» (alert:delete)
        assert call.kwargs["parse_mode"] == "HTML"
    assert storage["pending"] == [(1, 100), (2, 101), (3, 102)]  # автоудаление через 24 ч
    assert storage["marked"] == [1, 2, 3]


async def test_second_broadcast_sends_nothing(storage):
    bot = _bot()
    await announcements.broadcast_announcement(bot)

    assert await announcements.broadcast_announcement(bot) == (0, 0)
    assert bot.send_message.await_count == 3


async def test_blocked_users_are_skipped_for_good(storage):
    blocked = TelegramForbiddenError(method=MagicMock(), message="bot was blocked by the user")
    gone = TelegramBadRequest(method=MagicMock(), message="chat not found")
    bot = _bot({2: blocked, 3: gone})

    assert await announcements.broadcast_announcement(bot) == (1, 2)
    assert storage["marked"] == [1, 2, 3]  # повторять бессмысленно
    assert storage["pending"] == [(1, 100)]


async def test_flood_limit_waits_and_retries(storage):
    flood = TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=7)
    bot = _bot({2: [flood, None]})

    assert await announcements.broadcast_announcement(bot) == (3, 0)
    assert 7 in storage["sleeps"]


async def test_network_error_is_retried_next_time(storage):
    bot = _bot({2: TelegramNetworkError(method=MagicMock(), message="timeout")})

    assert await announcements.broadcast_announcement(bot) == (2, 1)
    assert 2 not in storage["marked"]  # догонит следующая рассылка


def test_announcement_text_is_simple_html():
    tags: list[str] = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append(tag)

    text = announcements.announcement_text()
    Parser().feed(text)

    assert set(tags) <= {"b"}
    assert "/links" in text and "/classic" in text
    assert len(text) < 4096


def _admin_message(role: str) -> MagicMock:
    message = MagicMock()
    message.from_user.id = 9
    message.chat.id = 9
    message.delete = AsyncMock()
    message.answer = AsyncMock()
    return message


async def test_announce_command_is_admin_only(monkeypatch):
    async def get_user(user_id):
        return {"user_id": user_id, "role": "student"}

    sent = AsyncMock()
    monkeypatch.setattr(admin, "get_user", get_user)
    monkeypatch.setattr(admin, "send_announcement", sent)
    message = _admin_message("student")

    await admin.cmd_announce(message, MagicMock())

    sent.assert_not_awaited()
    assert "Нет доступа" in message.answer.await_args.args[0]


async def test_announce_command_previews_and_asks(monkeypatch):
    async def get_user(user_id):
        return {"user_id": user_id, "role": "admin"}

    async def pending(announcement_id):
        return [{"user_id": 1}, {"user_id": 2}]

    sent = AsyncMock()
    monkeypatch.setattr(admin, "get_user", get_user)
    monkeypatch.setattr(admin, "send_announcement", sent)
    monkeypatch.setattr(admin, "get_users_without_announcement", pending)
    message = _admin_message("admin")

    await admin.cmd_announce(message, MagicMock())

    sent.assert_awaited_once_with(message.bot, 9)  # предпросмотр себе
    kb = message.answer.await_args.kwargs["reply_markup"]
    assert [b.callback_data for b in kb.inline_keyboard[0]] == ["announce:send", "announce:cancel"]
    assert kb.inline_keyboard[0][0].text == "📣 Разослать (2)"


async def test_announce_send_reports_result(monkeypatch):
    async def get_user(user_id):
        return {"user_id": user_id, "role": "admin"}

    async def broadcast(bot):
        return 120, 8

    monkeypatch.setattr(admin, "get_user", get_user)
    monkeypatch.setattr(admin, "broadcast_announcement", broadcast)
    callback = MagicMock()
    callback.from_user.id = 9
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()

    await admin.on_announce_send(callback)

    result = callback.message.edit_text.await_args.args[0]
    assert "отправлено: 120" in result and "Не доставлено: 8" in result
