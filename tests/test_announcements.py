"""Рассылка админа: своё сообщение или готовая сводка, без звука, «Скрыть», 24 часа."""

from html.parser import HTMLParser
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import announcements
from announcements import BroadcastAborted, BroadcastContent
from handlers import admin
from keyboards import alert_delete_kb

COPY = BroadcastContent(from_chat_id=9, message_id=555)
TEXT = BroadcastContent(text="<b>важно</b>")


@pytest.fixture
def storage(monkeypatch):
    """Подмена БД: получатели, отметки об отправке, записи на автоудаление."""
    state = {"users": [1, 2, 3, 9], "marked": [], "pending": [], "sleeps": []}

    async def get_users_without_announcement(broadcast_id):
        done = {uid for uid, bid in state["marked"] if bid == broadcast_id}
        return [{"user_id": uid} for uid in state["users"] if uid not in done]

    async def mark_announcement_sent(user_id, broadcast_id):
        state["marked"].append((user_id, broadcast_id))

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


def _bot(errors=None) -> MagicMock:
    """Бот, у которого send_message/copy_message падают для заданных chat_id."""
    bot = MagicMock()
    counter = iter(range(100, 200))

    async def deliver(**kwargs):
        effect = (errors or {}).get(kwargs["chat_id"])
        if isinstance(effect, list):
            effect = effect.pop(0) if effect else None
        if effect is not None:
            raise effect
        return MagicMock(message_id=next(counter))

    bot.send_message = AsyncMock(side_effect=deliver)
    bot.copy_message = AsyncMock(side_effect=deliver)
    return bot


def _marked(storage, broadcast_id="b1") -> list[int]:
    return [uid for uid, bid in storage["marked"] if bid == broadcast_id]


# ── Доставка одному пользователю ──────────────────────────


async def test_copy_is_silent_with_hide_button_and_autodelete(storage):
    bot = _bot()

    await announcements.send_broadcast(bot, 1, COPY)

    kwargs = bot.copy_message.await_args.kwargs
    assert (kwargs["from_chat_id"], kwargs["message_id"]) == (9, 555)
    assert kwargs["disable_notification"] is True
    assert kwargs["reply_markup"] == alert_delete_kb()  # «Скрыть» (alert:delete)
    assert storage["pending"] == [(1, 100)]  # автоудаление через 24 часа


async def test_text_is_sent_as_html(storage):
    bot = _bot()

    await announcements.send_broadcast(bot, 1, TEXT)

    kwargs = bot.send_message.await_args.kwargs
    assert kwargs["text"] == "<b>важно</b>" and kwargs["parse_mode"] == "HTML"
    assert kwargs["disable_notification"] is True
    bot.copy_message.assert_not_awaited()


def test_content_survives_fsm_roundtrip():
    assert BroadcastContent.from_data(COPY.to_data()) == COPY
    assert BroadcastContent.from_data(TEXT.to_data()) == TEXT


# ── Рассылка всем ─────────────────────────────────────────


async def test_broadcast_skips_author_and_marks(storage):
    bot = _bot()

    assert await announcements.broadcast(bot, COPY, "b1", exclude={9}) == (3, 0)
    assert [c.kwargs["chat_id"] for c in bot.copy_message.await_args_list] == [1, 2, 3]
    assert _marked(storage) == [1, 2, 3]


async def test_second_broadcast_sends_nothing(storage):
    bot = _bot()
    await announcements.broadcast(bot, COPY, "b1", exclude={9})

    assert await announcements.broadcast(bot, COPY, "b1", exclude={9}) == (0, 0)
    # А новая рассылка — снова всем.
    assert await announcements.broadcast(bot, COPY, "b2", exclude={9}) == (3, 0)


