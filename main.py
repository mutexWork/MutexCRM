"""Точка входа: запуск Telegram-бота в режиме polling."""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database import init_db
from handlers import router


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    init_db()

    bot = Bot(token=BOT_TOKEN)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Бот запущен. Для остановки нажмите Ctrl+C.")
        await dispatcher.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
