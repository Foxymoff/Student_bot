"""
Клавиатуры бота: reply-кнопки и inline-кнопки.
"""

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from config import GROUPS


# ── Reply-клавиатуры ──────────────────────────────────────


def main_menu_kb() -> ReplyKeyboardMarkup:
    """Главное меню бота."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 Расписание"), KeyboardButton(text="📚 Домашнее задание")],
            [KeyboardButton(text="⏰ Дедлайны"), KeyboardButton(text="💪 Мотивация")],
        ],
        resize_keyboard=True,
    )


# ── Inline-клавиатуры ─────────────────────────────────────


def group_select_kb() -> InlineKeyboardMarkup:
    """Выбор группы при регистрации."""
    buttons = [
        [InlineKeyboardButton(text=g, callback_data=f"group:{g}")]
        for g in GROUPS
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def schedule_period_kb() -> InlineKeyboardMarkup:
    """Выбор периода расписания."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Сегодня", callback_data="schedule:today"),
                InlineKeyboardButton(text="Завтра", callback_data="schedule:tomorrow"),
            ],
            [
                InlineKeyboardButton(text="На неделю", callback_data="schedule:week"),
            ],
            [
                InlineKeyboardButton(text="След. неделя", callback_data="schedule:next_week"),
            ],
            [
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"),
            ],
        ]
    )


def homework_action_kb() -> InlineKeyboardMarkup:
    """Действия с домашним заданием."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📖 Просмотреть ДЗ", callback_data="hw:view"),
                InlineKeyboardButton(text="➕ Добавить ДЗ", callback_data="hw:add"),
            ],
            [
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"),
            ],
        ]
    )


def homework_subjects_kb(subjects: list[str]) -> InlineKeyboardMarkup:
    """Кнопки выбора предмета для просмотра ДЗ."""
    buttons = [
        [InlineKeyboardButton(text=s, callback_data=f"hw_subject:{s}")]
        for s in subjects
    ]
    buttons.append(
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    )
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def deadlines_action_kb() -> InlineKeyboardMarkup:
    """Действия с дедлайнами."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Мои дедлайны", callback_data="dl:view"),
                InlineKeyboardButton(text="➕ Добавить", callback_data="dl:add"),
            ],
            [
                InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu"),
            ],
        ]
    )


def back_to_menu_kb() -> InlineKeyboardMarkup:
    """Кнопка возврата в главное меню."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")],
        ]
    )
