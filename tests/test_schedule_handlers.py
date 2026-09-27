"""Хендлеры расписания: служебные сообщения и отправка."""

from unittest.mock import MagicMock

import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from handlers import schedule


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
