"""
Обработчик панели администратора: /admin, назначение/снятие старост.
"""

import hmac
import logging
import time

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ADMIN_PASSWORD, ADMIN_USER_IDS
from database import (
    get_all_users,
    get_user,
    get_users_by_role,
    search_users,
    set_user_role,
)
from keyboards import (
    ADMIN_SEARCH_LIMIT,
    admin_menu_kb,
    admin_search_results_kb,
    admin_starostas_kb,
    admin_user_card_kb,
    admin_users_kb,
    back_kb,
    main_menu_kb,
)
from message_style import (
    HTML_PARSE_MODE,
    MAIN_MENU_TEXT,
    esc,
    no_access_text,
    register_required_text,
    title,
    titled,
)
from ui_messages import delete_user_message, replace_ui_messages

logger = logging.getLogger(__name__)
router = Router()


class AdminStates(StatesGroup):
    search_query = State()


ADMIN_MAX_ATTEMPTS = 5
ADMIN_ATTEMPT_WINDOW_SECONDS = 15 * 60
ADMIN_LOCK_SECONDS = 60 * 60

_admin_failures: dict[int, dict[str, float]] = {}


def _admin_user_allowed(user_id: int) -> bool:
    """Проверить optional allowlist для выдачи прав администратора."""
    return not ADMIN_USER_IDS or user_id in ADMIN_USER_IDS


def _admin_lock_seconds_left(user_id: int) -> int:
    """Остаток временной блокировки после неудачных попыток входа."""
    now = time.monotonic()
    record = _admin_failures.get(user_id)
    if not record:
        return 0

    locked_until = record.get("locked_until", 0)
    if locked_until > now:
        return int(locked_until - now)

    if locked_until:
        _admin_failures.pop(user_id, None)
    return 0


def _register_admin_failure(user_id: int) -> int:
    """Запомнить неудачную попытку и вернуть остаток блокировки."""
    now = time.monotonic()
    record = _admin_failures.get(user_id)
    if not record or now - record.get("first_seen", now) > ADMIN_ATTEMPT_WINDOW_SECONDS:
        record = {"count": 0, "first_seen": now, "locked_until": 0}

    record["count"] = record.get("count", 0) + 1
    if record["count"] >= ADMIN_MAX_ATTEMPTS:
        record["locked_until"] = now + ADMIN_LOCK_SECONDS

    _admin_failures[user_id] = record
    return _admin_lock_seconds_left(user_id)


def _clear_admin_failures(user_id: int) -> None:
    """Сбросить счетчик неудачных попыток после успешного входа."""
    _admin_failures.pop(user_id, None)


def _password_matches(password: str) -> bool:
    """Сравнить пароль без раннего выхода по первому несовпавшему символу."""
    return hmac.compare_digest(
        password.encode("utf-8"),
        ADMIN_PASSWORD.encode("utf-8"),
    )


def _chat_display_name(chat) -> str:
    """Получить понятное имя пользователя из Telegram-профиля."""
    username = getattr(chat, "username", None)
    if username:
        return f"@{username}"

    first_name = getattr(chat, "first_name", None)
    last_name = getattr(chat, "last_name", None)
    full_name = " ".join(part for part in (first_name, last_name) if part).strip()
    if full_name:
        return full_name

    return str(getattr(chat, "full_name", "") or getattr(chat, "title", "") or "").strip()


async def _attach_display_names(bot, users: list[dict]) -> list[dict]:
    """Подмешать @username или имя профиля в записи пользователей."""
    result = []
    for user in users:
        enriched = dict(user)
        try:
            chat = await bot.get_chat(user["user_id"])
            display_name = _chat_display_name(chat)
            if display_name:
                enriched["_display_name"] = display_name
        except Exception as exc:
            logger.debug(
                "Не удалось получить профиль пользователя %s: %s",
                user.get("user_id"),
                exc,
            )
        result.append(enriched)
    return result


