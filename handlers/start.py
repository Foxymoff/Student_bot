"""
Обработчик /start, выбора группы и подгрупп, навигация назад.
"""

import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from config import ENG_SUBGROUPS
from database import (
    get_user,
    add_user,
    update_user_subgroups,
    update_user_compact,
    update_user_extra_choices,
    update_user_extra_in_schedule,
    update_user_daily_notify,
    update_user_change_alert,
)
from extra_schedule import get_extra_options, parse_extra_choices
from message_style import HTML_PARSE_MODE, MAIN_MENU_TEXT, esc, register_required_text, title, titled
from ui_messages import (
    add_ui_messages,
    clear_state_keep_ui,
    clear_ui_messages,
    delete_user_message,
    register_ui_messages,
    replace_ui_messages,
)
from keyboards import (
    group_select_kb,
    subgroup_select_kb,
    eng_subgroup_select_kb,
    extra_select_kb,
    extra_display_kb,
    daily_notify_kb,
    daily_time_back_kb,
    daily_notify_sound_kb,
    main_menu_kb,
    back_kb,
    settings_change_alert_kb,
    settings_daily_notify_kb,
    settings_extra_display_kb,
    settings_menu_kb,
    profile_menu_kb,
    settings_view_kb,
)

logger = logging.getLogger(__name__)
router = Router()


def _eng_sg_label(group_name: str, sg: int) -> str:
    """Человекочитаемое название англ. подгруппы: 'Сильная · Шарафутдинова'."""
    return ENG_SUBGROUPS.get(group_name, {}).get(sg, f"Подгруппа {sg}")


class Registration(StatesGroup):
    group = State()
    subgroup_inf = State()
    subgroup_eng = State()
    extra = State()
    extra_display = State()
    daily_notify = State()
    daily_time = State()
    daily_sound = State()
    change_alert = State()
    change_alert_sound = State()


class Settings(StatesGroup):
    daily_time = State()
    daily_sound = State()


class Profile(StatesGroup):
    group = State()
    subgroup_inf = State()
    subgroup_eng = State()
    extra = State()


def _show_extra_button(user: dict | None) -> bool:
    """Нужна ли отдельная кнопка доп. занятий в главном меню."""
    return not bool(user and user.get("extra_in_schedule"))


def _settings_text(user: dict) -> str:
    """Текст общего меню настроек."""
    return title("Настройки")


def _help_text() -> str:
    """Текст команды /help."""
    return titled(
        "Помощь",
        "Вопросы, баги и предложения: @foxymoff\n\n"
        "По проблемам укажите группу, раздел и что произошло.",
    )


def _schedule_view_text() -> str:
    """Текст раздела настроек вида расписания."""
    return (
        f"{title('Вид расписания')}\n\n"
        "Рекомендуем:\n"
        "Android — компактный\n"
        "iOS, ПК — колонки"
    )


def _daily_notify_text(user: dict) -> str:
    """Текст раздела настроек ежедневного расписания."""
    enabled = bool(user.get("daily_notify_enabled"))
    status = "включено" if enabled else "выключено"
    notify_time = str(user.get("daily_notify_time") or "08:00")
    return titled(
        "Ежедневное расписание",
        "Автоотправка расписания на день в выбранное время.\n\n"
        f"Статус · {status}\n"
        f"Время · <b>{esc(notify_time)}</b>",
    )


def _change_alert_text(user: dict) -> str:
    """Текст раздела настроек алертов изменений."""
    return titled(
        "Алерты изменений",
        "Уведомления об отмене, смене аудитории и онлайн-занятиях.",
    )


def _profile_text(user: dict) -> str:
    """Текст меню учебного профиля."""
    sg_inf = user.get("subgroup_cs", 1) or 1
    sg_eng = user.get("subgroup_en", 1) or 1
    eng_label = _eng_sg_label(user["group_name"], sg_eng)
    extra_count = len(parse_extra_choices(user.get("extra_choices")))
    extra_label = f"{extra_count} выбрано" if extra_count else "не выбраны"
    return (
        f"{title('Учебный профиль')}\n\n"
        f"Группа · {esc(user['group_name'])}\n"
        f"Информатика · {sg_inf} подгр.\n"
        f"Английский · {esc(eng_label)}\n"
        f"Доп. занятия · {esc(extra_label)}"
    )


def _settings_kb(user: dict):
    """Inline-клавиатура общего меню настроек."""
    return settings_menu_kb(
        bool(user.get("compact_mode")),
        bool(user.get("extra_in_schedule")),
        bool(user.get("daily_notify_enabled")),
        str(user.get("daily_notify_time") or "08:00"),
        bool(user.get("change_alert_enabled")),
    )


def _parse_time(text: str | None) -> str | None:
    """Нормализовать время в формате HH:MM."""
    if not text:
        return None
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _daily_time_text(new: bool = False) -> str:
    """Понятная подсказка для ввода времени уведомления."""
    action = "Напиши новое время" if new else "Напиши время"
    return titled(
        "Время уведомления",
        f"{action} в формате: <b>часы:минуты</b>\n"
        "Например · 08:30 или 8:30",
    )


