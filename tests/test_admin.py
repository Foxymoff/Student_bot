from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import handlers.admin as admin


@pytest_asyncio.fixture
async def state() -> FSMContext:
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=99, user_id=99)
    return FSMContext(storage=storage, key=key)


@pytest.mark.asyncio
async def test_edit_admin_body_targets_correct_chat_and_message(state):
    """Регресс: edit_message_text должен получать chat_id/message_id, а не сдвиг.

    В aiogram 3.x сигнатура — (text, business_connection_id, chat_id, message_id).
    Позиционный вызов ломал редактирование (chat.id уходил в business_connection_id),
    из-за чего экраны админки молча не обновлялись.
    """
    calls = []

    async def edit_message_text(
        text, business_connection_id=None, chat_id=None, message_id=None, **kw
    ):
        calls.append(
            {
                "business_connection_id": business_connection_id,
                "chat_id": chat_id,
                "message_id": message_id,
            }
        )
        return True

    bot = MagicMock()
    bot.edit_message_text = edit_message_text
    message = MagicMock()
    message.bot = bot
    message.chat.id = 99

    await state.update_data(ui_msg_ids=[111, 222], ui_screen="admin")

    ok = await admin._edit_admin_body(message, state, "текст")

    assert ok is True
    assert len(calls) == 1
    assert calls[0]["business_connection_id"] is None
    assert calls[0]["chat_id"] == 99
    assert calls[0]["message_id"] == 222


@pytest.mark.asyncio
async def test_edit_admin_body_returns_false_without_body(state):
    message = MagicMock()
    message.chat.id = 99
    assert await admin._edit_admin_body(message, state, "текст") is False
