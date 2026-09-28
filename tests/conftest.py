import os
import tempfile

os.environ.setdefault("BOT_TOKEN", "test-token")
os.environ.setdefault("ADMIN_PASSWORD", "test-password")
# База тестов — во временной папке: случайный доступ к БД не создаст bot.db в репозитории.
os.environ.setdefault("DB_DIR", tempfile.mkdtemp(prefix="student-bot-tests-"))