async def _ask_registration_daily_notify(callback: CallbackQuery, state: FSMContext) -> None:
    """Спросить при регистрации, нужно ли ежедневное уведомление."""
    await state.set_state(Registration.daily_notify)
    await callback.message.edit_text(
        titled("Ежедневное расписание", "Присылать уведомление каждый день?"),
        reply_markup=daily_notify_kb("reg_daily_notify"),
        parse_mode=HTML_PARSE_MODE,
    )


async def _ask_registration_change_alert(callback: CallbackQuery, state: FSMContext) -> None:
    """Спросить при регистрации, нужны ли алерты изменений расписания."""
    await state.set_state(Registration.change_alert)
    await callback.message.edit_text(
        titled("Алерты изменений", "Сообщать об отменах и смене аудитории?"),
        reply_markup=daily_notify_kb("reg_change_alert"),
        parse_mode=HTML_PARSE_MODE,
    )


async def _finish_registration_from_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Завершить регистрацию и показать главное меню."""
    user = await get_user(callback.from_user.id)
    await _replace_with_main_menu(callback.message, state, user)


async def _finish_registration_from_message(message: Message, state: FSMContext) -> None:
    """Завершить регистрацию после текстового ввода."""
    user = await get_user(message.from_user.id)
    await _replace_with_main_menu(message, state, user)


async def _replace_with_main_menu(message: Message, state: FSMContext, user: dict | None) -> None:
    """Показать главное меню до удаления старого экрана."""
    role = user.get("role", "student") if user else "student"
    sent = await message.answer(
        MAIN_MENU_TEXT,
        reply_markup=main_menu_kb(role, _show_extra_button(user)),
        parse_mode=HTML_PARSE_MODE,
    )
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [sent.message_id],
        screen="main_menu",
        clear_state=True,
        last_bot_msg=sent.message_id,
    )


async def _send_register_required(message: Message, state: FSMContext) -> None:
    """Показать сообщение о необходимости регистрации."""
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


async def _show_profile_message(message: Message, state: FSMContext, user: dict) -> None:
    """Открыть учебный профиль отдельным сообщением."""
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


async def _show_profile_callback(callback: CallbackQuery, state: FSMContext) -> bool:
    """Вернуться к корневому экрану учебного профиля."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return False
    await clear_state_keep_ui(state)
    await callback.message.edit_text(
        _profile_text(user),
        reply_markup=profile_menu_kb(),
        parse_mode=HTML_PARSE_MODE,
    )
    await register_ui_messages(
        state,
        [callback.message.message_id],
        screen="profile",
        last_bot_msg=callback.message.message_id,
    )
    return True


async def _open_profile_group(callback: CallbackQuery, state: FSMContext, user: dict) -> None:
    """Открыть выбор группы внутри учебного профиля."""
    await state.set_state(Profile.group)
    await state.update_data(profile_action="group")
    await callback.message.edit_text(
        titled("Смена группы", f"Сейчас · {esc(user['group_name'])}\n\nВыбери новую группу."),
        reply_markup=group_select_kb("profile_group", include_back=True),
        parse_mode=HTML_PARSE_MODE,
    )
    await register_ui_messages(
        state,
        [callback.message.message_id],
        screen="profile",
        last_bot_msg=callback.message.message_id,
    )


async def _open_profile_subgroups(callback: CallbackQuery, state: FSMContext, user: dict) -> None:
    """Открыть выбор подгрупп внутри учебного профиля."""
    sg_inf = user.get("subgroup_cs", 1) or 1
    sg_eng = user.get("subgroup_en", 1) or 1
    eng_label = _eng_sg_label(user["group_name"], sg_eng)
    await state.set_state(Profile.subgroup_inf)
    await state.update_data(profile_action="subgroups", profile_sg_inf=None)
    await callback.message.edit_text(
        titled(
            "Смена подгрупп",
            f"Информатика · {sg_inf} подгр.\n"
            f"Английский · {esc(eng_label)}\n\n"
            "Выбери подгруппу по информатике.",
        ),
        reply_markup=subgroup_select_kb("inf", "profile_sg", include_back=True),
        parse_mode=HTML_PARSE_MODE,
    )
    await register_ui_messages(
        state,
        [callback.message.message_id],
        screen="profile",
        last_bot_msg=callback.message.message_id,
    )


async def _open_profile_extra(
    callback: CallbackQuery,
    state: FSMContext,
    user: dict,
    *,
    selected: list[str] | None = None,
) -> bool:
    """Открыть выбор доп. занятий внутри учебного профиля."""
    options = get_extra_options(user["group_name"])
    if not options:
        await update_user_extra_choices(callback.from_user.id, [])
        await update_user_extra_in_schedule(callback.from_user.id, False)
        await _show_profile_callback(callback, state)
        return False

    selected = parse_extra_choices(selected if selected is not None else user.get("extra_choices"))
    await state.set_state(Profile.extra)
    await state.update_data(profile_extra_selected=selected)
    await callback.message.edit_text(
        titled("Доп. занятия", "Выбери доп. занятия. Можно отметить несколько."),
        reply_markup=extra_select_kb(options, selected, "profile_extra", include_back=True),
        parse_mode=HTML_PARSE_MODE,
    )
    await register_ui_messages(
        state,
        [callback.message.message_id],
        screen="profile",
        last_bot_msg=callback.message.message_id,
    )
    return True


