"""
Обработчик блока «Домашнее задание»: просмотр и добавление через FSM.
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_user, add_homework, get_homework, get_homework_subjects
from keyboards import homework_action_kb, homework_subjects_kb, back_to_menu_kb, main_menu_kb

logger = logging.getLogger(__name__)
router = Router()


# ── FSM состояния ─────────────────────────────────────────


class AddHomework(StatesGroup):
    """Состояния для добавления ДЗ."""
    subject = State()   # ввод предмета
    text = State()      # ввод текста ДЗ


# ── Хендлеры ──────────────────────────────────────────────


@router.message(F.text == "📚 Домашнее задание")
async def on_homework_menu(message: Message, state: FSMContext) -> None:
    """Кнопка «Домашнее задание» в главном меню."""
    await state.clear()
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся: /start")
        return
    await message.answer(
        "📚 Домашнее задание\nВыбери действие:",
        reply_markup=homework_action_kb(),
    )


# ── Просмотр ДЗ ───────────────────────────────────────────


@router.callback_query(F.data == "hw:view")
async def on_hw_view(callback: CallbackQuery) -> None:
    """Показать список предметов, по которым есть ДЗ."""
    subjects = await get_homework_subjects(callback.from_user.id)
    if not subjects:
        await callback.message.answer(
            "У тебя пока нет записей домашнего задания.",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return
    await callback.message.answer(
        "Выбери предмет:",
        reply_markup=homework_subjects_kb(subjects),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("hw_subject:"))
async def on_hw_subject_selected(callback: CallbackQuery) -> None:
    """Показать ДЗ по выбранному предмету."""
    subject = callback.data.split(":", 1)[1]
    records = await get_homework(callback.from_user.id, subject)
    if not records:
        await callback.message.answer(
            f"По предмету «{subject}» записей нет.",
            reply_markup=back_to_menu_kb(),
        )
        await callback.answer()
        return

    lines = [f"📚 ДЗ по предмету: *{subject}*\n"]
    for i, rec in enumerate(records, 1):
        lines.append(f"{i}. {rec['text']}")
        lines.append(f"   _добавлено: {rec['created_at']}_\n")

    await callback.message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=back_to_menu_kb(),
    )
    await callback.answer()


# ── Добавление ДЗ ─────────────────────────────────────────


@router.callback_query(F.data == "hw:add")
async def on_hw_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Начало добавления ДЗ — запрос предмета."""
    await callback.message.answer(
        "Введи название предмета:"
    )
    await state.set_state(AddHomework.subject)
    await callback.answer()


@router.message(AddHomework.subject)
async def on_hw_subject_input(message: Message, state: FSMContext) -> None:
    """Получили предмет — запрашиваем текст ДЗ."""
    await state.update_data(subject=message.text.strip())
    await message.answer("Теперь введи текст домашнего задания:")
    await state.set_state(AddHomework.text)


@router.message(AddHomework.text)
async def on_hw_text_input(message: Message, state: FSMContext) -> None:
    """Получили текст ДЗ — сохраняем."""
    data = await state.get_data()
    subject = data["subject"]
    hw_text = message.text.strip()

    await add_homework(message.from_user.id, subject, hw_text)
    await state.clear()
    await message.answer(
        f"✅ ДЗ по предмету «{subject}» сохранено!",
        reply_markup=main_menu_kb(),
    )