async def _display_name(bot, user_id: int) -> str:
    """Имя пользователя для сообщений админа."""
    try:
        chat = await bot.get_chat(user_id)
        display_name = _chat_display_name(chat)
        if display_name:
            return display_name
    except Exception as exc:
        logger.debug("Не удалось получить профиль пользователя %s: %s", user_id, exc)
    return f"ID {user_id}"


def _admin_body_id(data: dict) -> int | None:
    """ID сообщения с inline-панелью админа."""
    ids = data.get("ui_msg_ids") or []
    return int(ids[-1]) if ids else None


async def _edit_admin_body(
    message: Message,
    state: FSMContext,
    text: str,
    reply_markup=None,
    parse_mode: str | None = None,
) -> bool:
    """Отредактировать текущее сообщение панели админа."""
    data = await state.get_data()
    body_id = _admin_body_id(data)
    if not body_id:
        return False
    try:
        await message.bot.edit_message_text(
            text,
            chat_id=message.chat.id,
            message_id=body_id,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return True
    except Exception:
        return False


async def _send_admin_menu(message: Message, state: FSMContext) -> None:
    """Показать корневую панель админа с reply-кнопкой Назад."""
    header = await message.answer(
        title("Панель администратора"), reply_markup=back_kb(), parse_mode=HTML_PARSE_MODE
    )
    body = await message.answer(
        titled("Действие", "Выбери действие."),
        reply_markup=admin_menu_kb(),
        parse_mode=HTML_PARSE_MODE,
    )
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [header.message_id, body.message_id],
        screen="admin",
        clear_state=True,
        last_bot_msg=header.message_id,
    )
    await state.update_data(_admin_screen="menu")


async def _render_admin_menu(message: Message, state: FSMContext) -> None:
    """Вернуться к корневому действию админки."""
    await state.set_state(None)
    if not await _edit_admin_body(
        message,
        state,
        titled("Действие", "Выбери действие."),
        admin_menu_kb(),
        HTML_PARSE_MODE,
    ):
        await _send_admin_menu(message, state)
        return
    await state.update_data(_admin_screen="menu")