async def push_nav(state: FSMContext, screen: str) -> None:
    """Добавить экран в стек навигации (без дублей подряд)."""
    data = await state.get_data()
    stack = data.get("_nav_stack", [])
    if not stack or stack[-1] != screen:
        stack.append(screen)
        await state.update_data(_nav_stack=stack)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    """Команда /start — приветствие и выбор группы."""
    await delete_user_message(message)
    user = await get_user(message.from_user.id)
    if user:
        await _replace_with_main_menu(message, state, user)
    else:
        sent = await message.answer(
            titled("Первичная настройка", "Выбери свою группу."),
            reply_markup=group_select_kb(),
            parse_mode=HTML_PARSE_MODE,
        )
        await replace_ui_messages(
            message.bot,
            message.chat.id,
            state,
            [sent.message_id],
            screen="registration",
            clear_state=True,
            last_bot_msg=sent.message_id,
        )
        await state.set_state(Registration.group)


@router.callback_query(F.data.startswith("group:"))
async def on_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка выбора группы → спрашиваем подгруппу по информатике."""
    group_name = callback.data.split(":", 1)[1]
    await add_user(callback.from_user.id, group_name)
    await state.update_data(group_name=group_name)
    await state.set_state(Registration.subgroup_inf)
    await callback.message.edit_text(
        titled("Группа сохранена", f"{esc(group_name)}\n\nВыбери подгруппу по информатике."),
        reply_markup=subgroup_select_kb("inf"),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sg:inf:"))
async def on_subgroup_inf(callback: CallbackQuery, state: FSMContext) -> None:
    """Подгруппа по информатике выбрана → спрашиваем по английскому."""
    sg_inf = int(callback.data.split(":")[-1])
    await state.update_data(sg_inf=sg_inf)
    data = await state.get_data()
    group_name = data.get("group_name", "")
    await state.set_state(Registration.subgroup_eng)
    await callback.message.edit_text(
        titled("Информатика сохранена", "Выбери подгруппу по английскому."),
        reply_markup=eng_subgroup_select_kb(group_name),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("sg:eng:"))
async def on_subgroup_eng(callback: CallbackQuery, state: FSMContext) -> None:
    """Подгруппа по английскому выбрана → спрашиваем доп. занятия."""
    sg_eng = int(callback.data.split(":")[-1])
    data = await state.get_data()
    sg_inf = data.get("sg_inf", 1)
    group_name = data.get("group_name", "")
    await update_user_subgroups(callback.from_user.id, sg_inf, sg_eng)

    eng_label = _eng_sg_label(group_name, sg_eng)
    options = get_extra_options(group_name)
    await state.update_data(reg_extra_selected=[])

    if not options:
        await update_user_extra_choices(callback.from_user.id, [])
        await update_user_extra_in_schedule(callback.from_user.id, False)
        await callback.answer(
            f"Подгруппы сохранены · инф. {sg_inf} · англ. {eng_label}",
            show_alert=True,
        )
        await _ask_registration_daily_notify(callback, state)
        return

    await state.set_state(Registration.extra)
    await callback.message.edit_text(
        titled(
            "Подгруппы сохранены",
            f"Информатика · {sg_inf} подгр.\n"
            f"Английский · {esc(eng_label)}\n\n"
            "Выбери доп. занятия. Можно отметить несколько.",
        ),
        reply_markup=extra_select_kb(options, set(), "reg_extra"),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(Registration.extra, F.data.startswith("reg_extra:"))
async def on_registration_extra(callback: CallbackQuery, state: FSMContext) -> None:
    """Мультивыбор доп. занятий во время регистрации."""
    data = await state.get_data()
    group_name = data.get("group_name", "")
    options = get_extra_options(group_name)
    selected = set(parse_extra_choices(data.get("reg_extra_selected")))
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
        await state.update_data(reg_extra_selected=list(selected))
        await callback.message.edit_reply_markup(
            reply_markup=extra_select_kb(options, selected, "reg_extra")
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

    if ordered_selected:
        await state.set_state(Registration.extra_display)
        await callback.message.edit_text(
            titled("Доп. занятия", "Где показывать выбранные допы?"),
            reply_markup=extra_display_kb("reg_extra_display"),
            parse_mode=HTML_PARSE_MODE,
        )
        await callback.answer("Готово · доп. занятия сохранены", show_alert=True)
        return

    await update_user_extra_in_schedule(callback.from_user.id, False)
    await callback.answer("Готово · доп. занятия сохранены", show_alert=True)
    await _ask_registration_daily_notify(callback, state)


@router.callback_query(Registration.extra_display, F.data.startswith("reg_extra_display:"))
async def on_registration_extra_display(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор места отображения доп. занятий во время регистрации."""
    value = int(callback.data.split(":")[-1])
    await update_user_extra_in_schedule(callback.from_user.id, bool(value))
    await callback.answer("Готово · настройка сохранена", show_alert=True)
    await _ask_registration_daily_notify(callback, state)


