"""
Простые информационные разделы главного меню.
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from database import get_user
from handlers.start import push_nav
from keyboards import back_kb
from message_style import HTML_PARSE_MODE, register_required_text
from message_style import title as styled_title
from ui_messages import delete_user_message, replace_ui_messages

router = Router()


INFO_SCREENS: dict[str, tuple[str, str]] = {
    "Полезные ссылки": (
        "Полезные ссылки",
        "<b>Спорткомплекс</b> · запись и расписание\n"
        "https://sport.innopolis.university/\n\n"
        "<b>Кампус</b> · общежитие и размещение\n"
        "https://hotel.innopolis.university/",
    ),
}

INFO_ALIASES: dict[str, str] = {
    "Полезные ссылки": "Полезные ссылки",
    "🔗Полезные ссылки": "Полезные ссылки",
    "🔗 Полезные ссылки": "Полезные ссылки",
    "Спорткомплекс": "Полезные ссылки",
    "🏃Спорткомплекс": "Полезные ссылки",
    "🏃 Спорткомплекс": "Полезные ссылки",
    "Кампус": "Полезные ссылки",
    "🏨Кампус": "Полезные ссылки",
    "🏨 Кампус": "Полезные ссылки",
}


@router.message(F.text.in_(set(INFO_ALIASES)))
async def on_info_screen(message: Message, state: FSMContext) -> None:
    """Открыть информационный раздел с кнопкой Назад."""
    user = await get_user(message.from_user.id)
    if not user:
        await message.answer(register_required_text(), parse_mode=HTML_PARSE_MODE)
        return

    await delete_user_message(message)

    screen_key = INFO_ALIASES[message.text]
    screen_title, text = INFO_SCREENS[screen_key]

    header = await message.answer(styled_title(screen_title), reply_markup=back_kb(), parse_mode=HTML_PARSE_MODE)
    body = await message.answer(text, parse_mode=HTML_PARSE_MODE)
    await replace_ui_messages(
        message.bot,
        message.chat.id,
        state,
        [header.message_id, body.message_id],
        screen="info",
        clear_state=True,
        last_bot_msg=header.message_id,
        last_info_msg=body.message_id,
    )
    await push_nav(state, "info_screen")