def _admin_search_prompt_kb() -> InlineKeyboardMarkup:
    """Клавиатура экрана поиска: показать всех сразу."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Показать всех", callback_data="admin:search_all")]
        ]
    )


def _role_word(role: str) -> str:
    """Человеческое название роли для карточки."""
    return {"admin": "администратор", "starosta": "староста"}.get(role, "студент")


def _user_card_text(user: dict) -> str:
    """Текст карточки пользователя из данных БД (плюс живое имя, если есть)."""
    username = str(user.get("username") or "").strip()
    first_name = str(user.get("first_name") or "").strip()
    last_name = str(user.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part)
    live_name = str(user.get("_display_name") or "").strip()
    name = live_name or full_name or (f"@{username}" if username else f"ID {user['user_id']}")

    lines = [f"👤 <b>{esc(name)}</b>"]
    if username and username.lstrip("@").lower() not in name.lower():
        lines.append(f"@{esc(username.lstrip('@'))}")
    lines.append(f"Группа · <b>{esc(str(user.get('group_name') or '—'))}</b>")
    lines.append(f"Роль · <b>{esc(_role_word(str(user.get('role') or 'student')))}</b>")
    lines.append(f"ID · <code>{user['user_id']}</code>")
    return "\n".join(lines)


async def _render_search_results(message: Message, state: FSMContext, query: str) -> None:
    """Показать результаты поиска пользователей."""
    users = await search_users(query)
    await state.update_data(_admin_search_query=query)

    if not users:
        await _edit_admin_body(
            message,
            state,
            titled("Поиск", "Никого не нашёл. Попробуй другой запрос."),
            _admin_search_prompt_kb(),
            HTML_PARSE_MODE,
        )
        await state.update_data(_admin_screen="search")
        return

    shown_users = users[:ADMIN_SEARCH_LIMIT]
    # Подмешиваем живые имена только для показываемых плиток — это дёшево и даёт
    # понятные подписи даже до того, как профиль сохранится в БД.
    shown_users = await _attach_display_names(message.bot, shown_users)

    subtitle = f"Найдено: {len(users)}. Выбери пользователя."
    if len(users) > len(shown_users):
        subtitle = (
            f"Найдено: {len(users)}, показаны первые {len(shown_users)}. "
            "Уточни запрос, чтобы сузить."
        )
    await _edit_admin_body(
        message,
        state,
        titled("Поиск", subtitle),
        admin_search_results_kb(shown_users),
        HTML_PARSE_MODE,
    )
    await state.update_data(_admin_screen="search_results")


async def _render_user_card(message: Message, state: FSMContext, user_id: int) -> bool:
    """Показать карточку пользователя с действиями."""
    user = await get_user(user_id)
    if not user:
        return False
    live_name = await _display_name(message.bot, user_id)
    if live_name and not live_name.startswith("ID "):
        user = {**user, "_display_name": live_name}
    await _edit_admin_body(
        message,
        state,
        _user_card_text(user),
        admin_user_card_kb(user),
        HTML_PARSE_MODE,
    )
    await state.update_data(_admin_screen="card", _admin_card_user=user_id)
    return True


async def _render_admin_users(message: Message, state: FSMContext) -> bool:
    """Показать список студентов для назначения старостой."""
    users = await get_all_users()
    students = [u for u in users if (u.get("role") or "student") == "student"]
    if not students:
        return False
    students = await _attach_display_names(message.bot, students)
    if not await _edit_admin_body(
        message,
        state,
        titled("Назначить старосту", "Выбери пользователя."),
        admin_users_kb(students),
        HTML_PARSE_MODE,
    ):
        return False
    await state.update_data(_admin_screen="set")
    return True


async def _render_admin_starostas(message: Message, state: FSMContext) -> bool:
    """Показать список старост для снятия."""
    starostas = await get_users_by_role("starosta")
    if not starostas:
        return False
    starostas = await _attach_display_names(message.bot, starostas)
    if not await _edit_admin_body(
        message,
        state,
        titled("Снять старосту", "Выбери старосту."),
        admin_starostas_kb(starostas),
        HTML_PARSE_MODE,
    ):
        return False
    await state.update_data(_admin_screen="remove")
    return True


async def handle_admin_back(message: Message, state: FSMContext) -> bool:
    """Обработать кнопку Назад внутри админки."""
    data = await state.get_data()
    if data.get("ui_screen") != "admin":
        return False

    screen = data.get("_admin_screen", "menu")
    if screen in ("set", "remove", "search", "search_results"):
        await _render_admin_menu(message, state)
        return True
    if screen == "card":
        await _render_search_results(message, state, data.get("_admin_search_query", ""))
        return True
    if screen == "set_done":
        if not await _render_admin_users(message, state):
            await _render_admin_menu(message, state)
        return True
    if screen == "remove_done":
        if not await _render_admin_starostas(message, state):
            await _render_admin_menu(message, state)
        return True

    user = await get_user(message.from_user.id)
    role = (user.get("role") or "student") if user else "student"
    sent = await message.answer(
        MAIN_MENU_TEXT,
        reply_markup=main_menu_kb(role, not bool(user and user.get("extra_in_schedule"))),
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
    return True


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    """Команда /admin <пароль> — получить роль админа."""
    await delete_user_message(message)

    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        sent = await message.answer(
            titled("Команда админа", "Использование · /admin пароль"),
            parse_mode=HTML_PARSE_MODE,
        )
        await replace_ui_messages(
            message.bot,
            message.chat.id,
            state,
            [sent.message_id],
            screen="admin",
            clear_state=True,
            last_bot_msg=sent.message_id,
        )
        return

    user_id = message.from_user.id
    if not _admin_user_allowed(user_id):
        logger.warning("Попытка входа в админку от пользователя вне allowlist: %s", user_id)
        sent = await message.answer(no_access_text(), parse_mode=HTML_PARSE_MODE)
        await replace_ui_messages(
            message.bot,
            message.chat.id,
            state,
            [sent.message_id],
            screen="admin",
            clear_state=True,
            last_bot_msg=sent.message_id,
        )
        return

    locked_left = _admin_lock_seconds_left(user_id)
    if locked_left:
        minutes = max(1, locked_left // 60)
        sent = await message.answer(
            titled("Не получилось", f"Слишком много попыток. Повтори через {minutes} мин."),
            parse_mode=HTML_PARSE_MODE,
        )
        await replace_ui_messages(
            message.bot,
            message.chat.id,
            state,
            [sent.message_id],
            screen="admin",
            clear_state=True,
            last_bot_msg=sent.message_id,
        )
        return

    password = parts[1]
    if not ADMIN_PASSWORD:
        sent = await message.answer(
            titled("Не получилось", "Пароль администратора не настроен."),
            parse_mode=HTML_PARSE_MODE,
        )
        await replace_ui_messages(
            message.bot,
            message.chat.id,
            state,
            [sent.message_id],
            screen="admin",
            clear_state=True,
            last_bot_msg=sent.message_id,
        )
        return

    if not _password_matches(password):
        locked_left = _register_admin_failure(user_id)
        logger.warning("Неудачная попытка входа в админку от пользователя %s", user_id)
        if locked_left:
            text = "Слишком много попыток. Вход временно заблокирован."
        else:
            text = "Неверный пароль."
        sent = await message.answer(titled("Не получилось", text), parse_mode=HTML_PARSE_MODE)
        await replace_ui_messages(
            message.bot,
            message.chat.id,
            state,
            [sent.message_id],
            screen="admin",
            clear_state=True,
            last_bot_msg=sent.message_id,
        )
        return

    user = await get_user(user_id)
    if not user:
        sent = await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        await replace_ui_messages(
            message.bot,
            message.chat.id,
            state,
            [sent.message_id],
            screen="admin",
            clear_state=True,
            last_bot_msg=sent.message_id,
        )
        return

    _clear_admin_failures(user_id)
    await set_user_role(user_id, "admin")
    sent = await message.answer(
        titled("Готово", "Права администратора выданы."),
        reply_markup=main_menu_kb("admin", not bool(user.get("extra_in_schedule"))),
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


@router.message(F.text == "⚙️ Админ")
async def on_admin_menu(message: Message, state: FSMContext) -> None:
    """Кнопка «Админ» в главном меню."""
    user = await get_user(message.from_user.id)
    if not user or user.get("role") != "admin":
        await message.answer(no_access_text(), parse_mode=HTML_PARSE_MODE)
        return
    await delete_user_message(message)
    await _send_admin_menu(message, state)
    await state.update_data(_nav_stack=["main_menu"])


async def _guard_admin(callback: CallbackQuery) -> bool:
    """Проверить, что вызвавший — админ. Иначе показать алерт."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return False
    return True