@router.callback_query(Registration.daily_notify, F.data.startswith("reg_daily_notify:"))
async def on_registration_daily_notify(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор ежедневного уведомления во время регистрации."""
    value = int(callback.data.split(":")[-1])
    if not value:
        await update_user_daily_notify(callback.from_user.id, False)
        await callback.answer("Готово · уведомление выключено", show_alert=True)
        await _ask_registration_change_alert(callback, state)
        return

    await state.set_state(Registration.daily_time)
    await state.update_data(reg_daily_msg=callback.message.message_id)
    await callback.message.edit_text(
        _daily_time_text(),
        reply_markup=daily_time_back_kb("reg_daily_time_back"),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(Registration.daily_time, F.data == "reg_daily_time_back")
async def on_registration_daily_time_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Вернуться к выбору ежедневного расписания при регистрации."""
    await _ask_registration_daily_notify(callback, state)
    await callback.answer()


@router.message(Registration.daily_time)
async def on_registration_daily_time(message: Message, state: FSMContext) -> None:
    """Ввод времени ежедневного уведомления во время регистрации."""
    notify_time = _parse_time(message.text)
    if not notify_time:
        data = await state.get_data()
        msg_id = data.get("reg_daily_msg")
        if msg_id:
            try:
                await message.bot.edit_message_text(
                    _daily_time_text(),
                    message.chat.id,
                    msg_id,
                    reply_markup=daily_time_back_kb("reg_daily_time_back"),
                    parse_mode=HTML_PARSE_MODE,
                )
                return
            except Exception:
                pass
        sent = await message.answer(
            _daily_time_text(),
            reply_markup=daily_time_back_kb("reg_daily_time_back"),
            parse_mode=HTML_PARSE_MODE,
        )
        await state.update_data(reg_daily_msg=sent.message_id)
        return

    try:
        await message.delete()
    except Exception:
        pass
    await state.update_data(reg_daily_time=notify_time)
    await state.set_state(Registration.daily_sound)
    data = await state.get_data()
    msg_id = data.get("reg_daily_msg")
    sound_text = titled("Звук уведомления", "Присылать со звуком?")
    sent = await message.answer(
        sound_text,
        reply_markup=daily_notify_sound_kb("reg_daily_sound"),
        parse_mode=HTML_PARSE_MODE,
    )
    await register_ui_messages(
        state,
        [sent.message_id],
        screen="registration",
        last_bot_msg=sent.message_id,
        reg_daily_msg=sent.message_id,
    )
    if msg_id:
        try:
            await message.bot.delete_message(message.chat.id, msg_id)
        except Exception:
            pass


@router.callback_query(Registration.daily_sound, F.data.startswith("reg_daily_sound:"))
async def on_registration_daily_sound(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор звука ежедневного уведомления во время регистрации."""
    sound = bool(int(callback.data.split(":")[-1]))
    data = await state.get_data()
    notify_time = data.get("reg_daily_time", "08:00")
    await update_user_daily_notify(callback.from_user.id, True, notify_time, sound)
    await callback.answer("Готово · уведомление включено", show_alert=True)
    await _ask_registration_change_alert(callback, state)


@router.callback_query(Registration.change_alert, F.data.startswith("reg_change_alert:"))
async def on_registration_change_alert(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор алертов изменений во время регистрации."""
    value = int(callback.data.split(":")[-1])
    if not value:
        await update_user_change_alert(callback.from_user.id, False)
        await callback.answer("Готово · алерты выключены", show_alert=True)
        await _finish_registration_from_callback(callback, state)
        return

    await state.set_state(Registration.change_alert_sound)
    await callback.message.edit_text(
        titled("Звук алертов", "Присылать со звуком?"),
        reply_markup=daily_notify_sound_kb("reg_change_alert_sound"),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(Registration.change_alert_sound, F.data.startswith("reg_change_alert_sound:"))
async def on_registration_change_alert_sound(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор звука алертов изменений во время регистрации."""
    sound = bool(int(callback.data.split(":")[-1]))
    await update_user_change_alert(callback.from_user.id, True, sound)
    await callback.answer("Готово · алерты включены", show_alert=True)
    await _finish_registration_from_callback(callback, state)


# ── Учебный профиль (/profile) ────────────────────────────


@router.message(Command("profile"))
async def cmd_profile(message: Message, state: FSMContext) -> None:
    """Команда /profile — группа, подгруппы и доп. занятия."""
    user = await get_user(message.from_user.id)
    if not user:
        await _send_register_required(message, state)
        return
    await _show_profile_message(message, state, user)


@router.callback_query(F.data == "profile:back")
async def on_profile_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Вернуться к корневому меню учебного профиля."""
    if await _show_profile_callback(callback, state):
        await callback.answer()


@router.callback_query(F.data == "profile:main")
async def on_profile_main(callback: CallbackQuery, state: FSMContext) -> None:
    """Закрыть учебный профиль и показать главное меню."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return

    await callback.answer()
    await _replace_with_main_menu(callback.message, state, user)


@router.callback_query(F.data == "profile:group")
async def on_profile_group(callback: CallbackQuery, state: FSMContext) -> None:
    """Открыть смену группы из учебного профиля."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await _open_profile_group(callback, state, user)
    await callback.answer()


@router.callback_query(Profile.group, F.data.startswith("profile_group:"))
async def on_profile_group_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохранить группу и запросить подгруппы."""
    group_name = callback.data.split(":", 1)[1]
    await add_user(callback.from_user.id, group_name)
    await state.set_state(Profile.subgroup_inf)
    await state.update_data(
        profile_action="group",
        profile_group_name=group_name,
        profile_sg_inf=None,
    )
    await callback.message.edit_text(
        titled("Группа изменена", f"{esc(group_name)}\n\nВыбери подгруппу по информатике."),
        reply_markup=subgroup_select_kb("inf", "profile_sg", include_back=True),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data == "profile:subgroups")
async def on_profile_subgroups(callback: CallbackQuery, state: FSMContext) -> None:
    """Открыть смену подгрупп из учебного профиля."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await _open_profile_subgroups(callback, state, user)
    await callback.answer()


@router.callback_query(Profile.subgroup_inf, F.data.startswith("profile_sg:inf:"))
async def on_profile_sg_inf(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохранить подгруппу по информатике и запросить английский."""
    sg_inf = int(callback.data.split(":")[-1])
    await state.update_data(profile_sg_inf=sg_inf)
    data = await state.get_data()
    user = await get_user(callback.from_user.id)
    group_name = data.get("profile_group_name") or (user["group_name"] if user else "")
    await state.set_state(Profile.subgroup_eng)
    await callback.message.edit_text(
        titled("Информатика сохранена", "Выбери подгруппу по английскому."),
        reply_markup=eng_subgroup_select_kb(group_name, "profile_sg", include_back=True),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(Profile.subgroup_eng, F.data.startswith("profile_sg:eng:"))
async def on_profile_sg_eng(callback: CallbackQuery, state: FSMContext) -> None:
    """Сохранить подгруппы и завершить нужный сценарий профиля."""
    sg_eng = int(callback.data.split(":")[-1])
    data = await state.get_data()
    sg_inf = int(data.get("profile_sg_inf") or 1)
    await update_user_subgroups(callback.from_user.id, sg_inf, sg_eng)
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        await state.clear()
        return

    if data.get("profile_action") == "group":
        opened = await _open_profile_extra(callback, state, user)
        if opened:
            await callback.answer("Готово · выбери доп. занятия")
        else:
            await callback.answer("Готово · профиль обновлён", show_alert=True)
        return

    await _show_profile_callback(callback, state)
    eng_label = _eng_sg_label(user["group_name"], sg_eng)
    await callback.answer(f"Готово · инф. {sg_inf} · англ. {eng_label}", show_alert=True)


@router.callback_query(F.data == "profile:extra")
async def on_profile_extra(callback: CallbackQuery, state: FSMContext) -> None:
    """Открыть смену доп. занятий из учебного профиля."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await state.update_data(profile_action="extra")
    opened = await _open_profile_extra(callback, state, user)
    if opened:
        await callback.answer()
    else:
        await callback.answer("Доп. занятий для группы нет", show_alert=True)


@router.callback_query(Profile.extra, F.data.startswith("profile_extra:"))
async def on_profile_extra_selected(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка мультивыбора доп. занятий внутри учебного профиля."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        await state.clear()
        return

    options = get_extra_options(user["group_name"])
    data = await state.get_data()
    selected = set(parse_extra_choices(data.get("profile_extra_selected")))
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
        await state.update_data(profile_extra_selected=list(selected))
        await callback.message.edit_reply_markup(
            reply_markup=extra_select_kb(options, selected, "profile_extra", include_back=True)
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
    await _show_profile_callback(callback, state)
    await callback.answer("Готово · доп. занятия обновлены", show_alert=True)


# ── Перевыбор группы / подгрупп (/group, /subgroups) ─────


@router.message(Command("group"))
async def cmd_change_group(message: Message, state: FSMContext) -> None:
    """Скрытый алиас: открыть смену группы внутри учебного профиля."""
    user = await get_user(message.from_user.id)
    if not user:
        await _send_register_required(message, state)
        return
    await delete_user_message(message)
    sent = await message.answer(
        titled("Смена группы", f"Сейчас · {esc(user['group_name'])}\n\nВыбери новую группу."),
        reply_markup=group_select_kb("profile_group", include_back=True),
        parse_mode=HTML_PARSE_MODE,
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
    await state.set_state(Profile.group)
    await state.update_data(profile_action="group")


@router.callback_query(F.data.startswith("chg_group:"))
async def on_change_group(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка перевыбора группы → заново спрашиваем подгруппы и допы."""
    group_name = callback.data.split(":", 1)[1]
    await add_user(callback.from_user.id, group_name)
    await state.update_data(
        group_name=group_name,
        _after_group_change=True,
        _chg_sg_inf=None,
    )
    await callback.message.edit_text(
        titled("Группа изменена", f"{esc(group_name)}\n\nВыбери подгруппу по информатике."),
        reply_markup=subgroup_select_kb("inf", "chg_sg"),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.message(Command("subgroups"))
async def cmd_change_subgroups(message: Message, state: FSMContext) -> None:
    """Скрытый алиас: открыть смену подгрупп внутри учебного профиля."""
    user = await get_user(message.from_user.id)
    if not user:
        await _send_register_required(message, state)
        return
    await delete_user_message(message)
    sg_inf = user.get("subgroup_cs", 1) or 1
    sg_eng = user.get("subgroup_en", 1) or 1
    eng_label = _eng_sg_label(user["group_name"], sg_eng)
    sent = await message.answer(
        titled(
            "Смена подгрупп",
            f"Информатика · {sg_inf} подгр.\n"
            f"Английский · {esc(eng_label)}\n\n"
            "Выбери подгруппу по информатике.",
        ),
        reply_markup=subgroup_select_kb("inf", "profile_sg", include_back=True),
        parse_mode=HTML_PARSE_MODE,
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
    await state.set_state(Profile.subgroup_inf)
    await state.update_data(profile_action="subgroups", profile_sg_inf=None)


@router.callback_query(F.data.startswith("chg_sg:inf:"))
async def on_change_sg_inf(callback: CallbackQuery, state: FSMContext) -> None:
    """Перевыбор подгруппы по информатике → спрашиваем английский."""
    sg_inf = int(callback.data.split(":")[-1])
    await state.update_data(_chg_sg_inf=sg_inf)
    user = await get_user(callback.from_user.id)
    group_name = user["group_name"] if user else ""
    await callback.message.edit_text(
        titled("Информатика сохранена", "Выбери подгруппу по английскому."),
        reply_markup=eng_subgroup_select_kb(group_name, "chg_sg"),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("chg_sg:eng:"))
async def on_change_sg_eng(callback: CallbackQuery, state: FSMContext) -> None:
    """Перевыбор подгруппы по английскому → сохраняем и при смене группы спрашиваем допы."""
    sg_eng = int(callback.data.split(":")[-1])
    data = await state.get_data()
    sg_inf = data.get("_chg_sg_inf", 1)
    await update_user_subgroups(callback.from_user.id, sg_inf, sg_eng)
    user = await get_user(callback.from_user.id)
    eng_label = _eng_sg_label(user["group_name"], sg_eng) if user else str(sg_eng)
    if data.get("_after_group_change") and user:
        options = get_extra_options(user["group_name"])
        await state.update_data(
            group_name=user["group_name"],
            reg_extra_selected=[],
            _after_group_change=None,
            _chg_sg_inf=None,
            _chg_sg_msg=None,
        )
        if options:
            await state.set_state(Registration.extra)
            await callback.message.edit_text(
                titled(
                    "Подгруппы сохранены",
                    f"Информатика · {sg_inf} подгр.\n"
                    f"Английский · {esc(eng_label)}\n\n"
                    "Выбери доп. занятия. Можно отметить несколько.",
                ),
                reply_markup=extra_select_kb(options, set(), "reg_extra"),
                parse_mode=HTML_PARSE_MODE,
            )
        else:
            await update_user_extra_choices(callback.from_user.id, [])
            await update_user_extra_in_schedule(callback.from_user.id, False)
            await clear_state_keep_ui(state)
            await callback.message.edit_text(
                titled("Подгруппы сохранены", "Для этой группы доп. занятий нет."),
                parse_mode=HTML_PARSE_MODE,
            )
        await callback.answer("Готово · профиль обновлён", show_alert=True)
        return

    await callback.answer(f"Готово · инф. {sg_inf} · англ. {eng_label}", show_alert=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await register_ui_messages(
        state,
        [],
        screen=None,
        last_bot_msg=None,
        _chg_sg_msg=None,
    )
    await state.update_data(_chg_sg_inf=None)


@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext) -> None:
    """Команда /settings — общее меню настроек."""
    user = await get_user(message.from_user.id)
    if not user:
        await _send_register_required(message, state)
        return
    await delete_user_message(message)
    sent = await message.answer(
        _settings_text(user),
        reply_markup=_settings_kb(user),
        parse_mode=HTML_PARSE_MODE,
    )
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [sent.message_id],
        screen="settings",
        clear_state=True,
        last_bot_msg=sent.message_id,
    )


@router.message(Command("help"))
async def cmd_help(message: Message, state: FSMContext) -> None:
    """Команда /help — помощь и контакт администратора."""
    await delete_user_message(message)
    sent = await message.answer(
        _help_text(),
        reply_markup=back_kb(),
        parse_mode=HTML_PARSE_MODE,
    )
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [sent.message_id],
        screen="help",
        clear_state=True,
        last_bot_msg=sent.message_id,
    )


@router.callback_query(F.data == "settings:view")
async def on_settings_view(callback: CallbackQuery) -> None:
    """Открыть настройки вида расписания."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    compact = bool(user.get("compact_mode"))
    await callback.message.edit_text(
        _schedule_view_text(),
        reply_markup=settings_view_kb(compact),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:compact:"))
async def on_toggle_compact(callback: CallbackQuery, state: FSMContext) -> None:
    """Переключение компактного режима."""
    value = int(callback.data.split(":")[-1])
    await update_user_compact(callback.from_user.id, bool(value))
    label = "Компактный" if value else "Колонки"
    await callback.message.edit_text(
        _schedule_view_text(),
        reply_markup=settings_view_kb(bool(value)),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer(f"Готово · режим {label.lower()}", show_alert=True)


@router.callback_query(F.data == "settings:extra")
async def on_settings_extra(callback: CallbackQuery) -> None:
    """Открыть настройки отображения доп. занятий."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    extra_in_schedule = bool(user.get("extra_in_schedule"))
    await callback.message.edit_text(
        title("Доп. занятия"),
        reply_markup=settings_extra_display_kb(extra_in_schedule),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:extra_display:"))
async def on_settings_extra_display(callback: CallbackQuery, state: FSMContext) -> None:
    """Переключить место отображения доп. занятий."""
    value = int(callback.data.split(":")[-1])
    await update_user_extra_in_schedule(callback.from_user.id, bool(value))
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await callback.message.edit_text(
        title("Доп. занятия"),
        reply_markup=settings_extra_display_kb(bool(user.get("extra_in_schedule"))),
        parse_mode=HTML_PARSE_MODE,
    )
    await register_ui_messages(
        state,
        [callback.message.message_id],
        screen="settings",
        last_bot_msg=callback.message.message_id,
    )
    mode = "в расписании" if value else "отдельной кнопкой"
    await callback.answer(f"Готово · допы {mode}", show_alert=True)


@router.callback_query(F.data == "settings:daily")
async def on_settings_daily(callback: CallbackQuery) -> None:
    """Открыть настройки ежедневного расписания."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await callback.message.edit_text(
        _daily_notify_text(user),
        reply_markup=settings_daily_notify_kb(
            bool(user.get("daily_notify_enabled")),
            bool(user.get("daily_notify_sound", 1)),
        ),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:daily_enabled:"))
async def on_settings_daily_enabled(callback: CallbackQuery, state: FSMContext) -> None:
    """Включить или выключить ежедневное расписание."""
    value = int(callback.data.split(":")[-1])
    if not value:
        await update_user_daily_notify(callback.from_user.id, False)
        user = await get_user(callback.from_user.id)
        await callback.message.edit_text(
            _daily_notify_text(user),
            reply_markup=settings_daily_notify_kb(False, bool(user.get("daily_notify_sound", 1))),
            parse_mode=HTML_PARSE_MODE,
        )
        await callback.answer("Готово · уведомление выключено", show_alert=True)
        return

    await state.set_state(Settings.daily_time)
    await state.update_data(settings_daily_action="enable", settings_daily_msg=callback.message.message_id)
    await callback.message.edit_text(
        _daily_time_text(),
        reply_markup=daily_time_back_kb("settings_daily_time_back"),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data == "settings:daily_time")
async def on_settings_daily_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Запросить новое время ежедневного расписания."""
    await state.set_state(Settings.daily_time)
    await state.update_data(settings_daily_action="time", settings_daily_msg=callback.message.message_id)
    await callback.message.edit_text(
        _daily_time_text(new=True),
        reply_markup=daily_time_back_kb("settings_daily_time_back"),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(Settings.daily_time, F.data == "settings_daily_time_back")
async def on_settings_daily_time_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Вернуться к настройкам ежедневного расписания с экрана ввода времени."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await state.set_state(None)
    await callback.message.edit_text(
        _daily_notify_text(user),
        reply_markup=settings_daily_notify_kb(
            bool(user.get("daily_notify_enabled")),
            bool(user.get("daily_notify_sound", 1)),
        ),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.message(Settings.daily_time)
async def on_settings_daily_time_input(message: Message, state: FSMContext) -> None:
    """Ввод времени ежедневного расписания из настроек."""
    data = await state.get_data()
    msg_id = data.get("settings_daily_msg")
    notify_time = _parse_time(message.text)
    if not notify_time:
        await delete_user_message(message)
        text = _daily_time_text(new=data.get("settings_daily_action") == "time")
        if msg_id:
            try:
                await message.bot.edit_message_text(
                    text,
                    message.chat.id,
                    msg_id,
                    reply_markup=daily_time_back_kb("settings_daily_time_back"),
                    parse_mode=HTML_PARSE_MODE,
                )
                return
            except Exception:
                pass
        sent = await message.answer(
            text,
            reply_markup=daily_time_back_kb("settings_daily_time_back"),
            parse_mode=HTML_PARSE_MODE,
        )
        await add_ui_messages(state, [sent.message_id], settings_daily_msg=sent.message_id)
        return

    await delete_user_message(message)

    action = data.get("settings_daily_action")
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        await state.clear()
        return

    if action == "enable":
        await state.set_state(Settings.daily_sound)
        await state.update_data(settings_daily_time=notify_time)
        sound_text = titled("Звук уведомления", "Присылать со звуком?")
        sent = await message.answer(
            sound_text,
            reply_markup=daily_notify_sound_kb("settings_daily_sound"),
            parse_mode=HTML_PARSE_MODE,
        )
        await register_ui_messages(
            state,
            [sent.message_id],
            screen="settings",
            last_bot_msg=sent.message_id,
            settings_daily_msg=sent.message_id,
        )
        if msg_id:
            try:
                await message.bot.delete_message(message.chat.id, msg_id)
            except Exception:
                pass
        return

    await update_user_daily_notify(
        message.from_user.id,
        True,
        notify_time,
        bool(user.get("daily_notify_sound", 1)),
    )
    await clear_state_keep_ui(state)
    user = await get_user(message.from_user.id)
    daily_text = _daily_notify_text(user)
    daily_kb = settings_daily_notify_kb(True, bool(user.get("daily_notify_sound", 1)))
    sent = await message.answer(
        daily_text,
        reply_markup=daily_kb,
        parse_mode=HTML_PARSE_MODE,
    )
    await register_ui_messages(
        state,
        [sent.message_id],
        screen="settings",
        last_bot_msg=sent.message_id,
        settings_daily_msg=None,
    )
    if msg_id:
        try:
            await message.bot.delete_message(message.chat.id, msg_id)
        except Exception:
            pass


@router.callback_query(Settings.daily_sound, F.data.startswith("settings_daily_sound:"))
async def on_settings_daily_sound_setup(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор звука при включении ежедневного расписания в настройках."""
    sound = bool(int(callback.data.split(":")[-1]))
    data = await state.get_data()
    notify_time = data.get("settings_daily_time", "08:00")
    await update_user_daily_notify(callback.from_user.id, True, notify_time, sound)
    await clear_state_keep_ui(state)
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        _daily_notify_text(user),
        reply_markup=settings_daily_notify_kb(True, sound),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer("Готово · уведомление включено", show_alert=True)


@router.callback_query(F.data.startswith("settings:daily_sound:"))
async def on_settings_daily_sound_toggle(callback: CallbackQuery) -> None:
    """Переключить звук ежедневного расписания."""
    sound = bool(int(callback.data.split(":")[-1]))
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await update_user_daily_notify(
        callback.from_user.id,
        bool(user.get("daily_notify_enabled")),
        str(user.get("daily_notify_time") or "08:00"),
        sound,
    )
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        _daily_notify_text(user),
        reply_markup=settings_daily_notify_kb(
            bool(user.get("daily_notify_enabled")),
            bool(user.get("daily_notify_sound", 1)),
        ),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer("Готово · звук сохранён", show_alert=True)


@router.callback_query(F.data == "settings:alert")
async def on_settings_change_alert(callback: CallbackQuery) -> None:
    """Открыть настройки алертов изменений расписания."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await callback.message.edit_text(
        _change_alert_text(user),
        reply_markup=settings_change_alert_kb(
            bool(user.get("change_alert_enabled")),
            bool(user.get("change_alert_sound", 1)),
        ),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("settings:alert_enabled:"))
async def on_settings_change_alert_enabled(callback: CallbackQuery) -> None:
    """Включить или выключить алерты изменений расписания."""
    value = bool(int(callback.data.split(":")[-1]))
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    sound = bool(user.get("change_alert_sound", 1))
    await update_user_change_alert(callback.from_user.id, value)
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        _change_alert_text(user),
        reply_markup=settings_change_alert_kb(value, sound),
        parse_mode=HTML_PARSE_MODE,
    )
    status = "включены" if value else "выключены"
    await callback.answer(f"Готово · алерты {status}", show_alert=True)


@router.callback_query(F.data.startswith("settings:alert_sound:"))
async def on_settings_change_alert_sound(callback: CallbackQuery) -> None:
    """Переключить звук алертов изменений расписания."""
    sound = bool(int(callback.data.split(":")[-1]))
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await update_user_change_alert(
        callback.from_user.id,
        bool(user.get("change_alert_enabled")),
        sound,
    )
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        _change_alert_text(user),
        reply_markup=settings_change_alert_kb(
            bool(user.get("change_alert_enabled")),
            bool(user.get("change_alert_sound", 1)),
        ),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer("Готово · звук сохранён", show_alert=True)


@router.callback_query(F.data == "settings:back")
async def on_settings_back(callback: CallbackQuery) -> None:
    """Вернуться в главное меню настроек."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await callback.message.edit_text(
        _settings_text(user),
        reply_markup=_settings_kb(user),
        parse_mode=HTML_PARSE_MODE,
    )
    await callback.answer()


@router.callback_query(F.data == "settings:main")
async def on_settings_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Вернуться из настроек в главное меню бота."""
    user = await get_user(callback.from_user.id)
    if not user:
        await callback.answer("Открой /start", show_alert=True)
        return
    await _replace_with_main_menu(callback.message, state, user)
    await callback.answer()


@router.message(F.text == "⬅️ Назад")
async def on_back(message: Message, state: FSMContext) -> None:
    """Кнопка Назад — вернуться на предыдущий экран из стека."""
    await delete_user_message(message)

    data = await state.get_data()
    bot = message.bot
    chat_id = message.chat.id

    if data.get("ui_screen") == "admin":
        from handlers.admin import handle_admin_back  # lazy import
        if await handle_admin_back(message, state):
            return

    if data.get("ui_screen") == "starosta":
        from handlers.starosta import handle_starosta_back  # lazy import
        if await handle_starosta_back(message, state):
            return

    stack = data.get("_nav_stack", [])
    screen = stack.pop() if stack else None
    await state.update_data(_nav_stack=stack)

    if screen == "schedule_period":
        if data.get("schedule_context") == "other":
            from handlers.schedule import show_other_group_select  # lazy import
            await show_other_group_select(message, state)
            return

        user = await get_user(message.from_user.id)
        await state.set_state(None)
        await _replace_with_main_menu(message, state, user)
        return

    if screen == "other_group_select":
        from handlers.schedule import show_other_group_select  # lazy import
        await show_other_group_select(message, state)
        return

    user = await get_user(message.from_user.id)
    await state.set_state(None)
    await _replace_with_main_menu(message, state, user)
