"""Общие тексты и HTML-стиль служебных сообщений."""

import html as _html

HTML_PARSE_MODE = "HTML"
MAIN_MENU_TEXT = "<b>Главное меню</b>"


def esc(value: object) -> str:
    """Экранировать значение для HTML-сообщения Telegram."""
    return _html.escape(str(value))


def title(text: str) -> str:
    """Жирный заголовок экрана."""
    return f"<b>{esc(text)}</b>"


def titled(title_text: str, body: str | None = None) -> str:
    """Заголовок + короткий текст через пустую строку."""
    if body:
        return f"{title(title_text)}\n\n{body}"
    return title(title_text)


def register_required_text() -> str:
    """Единый текст для незарегистрированного пользователя."""
    return titled("Нужна регистрация", "Открой /start.")


def no_access_text() -> str:
    """Единый текст для недоступного раздела."""
    return titled("Нет доступа", "Эта команда недоступна для твоей роли.")