async def test_blocked_and_deleted_chats_are_skipped_for_good(storage):
    blocked = TelegramForbiddenError(method=MagicMock(), message="bot was blocked by the user")
    gone = TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found")
    bot = _bot({2: blocked, 3: gone})

    assert await announcements.broadcast(bot, COPY, "b1", exclude={9}) == (1, 2)
    assert _marked(storage) == [1, 2, 3]  # повторять бессмысленно


async def test_broken_message_aborts_without_marking_the_rest(storage):
    broken = TelegramBadRequest(
        method=MagicMock(), message="Bad Request: message to copy not found"
    )
    bot = _bot({2: broken})

    with pytest.raises(BroadcastAborted, match="message to copy not found"):
        await announcements.broadcast(bot, COPY, "b1", exclude={9})
    assert _marked(storage) == [1]  # остальным не «отправлено» понарошку


async def test_flood_limit_waits_and_retries(storage):
    flood = TelegramRetryAfter(method=MagicMock(), message="Too Many Requests", retry_after=7)
    bot = _bot({2: [flood, None]})

    assert await announcements.broadcast(bot, COPY, "b1", exclude={9}) == (3, 0)
    assert 7 in storage["sleeps"]


async def test_network_error_is_retried_next_time(storage):
    bot = _bot({2: TelegramNetworkError(method=MagicMock(), message="timeout")})

    assert await announcements.broadcast(bot, COPY, "b1", exclude={9}) == (2, 1)
    assert 2 not in _marked(storage)  # догонит повторное «Разослать»


def test_update_summary_text():
    tags: list[str] = []

    class Parser(HTMLParser):
        def handle_starttag(self, tag, attrs):
            tags.append(tag)

    text = announcements.announcement_text()
    Parser().feed(text)

    assert tags == []
    for must in ("/links", "/classic", "подробнее", "доп. занятия", "@foxymoff"):
        assert must in text
    assert text == text.lower()
    assert not any(dash in text for dash in ("—", "–", " - "))


# ── Команда /announce и кнопки ────────────────────────────


@pytest_asyncio.fixture
async def state() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=9, user_id=9))


@pytest.fixture
def as_admin(monkeypatch):
    async def get_user(user_id):
        return {"user_id": user_id, "role": "admin"}

    monkeypatch.setattr(admin, "get_user", get_user)


def _message(text: str = "текст рассылки") -> MagicMock:
    message = MagicMock()
    message.from_user.id = 9
    message.chat.id = 9
    message.message_id = 555
    message.text = text
    message.delete = AsyncMock()
    message.answer = AsyncMock()
    message.bot.send_message = AsyncMock()
    return message


def _callback(data: str) -> MagicMock:
    callback = MagicMock()
    callback.data = data
    callback.from_user.id = 9
    callback.message.chat.id = 9
    callback.answer = AsyncMock()
    callback.message.edit_text = AsyncMock()
    callback.message.delete = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.bot.send_message = AsyncMock()
    return callback


async def test_announce_is_admin_only(monkeypatch, state):
    async def get_user(user_id):
        return {"user_id": user_id, "role": "student"}

    monkeypatch.setattr(admin, "get_user", get_user)
    message = _message("/announce")

    await admin.cmd_announce(message, state)

    assert "Нет доступа" in message.answer.await_args.args[0]
    assert await state.get_state() is None


async def test_announce_asks_for_message(as_admin, state):
    message = _message("/announce")

    await admin.cmd_announce(message, state)

    assert "Пришли сообщение" in message.answer.await_args.args[0]
    kb = message.answer.await_args.kwargs["reply_markup"]
    assert [row[0].callback_data for row in kb.inline_keyboard] == [
        "announce:template",
        "announce:cancel",
    ]
    assert await state.get_state() == admin.AdminStates.broadcast_wait.state


