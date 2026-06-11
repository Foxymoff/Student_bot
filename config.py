"""
Конфигурация бота: загрузка токена и путей.
"""

import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()


def _parse_int_set(value: str) -> set[int]:
    """Разобрать список Telegram ID из env-переменной."""
    result: set[int] = set()
    for raw_item in value.replace(";", ",").split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            result.add(int(item))
        except ValueError as exc:
            raise ValueError("ADMIN_USER_IDS должен содержать только числовые Telegram ID") from exc
    return result


# Токен бота из .env
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Пароль администратора из .env
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "")

# Необязательный allowlist Telegram ID, которым разрешена команда /admin.
# Если список пустой, работает только проверка ADMIN_PASSWORD.
ADMIN_USER_IDS: set[int] = _parse_int_set(os.getenv("ADMIN_USER_IDS", ""))

# Корневая директория проекта
BASE_DIR: Path = Path(__file__).resolve().parent

# Папка с JSON-файлами расписания
DATA_DIR: Path = BASE_DIR / "data"

# Путь к файлу базы данных (DB_DIR позволяет вынести БД в отдельную директорию, напр. в Docker)
DB_PATH: Path = Path(os.getenv("DB_DIR", str(BASE_DIR))) / "bot.db"

# Часовой пояс для дат расписания и уведомлений
APP_TIMEZONE = ZoneInfo("Europe/Moscow")


def app_now() -> datetime.datetime:
    """Текущее время в часовом поясе бота."""
    return datetime.datetime.now(APP_TIMEZONE)


def app_today() -> datetime.date:
    """Текущая дата в часовом поясе бота."""
    return app_now().date()

# Соответствие групп → файлам расписания
GROUP_FILES: dict[str, str] = {
    "ИСП-25-1": "isp_25_1.json",
    "ИСП-25-2": "isp_25_2.json",
    "МР-25": "mr_25.json",
}

# Соответствие групп → файлам расписания доп. занятий.
EXTRA_GROUP_FILES: dict[str, str] = {
    "ИСП-25-1": "isp_25_1_extra.json",
    "ИСП-25-2": "isp_25_2_extra.json",
    "МР-25": "mr_25_extra.json",
}

EXTRA_DATA_DIR: Path = Path(os.getenv("EXTRA_DATA_DIR", str(DATA_DIR)))

# Список доступных групп
GROUPS: list[str] = list(GROUP_FILES.keys())

# Словарь сокращений длинных названий предметов
SUBJECT_SHORT: dict[str, str] = {
    "Цифровая инженерия и проектное мышление": "Цифр. инженерия",
    "Разговоры о важном": "Разг. о важном",
    "Компьютерное моделирование": "Комп. моделирование",
    "Продвинутая математика": "Прод. мат",
    "Медиа-мастерская": "Медиа-маст.",
    "Бизнес-лаборатория": "Бизнес-лаб",
    "Инженерный клуб Иннотех": "Иннотех",
    "Разработка игр на движке GODOT ENGINE": "GODOT",
    "Английский язык для IT-среды": "Англ. IT",
    "Иностранный язык": "Ин. язык",
}

# Словарь сокращений аудиторий
ROOM_SHORT: dict[str, str] = {
    "Спорткомплекс": "СК",
    "Конференц-зал": "КЗ",
    "Школа": "ШК",
}

# Подгруппы по английскому: номер → (уровень, преподаватель)
ENG_SUBGROUPS: dict[str, dict[int, str]] = {
    "ИСП-25-1": {1: "Сильная · Шарафутдинова Анита", 2: "Слабая · Юсупова Луиза"},
    "ИСП-25-2": {1: "Сильная · Юсупова Луиза", 2: "Слабая · Шарафутдинова Анита"},
    "МР-25":    {1: "Сильная · Шарафутдинова Анита", 2: "Слабая · Юсупова Луиза"},
}