@router.callback_query(F.data == "admin:search")
async def on_admin_search(callback: CallbackQuery, state: FSMContext) -> None:
    """Открыть экран поиска пользователя."""
    if not await _guard_admin(callback):
        return
    await callback.message.edit_text(
        titled("Поиск", "Введи имя, @username, группу или ID. Или покажи всех."),
        reply_markup=_admin_search_prompt_kb(),
        parse_mode=HTML_PARSE_MODE,
    )
    await state.set_state(AdminStates.search_query)
    await state.update_data(_admin_screen="search")
    await callback.answer()


@router.callback_query(F.data == "admin:search_all")
async def on_admin_search_all(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать всех пользователей."""
    if not await _guard_admin(callback):
        return
    await state.set_state(AdminStates.search_query)
    await _render_search_results(callback.message, state, "")
    await callback.answer()


@router.callback_query(F.data == "admin:search_back")
async def on_admin_search_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Вернуться из карточки к результатам поиска."""
    if not await _guard_admin(callback):
        return
    data = await state.get_data()
    await state.set_state(AdminStates.search_query)
    await _render_search_results(callback.message, state, data.get("_admin_search_query", ""))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user:"))
async def on_admin_user_card(callback: CallbackQuery, state: FSMContext) -> None:
    """Открыть карточку пользователя."""
    if not await _guard_admin(callback):
        return
    target_id = int(callback.data.split(":")[1])
    if not await _render_user_card(callback.message, state, target_id):
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    await callback.answer()


@router.message(AdminStates.search_query)
async def on_admin_search_query(message: Message, state: FSMContext) -> None:
    """Обработать введённый запрос поиска."""
    query = (message.text or "").strip()
    await delete_user_message(message)
    await _render_search_results(message, state, query)


@router.callback_query(F.data == "admin:set_starosta")
async def on_set_starosta(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать список пользователей для назначения старостой."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return
    users = await get_all_users()
    # Показываем только студентов
    students = [u for u in users if (u.get("role") or "student") == "student"]
    if not students:
        await callback.answer("Нет студентов для назначения", show_alert=True)
        return
    students = await _attach_display_names(callback.bot, students)
    await callback.message.edit_text(
        titled("Назначить старосту", "Выбери пользователя."),
        reply_markup=admin_users_kb(students),
        parse_mode=HTML_PARSE_MODE,
    )
    await state.update_data(_admin_screen="set")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_set_starosta:"))
async def on_confirm_set_starosta(callback: CallbackQuery, state: FSMContext) -> None:
    """Назначить старосту."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    await set_user_role(target_id, "starosta")
    data = await state.get_data()
    if data.get("_admin_screen") == "card":
        await _render_user_card(callback.message, state, target_id)
        await callback.answer("Назначен старостой")
        return
    target_name = await _display_name(callback.bot, target_id)
    await callback.message.edit_text(
        titled("Готово", f"{esc(target_name)} · староста"),
        parse_mode=HTML_PARSE_MODE,
    )
    await state.update_data(_admin_screen="set_done")
    await callback.answer()


@router.callback_query(F.data == "admin:remove_starosta")
async def on_remove_starosta(callback: CallbackQuery, state: FSMContext) -> None:
    """Показать список старост для снятия."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return
    starostas = await get_users_by_role("starosta")
    if not starostas:
        await callback.answer("Нет старост для снятия", show_alert=True)
        return
    starostas = await _attach_display_names(callback.bot, starostas)
    await callback.message.edit_text(
        titled("Снять старосту", "Выбери старосту."),
        reply_markup=admin_starostas_kb(starostas),
        parse_mode=HTML_PARSE_MODE,
    )
    await state.update_data(_admin_screen="remove")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_rm_starosta:"))
async def on_confirm_remove_starosta(callback: CallbackQuery, state: FSMContext) -> None:
    """Снять старосту."""
    user = await get_user(callback.from_user.id)
    if not user or user.get("role") != "admin":
        await callback.answer("Нет доступа", show_alert=True)
        return
    target_id = int(callback.data.split(":")[1])
    await set_user_role(target_id, "student")
    data = await state.get_data()
    if data.get("_admin_screen") == "card":
        await _render_user_card(callback.message, state, target_id)
        await callback.answer("Снят со старосты")
        return
    target_name = await _display_name(callback.bot, target_id)
    await callback.message.edit_text(
        titled("Готово", f"{esc(target_name)} · студент"),
        parse_mode=HTML_PARSE_MODE,
    )
    await state.update_data(_admin_screen="remove_done")
    await callback.answer()
