"""
Обработчик блока «Дедлайны»: просмотр и добавление через FSM.
"""

import logging
import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_user, add_deadline, get_deadlines
from keyboards import deadlines_action_kb, back_to_menu_kb, main_menu_kb

logger = logging.getLogger(__name__)
router = Router()


# ── FSM состояния ─────────────────────────────────────────


class AddDeadline(StatesGroup):
    """Состояния для добавления дедлайна."""
    title = State()         # ввод названия
    deadline_date = State()  # ввод даты


# ── Хендлеры ──────────────────────────────────────────────


@router.message(F.text == "⏰ Дедлайны")
async def on_deadlines_menu(message: Message, state: FSMContext) -> None:
    """Кнопка «Дедлайны» в главном меню."""
    await state.clear()
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await message.answer(
        "⏰ Дедлайны\nВыбери действие:",
        reply_markup=deadlines_action_kb(),
    )


# ── Просмотр дедлайнов ────────────────────────────────────


@router.callback_query(F.data == "dl:view")
async def on_dl_view(callback: CallbackQuery) -> None:
    """Показать список дедлайнов."""
    records = await get_deadlines(callback.from_user.id)
    if not records:
        await callback.message.answer(
            "У тебя нет дедлайнов. Добавь первый! ✨",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return

    today = datetime.date.today()
    lines = ["⏰ *Твои дедлайны:*\n"]

    for rec in records:
        dl_date = datetime.date.fromisoformat(rec["deadline_date"])
        days_left = (dl_date - today).days
        # Пометка 🔥 если до дедлайна 3 дня или менее
        fire = " 🔥" if 0 <= days_left <= 3 else ""
        date_str = dl_date.strftime("%d.%m.%Y")

        if days_left < 0:
            status = "(просрочен)"
        elif days_left == 0:
            status = "(сегодня!)"
        elif days_left == 1:
            status = "(завтра)"
        else:
            status = f"(через {days_left} дн.)"

        lines.append(f"• *{rec['title']}*{fire}")
        lines.append(f"  📅 {date_str} {status}\n")

    await callback.message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


# ── Добавление дедлайна ───────────────────────────────────


@router.callback_query(F.data == "dl:add")
async def on_dl_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления дедлайна — запрос названия."""
    await callback.message.answer("Введи название дедлайна:")
    await state.set_state(AddDeadline.title)
    await callback.answer()


@router.message(AddDeadline.title)
async def on_dl_title_input(message: Message, state: FSMContext) -> None:
    """Получили название — запрашиваем дату."""
    await state.update_data(title=message.text.strip())
    await message.answer(
        "Введи дату дедлайна в формате ДД.ММ.ГГГГ\n"
        "(например, 15.03.2026):"
    )
    await state.set_state(AddDeadline.deadline_date)


@router.message(AddDeadline.deadline_date)
async def on_dl_date_input(message: Message, state: FSMContext) -> None:
    """Получили дату — валидируем и сохраняем."""
    raw = message.text.strip()
    try:
        parsed = datetime.datetime.strptime(raw, "%d.%m.%Y").date()
    except ValueError:
        await message.answer(
            "❌ Неверный формат даты. Введи дату в формате ДД.ММ.ГГГГ\n"
            "(например, 15.03.2026):"
        )
        return  # Остаёмся в том же состоянии

    data = await state.get_data()
    title = data["title"]
    # Сохраняем в ISO формате (YYYY-MM-DD) для удобства сортировки
    await add_deadline(message.from_user.id, title, parsed.isoformat())
    await state.clear()
    await message.answer(
        f"✅ Дедлайн «{title}» на {raw} сохранён!",
        reply_markup=main_menu_kb(),
    )
