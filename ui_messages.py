"""
Единый учёт активных сообщений бота в чате.
"""

from collections.abc import Iterable

from aiogram.fsm.context import FSMContext

LEGACY_MESSAGE_KEYS: tuple[str, ...] = (
    "last_bot_msg",
    "last_schedule_msg",
    "last_extra_msg",
    "last_info_msg",
    "_chg_sg_msg",
    "reg_daily_msg",
    "settings_daily_msg",
)

PERSIST_KEYS: tuple[str, ...] = (
    "_nav_stack",
    "ui_msg_ids",
    "ui_screen",
    *LEGACY_MESSAGE_KEYS,
)


def _normalise_ids(values: Iterable[object]) -> list[int]:
    """Вернуть уникальные целочисленные message_id с сохранением порядка."""
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        if value in (None, "", []):
            continue
        if isinstance(value, (list, tuple, set)):
            nested = _normalise_ids(value)
            for msg_id in nested:
                if msg_id not in seen:
                    seen.add(msg_id)
                    result.append(msg_id)
            continue
        try:
            msg_id = int(value)
        except (TypeError, ValueError):
            continue
        if msg_id not in seen:
            seen.add(msg_id)
            result.append(msg_id)
    return result


def collect_ui_message_ids(data: dict) -> list[int]:
    """Собрать все известные активные message_id из состояния."""
    values: list[object] = []
    values.append(data.get("ui_msg_ids", []))
    values.extend(data.get(key) for key in LEGACY_MESSAGE_KEYS)
    return _normalise_ids(values)


async def delete_message_ids(bot, chat_id: int, message_ids: Iterable[object]) -> None:
    """Удалить набор сообщений, игнорируя уже удалённые."""
    for msg_id in _normalise_ids(message_ids):
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            pass


async def delete_user_message(message) -> None:
    """Удалить входящее сообщение пользователя."""
    try:
        await message.delete()
    except Exception:
        pass


async def clear_ui_messages(
    bot,
    chat_id: int,
    state: FSMContext,
    *,
    exclude_ids: Iterable[object] = (),
) -> None:
    """Удалить активный экран бота, кроме явно сохранённых сообщений."""
    data = await state.get_data()
    excluded = set(_normalise_ids(exclude_ids))
    all_ids = collect_ui_message_ids(data)
    await delete_message_ids(bot, chat_id, [msg_id for msg_id in all_ids if msg_id not in excluded])

    kept_ids = [
        msg_id for msg_id in _normalise_ids(data.get("ui_msg_ids", [])) if msg_id in excluded
    ]
    updates: dict[str, object] = {
        "ui_msg_ids": kept_ids,
        "ui_screen": data.get("ui_screen") if kept_ids else None,
    }
    for key in LEGACY_MESSAGE_KEYS:
        ids = _normalise_ids([data.get(key)])
        msg_id = ids[0] if ids else None
        updates[key] = msg_id if msg_id in excluded else None
    await state.update_data(**updates)


async def register_ui_messages(
    state: FSMContext,
    message_ids: Iterable[object],
    *,
    screen: str | None = None,
    **legacy_ids: int | None,
) -> None:
    """Запомнить сообщения текущего активного экрана."""
    ids = _normalise_ids(message_ids)
    updates: dict[str, object] = {
        "ui_msg_ids": ids,
        "ui_screen": screen,
    }
    for key, value in legacy_ids.items():
        if key in LEGACY_MESSAGE_KEYS:
            updates[key] = value
    await state.update_data(**updates)


async def replace_ui_messages(
    bot,
    chat_id: int,
    state: FSMContext,
    message_ids: Iterable[object],
    *,
    screen: str | None = None,
    clear_state: bool = False,
    **legacy_ids: int | None,
) -> None:
    """Зарегистрировать новый экран, предварительно удалив старый без визуального провала."""
    ids = _normalise_ids(message_ids)
    await clear_ui_messages(bot, chat_id, state, exclude_ids=ids)
    if clear_state:
        await state.clear()
    await register_ui_messages(state, ids, screen=screen, **legacy_ids)


async def add_ui_messages(
    state: FSMContext,
    message_ids: Iterable[object],
    **legacy_ids: int | None,
) -> None:
    """Добавить сообщения к текущему экрану."""
    data = await state.get_data()
    ids = _normalise_ids([data.get("ui_msg_ids", []), *message_ids])
    updates: dict[str, object] = {"ui_msg_ids": ids}
    for key, value in legacy_ids.items():
        if key in LEGACY_MESSAGE_KEYS:
            updates[key] = value
    await state.update_data(**updates)


async def clear_state_keep_ui(state: FSMContext, *, extra_keys: Iterable[str] = ()) -> None:
    """Сбросить FSM-состояние, сохранив навигацию и активные сообщения."""
    data = await state.get_data()
    keep_keys = set(PERSIST_KEYS)
    keep_keys.update(extra_keys)
    keep = {key: data[key] for key in keep_keys if key in data and data[key] is not None}
    await state.clear()
    if keep:
        await state.update_data(**keep)
