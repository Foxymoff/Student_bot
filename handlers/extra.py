"""
Обработчик раздела «Доп. занятия» и команды /extra.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database import get_user, update_user_extra_choices, update_user_extra_in_schedule
from extra_schedule import (
    format_extra_week_detailed,
    format_extra_week_short,
    get_extra_options,
    get_extra_week,
    parse_extra_choices,
)
from handlers.start import _profile_text, push_nav
from keyboards import (
    back_kb,
    extra_collapse_kb,
    extra_detail_kb,
    extra_select_kb,
    main_menu_kb,
    profile_menu_kb,
)
from message_style import HTML_PARSE_MODE, MAIN_MENU_TEXT, register_required_text, title
from ui_messages import delete_user_message, replace_ui_messages

logger = logging.getLogger(__name__)
router = Router()


class ExtraSelect(StatesGroup):
    choosing = State()


def _selected_keys(user: dict) -> list[str]:
    """Получить выбранные пользователем доп. занятия."""
    return parse_extra_choices(user.get("extra_choices"))


def _extra_week_text(user: dict) -> str:
    """Сформировать цикличное недельное расписание доп. занятий."""
    selected = _selected_keys(user)
    extra_week = get_extra_week(user["group_name"], selected)
    return format_extra_week_short(extra_week, bool(selected))


def _has_extra_schedule(user: dict) -> bool:
    """Есть ли выбранные доп. занятия с расписанием."""
    selected = _selected_keys(user)
    return bool(get_extra_week(user["group_name"], selected))


@router.message(F.text.in_({"Доп. занятия", "📌 Доп. занятия", "📌Доп. занятия"}))
async def on_extra_menu(message: Message, state: FSMContext) -> None:
    """Кнопка «Доп. занятия» в главном меню: сразу показать неделю."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        return

    await delete_user_message(message)

    text = _extra_week_text(user)
    header = await message.answer(title("Доп. занятия"), reply_markup=back_kb(), parse_mode=HTML_PARSE_MODE)
    reply_markup = extra_detail_kb() if _has_extra_schedule(user) else None
    body = await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [header.message_id, body.message_id],
        screen="extra",
        clear_state=True,
        last_bot_msg=header.message_id,
        last_extra_msg=body.message_id,
    )
    await push_nav(state, "extra_screen")


@router.callback_query(F.data == "extra_detail")
async def on_extra_detail(callback: CallbackQuery) -> None:
    """Развернуть подробный вид расписания доп. занятий."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    selected = _selected_keys(user)
    extra_week = get_extra_week(user["group_name"], selected)
    text = format_extra_week_detailed(extra_week, bool(selected))
    await callback.message.edit_text(
        text,
        reply_markup=extra_collapse_kb() if extra_week else None,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "extra_collapse")
async def on_extra_collapse(callback: CallbackQuery) -> None:
    """Свернуть расписание доп. занятий обратно в краткий вид."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    selected = _selected_keys(user)
    extra_week = get_extra_week(user["group_name"], selected)
    text = format_extra_week_short(extra_week, bool(selected))
    await callback.message.edit_text(
        text,
        reply_markup=extra_detail_kb() if extra_week else None,
        parse_mode="HTML",
    )
    await callback.answer()


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
    sent = await message.answer(_profile_text(user), reply_markup=profile_menu_kb(), parse_mode=HTML_PARSE_MODE)
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
    if not ordered_selected:
        await update_user_extra_in_schedule(callback.from_user.id, False)
    await callback.answer("Готово · доп. занятия обновлены", show_alert=True)
    updated_user = await get_user(callback.from_user.id)
    role = updated_user.get("role", "student") if updated_user else "student"
    sent = await callback.message.answer(
        MAIN_MENU_TEXT,
        reply_markup=main_menu_kb(role, not bool(updated_user and updated_user.get("extra_in_schedule"))),
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
