"""
Обработчик /start и выбора группы.
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart

from database import get_user, add_user
from keyboards import group_select_kb, main_menu_kb

logger = logging.getLogger(__name__)
router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """Команда /start — приветствие и выбор группы."""
    user = await get_user(message.from_user.id)
    if user:
        # Пользователь уже зарегистрирован
        await message.answer(
            f"С возвращением! Твоя группа: {user['group_name']}\n"
            "Выбери действие в меню 👇",
            reply_markup=main_menu_kb(),
        )
    else:
        # Новый пользователь — предлагаем выбрать группу
        await message.answer(
            "Привет! 👋 Я — Ассистент студента.\n"
            "Помогу с расписанием, домашкой и дедлайнами.\n\n"
            "Для начала выбери свою группу:",
            reply_markup=group_select_kb(),
        )


@router.callback_query(F.data.startswith("group:"))
async def on_group_selected(callback: CallbackQuery) -> None:
    """Обработка выбора группы."""
    group_name = callback.data.split(":", 1)[1]
    await add_user(callback.from_user.id, group_name)
    await callback.message.edit_text(
        f"Отлично! Группа {group_name} сохранена ✅"
    )
    await callback.message.answer(
        "Добро пожаловать! Выбери действие 👇",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def on_main_menu(callback: CallbackQuery) -> None:
    """Возврат в главное меню по inline-кнопке."""
    await callback.message.answer(
        "Главное меню 👇",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()
