"""
Выбор доп. занятий (/extra); сами занятия показываются в основном расписании.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database import get_user, update_user_extra_choices
from extra_schedule import get_extra_options, parse_extra_choices
from handlers.start import _profile_text, _replace_with_main_menu
from keyboards import extra_select_kb, main_menu_kb, profile_menu_kb
from message_style import HTML_PARSE_MODE, MAIN_MENU_TEXT, register_required_text
from ui_messages import delete_user_message, replace_ui_messages

logger = logging.getLogger(__name__)
router = Router()


class ExtraSelect(StatesGroup):
    choosing = State()


def _selected_keys(user: dict) -> list[str]:
    """Получить выбранные пользователем доп. занятия."""
    return parse_extra_choices(user.get("extra_choices"))


@router.message(F.text.in_({"Доп. занятия", "📌 Доп. занятия", "📌Доп. занятия"}))
async def on_extra_menu_removed(message: Message, state: FSMContext) -> None:
    """Старая кнопка «📌 Доп. занятия»: кружки теперь в расписании — обновить меню."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        return
    await delete_user_message(message)
    await _replace_with_main_menu(message, state, user)


@router.callback_query(F.data.in_({"extra_detail", "extra_collapse"}))
async def on_extra_week_removed(callback: CallbackQuery) -> None:
    """Кнопки старого отдельного расписания кружков."""
    await callback.answer("Кружки теперь показываются в основном расписании", show_alert=True)


@router.message(Command("extra"))
async def cmd_extra(message: Message, state: FSMContext) -> None:
    """Скрытый алиас: открыть учебный профиль."""
    user = await get_user(message.from_user.id)
    if not user:
        await delete_user_message(message)
        sent = await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        await replace_ui_messages(
            message.bot,
            message.chat.id,
            state,
            [sent.message_id],
            screen="system",
            clear_state=True,
            last_bot_msg=sent.message_id,
        )
        return
    await delete_user_message(message)
    sent = await message.answer(
        _profile_text(user), reply_markup=profile_menu_kb(), parse_mode=HTML_PARSE_MODE
    )
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [sent.message_id],
        screen="profile",
        clear_state=True,
        last_bot_msg=sent.message_id,
    )


@router.callback_query(ExtraSelect.choosing, F.data.startswith("extra_edit:"))
async def on_extra_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка мультивыбора доп. занятий через /extra."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        await state.clear()
        return

    options = get_extra_options(user["group_name"])
    data = await state.get_data()
    selected = set(parse_extra_choices(data.get("extra_edit_selected")))
    parts = callback.data.split(":")
    action = parts[1]

    if action == "toggle" and len(parts) == 3:
        index = int(parts[2])
        if index >= len(options):
            await callback.answer("Не получилось · занятие не найдено", show_alert=True)
            return
        key = options[index]["_key"]
        if key in selected:
            selected.remove(key)
        else:
            selected.add(key)
        await state.update_data(extra_edit_selected=list(selected))
        await callback.message.edit_reply_markup(
            reply_markup=extra_select_kb(options, selected, "extra_edit")
        )
        await callback.answer()
        return

    if action == "none":
        selected = set()
    elif action != "done":
        await callback.answer()
        return

    ordered_selected = [option["_key"] for option in options if option["_key"] in selected]
    await update_user_extra_choices(callback.from_user.id, ordered_selected)
    await callback.answer("Готово · доп. занятия обновлены", show_alert=True)
    updated_user = await get_user(callback.from_user.id)
    role = (updated_user.get("role") or "student") if updated_user else "student"
    sent = await callback.message.answer(
        MAIN_MENU_TEXT,
        reply_markup=main_menu_kb(role),
        parse_mode=HTML_PARSE_MODE,
    )
    await replace_ui_messages(
        callback.bot,
        callback.message.chat.id,
        state,
        [sent.message_id],
        screen="main_menu",
        clear_state=True,
        last_bot_msg=sent.message_id,
    )
