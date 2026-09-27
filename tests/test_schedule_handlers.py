"""Хендлеры расписания: служебные сообщения и отправка."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from handlers import schedule, start


@pytest_asyncio.fixture
async def state() -> FSMContext:
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=9, user_id=9))


async def test_period_header_edit_targets_correct_message(state):
    """Регресс: шапка «Выбери период» не обновлялась из-за позиционных аргументов.

    В aiogram 3.x сигнатура — (text, business_connection_id, chat_id, message_id).
    """
    calls = []

    async def edit_message_text(
        text, business_connection_id=None, chat_id=None, message_id=None, **kw
    ):
        calls.append((text, business_connection_id, chat_id, message_id))

    message = MagicMock()
    message.bot.edit_message_text = edit_message_text
    message.chat.id = 9
    await state.update_data(last_bot_msg=77)

    await schedule._update_period_header(message, state, "<b>Сегодня</b>")

    assert calls == [("<b>Сегодня</b>", None, 9, 77)]


def _message(user_id: int = 9) -> MagicMock:
    message = MagicMock()
    message.from_user.id = user_id
    message.chat.id = user_id
    message.delete = AsyncMock()
    message.answer = AsyncMock(return_value=MagicMock(message_id=5))
    message.bot.delete_message = AsyncMock()
    return message


@pytest.mark.parametrize(("stored", "expected"), [(0, True), (1, False)])
async def test_classic_command_toggles_flag(state, monkeypatch, stored, expected):
    calls = []

    async def get_user(user_id):
        return {"user_id": user_id, "group_name": "ИСП-25-1", "classic_view": stored}

    async def update_user_classic_view(user_id, classic):
        calls.append((user_id, classic))

    monkeypatch.setattr(start, "get_user", get_user)
    monkeypatch.setattr(start, "update_user_classic_view", update_user_classic_view)
    message = _message()

    await start.cmd_classic(message, state)

    assert calls == [(9, expected)]
    text = message.answer.await_args.args[0]
    assert ("классический" if expected else "новый") in text
    assert "/classic" in text
