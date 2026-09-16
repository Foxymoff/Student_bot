import pytest
import pytest_asyncio
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey

from storage import SQLiteStorage


class Demo(StatesGroup):
    one = State()


def _key() -> StorageKey:
    return StorageKey(bot_id=1, chat_id=5, user_id=5)


@pytest_asyncio.fixture
async def store(tmp_path):
    s = SQLiteStorage(tmp_path / "fsm.db")
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_state_roundtrip_and_clear(store):
    key = _key()
    assert await store.get_state(key) is None
    await store.set_state(key, Demo.one)
    assert await store.get_state(key) == "Demo:one"
    await store.set_state(key, None)
    assert await store.get_state(key) is None


@pytest.mark.asyncio
async def test_data_roundtrip_and_update(store):
    key = _key()
    assert await store.get_data(key) == {}
    await store.set_data(key, {"ui_msg_ids": [1, 2], "имя": "Женя"})
    assert await store.get_data(key) == {"ui_msg_ids": [1, 2], "имя": "Женя"}
    await store.update_data(key, {"имя": "Пётр"})
    assert await store.get_data(key) == {"ui_msg_ids": [1, 2], "имя": "Пётр"}


@pytest.mark.asyncio
async def test_state_and_data_are_independent(store):
    key = _key()
    await store.set_data(key, {"a": 1})
    await store.set_state(key, Demo.one)
    # смена состояния не трёт data
    assert await store.get_data(key) == {"a": 1}
    # сброс состояния тоже сохраняет data
    await store.set_state(key, None)
    assert await store.get_data(key) == {"a": 1}
    assert await store.get_state(key) is None


@pytest.mark.asyncio
async def test_persists_across_restart(tmp_path):
    path = tmp_path / "fsm.db"
    key = _key()

    first = SQLiteStorage(path)
    await first.set_state(key, "SomeState")
    await first.set_data(key, {"ui_msg_ids": [42], "n": 7})
    await first.close()

    # Новый инстанс на том же файле = перезапуск процесса.
    second = SQLiteStorage(path)
    assert await second.get_state(key) == "SomeState"
    assert await second.get_data(key) == {"ui_msg_ids": [42], "n": 7}
    await second.close()
