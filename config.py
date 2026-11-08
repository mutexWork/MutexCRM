"""Загрузка настроек бота из переменных окружения и файла .env."""

import os

from dotenv import load_dotenv

# Загружаем переменные из .env (существующие переменные окружения не перезаписываются).
load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()

if not BOT_TOKEN or BOT_TOKEN == "your_token_here":
    raise RuntimeError(
        "BOT_TOKEN не задан. Создайте файл .env на основе .env.example "
        "и укажите токен, полученный у @BotFather."
    )

_admin_id_raw: str = os.getenv("ADMIN_ID", "").strip()

try:
    ADMIN_ID: int = int(_admin_id_raw)
except ValueError as exc:
    raise RuntimeError(
        "ADMIN_ID должен быть числом — это ваш Telegram ID. "
        "Проверьте значение ADMIN_ID в файле .env."
    ) from exc

if ADMIN_ID <= 0:
    raise RuntimeError(
        "ADMIN_ID должен быть положительным числом. "
        "Проверьте значение ADMIN_ID в файле .env."
    )
