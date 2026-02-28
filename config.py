"""
Конфигурация бота: загрузка токена и путей.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения из .env
load_dotenv()

# Токен бота из .env
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Корневая директория проекта
BASE_DIR: Path = Path(__file__).resolve().parent

# Папка с JSON-файлами расписания
DATA_DIR: Path = BASE_DIR / "data"

# Путь к файлу базы данных (DB_DIR позволяет вынести БД в отдельную директорию, напр. в Docker)
DB_PATH: Path = Path(os.getenv("DB_DIR", str(BASE_DIR))) / "bot.db"

# Соответствие групп → файлам расписания
GROUP_FILES: dict[str, str] = {
    "ИСП-25-1": "isp_25_1.json",
    "ИСП-25-2": "isp_25_2.json",
    "МР-25": "mr_25.json",
}

# Список доступных групп
GROUPS: list[str] = list(GROUP_FILES.keys())

# Время ежедневной рассылки расписания (часы, минуты)
DAILY_SCHEDULE_HOUR: int = 8
DAILY_SCHEDULE_MINUTE: int = 0