async def test_own_message_is_previewed_as_copy(monkeypatch, as_admin, state):
    previews = []

    async def send_broadcast(bot, chat_id, content):
        previews.append((chat_id, content))

    async def recipients(broadcast_id, *, exclude=frozenset()):
        return [1, 2, 3]

    monkeypatch.setattr(admin, "send_broadcast", send_broadcast)
    monkeypatch.setattr(admin, "broadcast_recipients", recipients)
    await state.set_state(admin.AdminStates.broadcast_wait)
    message = _message("завтра пар нет")

    await admin.on_broadcast_message(message, state)

    assert previews == [(9, COPY)]  # предпросмотр — копия ровно того, что прислал админ
    message.delete.assert_not_awaited()  # исходник для копирования не удаляем
    kb = message.bot.send_message.await_args.kwargs["reply_markup"]
    assert kb.inline_keyboard[0][0].text == "📣 Разослать (3)"
    data = await state.get_data()
    assert BroadcastContent.from_data(data["broadcast"]) == COPY
    assert data["broadcast_id"] == "b9-555"
    assert await state.get_state() is None


async def test_template_uses_update_summary(monkeypatch, as_admin, state):
    previews = []

    async def send_broadcast(bot, chat_id, content):
        previews.append(content)

    async def recipients(broadcast_id, *, exclude=frozenset()):
        return [1]

    monkeypatch.setattr(admin, "send_broadcast", send_broadcast)
    monkeypatch.setattr(admin, "broadcast_recipients", recipients)
    await state.set_state(admin.AdminStates.broadcast_wait)

    await admin.on_broadcast_template(_callback("announce:template"), state)

    assert previews == [BroadcastContent(text=announcements.announcement_text())]
    assert (await state.get_data())["broadcast_id"] == announcements.ANNOUNCEMENT_ID


async def test_send_broadcasts_draft_and_reports(monkeypatch, as_admin, state):
    calls = []

    async def broadcast(bot, content, broadcast_id, *, exclude):
        calls.append((content, broadcast_id, exclude))
        return 120, 8

    monkeypatch.setattr(admin, "broadcast", broadcast)
    await state.update_data(broadcast=COPY.to_data(), broadcast_id="b9-555")
    callback = _callback("announce:send")

    await admin.on_announce_send(callback, state)

    assert calls == [(COPY, "b9-555", {9})]
    result = callback.message.edit_text.await_args.args[0]
    assert "отправлено: 120" in result and "Не доставлено: 8" in result
    assert (await state.get_data())["broadcast"] is None


async def test_send_without_draft_asks_to_start_over(as_admin, state):
    callback = _callback("announce:send")

    await admin.on_announce_send(callback, state)

    callback.answer.assert_awaited_once_with(
        "Черновик не найден — начни заново: /announce", show_alert=True
    )


async def test_aborted_broadcast_is_reported(monkeypatch, as_admin, state):
    async def broadcast(bot, content, broadcast_id, *, exclude):
        raise BroadcastAborted("message to copy not found")

    monkeypatch.setattr(admin, "broadcast", broadcast)
    await state.update_data(broadcast=COPY.to_data(), broadcast_id="b9-555")
    callback = _callback("announce:send")

    await admin.on_announce_send(callback, state)

    text = callback.message.edit_text.await_args.args[0]
    assert "Рассылка остановлена" in text and "message to copy not found" in text


async def test_cancel_clears_draft(as_admin, state):
    await state.set_state(admin.AdminStates.broadcast_wait)
    await state.update_data(broadcast=COPY.to_data(), broadcast_id="b9-555")
    callback = _callback("announce:cancel")

    await admin.on_announce_cancel(callback, state)

    assert await state.get_state() is None
    assert (await state.get_data())["broadcast"] is None
    callback.answer.assert_awaited_once_with("Отменено")


async def test_again_asks_for_new_message(as_admin, state):
    callback = _callback("announce:again")

    await admin.on_announce_again(callback, state)

    assert "Пришли сообщение" in callback.message.answer.await_args.args[0]
    assert await state.get_state() == admin.AdminStates.broadcast_wait.state
