"""Обработчики Telegram-бота для приёма заявок."""

import csv
import logging
import sqlite3
import tempfile
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import ADMIN_ID
from database import add_request, get_requests

logger = logging.getLogger(__name__)

router = Router(name="crm_requests")

# Ограничение Telegram — 4096 символов. Оставляем запас для заголовка.
MAX_MESSAGE_LENGTH = 3500


class RequestForm(StatesGroup):
    """Шаги заполнения заявки."""

    name = State()
    task = State()
    contact = State()


# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------


def main_menu_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Оставить заявку", callback_data="request:start")
    return builder.as_markup()


def cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="request:cancel")
    return builder.as_markup()


def admin_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Посмотреть заявки", callback_data="admin:list")
    builder.button(text="📊 Экспорт в CSV", callback_data="admin:export")
    builder.adjust(1)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


async def ensure_admin(callback: CallbackQuery) -> bool:
    """Проверяет, что нажатие пришло от администратора."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Доступ запрещён.", show_alert=True)
        return False
    return True


def format_request(row: sqlite3.Row) -> str:
    """Форматирует одну заявку для вывода в чат."""
    task = row["task"]
    if len(task) > 300:
        task = f"{task[:300]}…"

    return (
        f"№{row['id']} — {row['created_at']}\n"
        f"👤 Имя: {row['name']}\n"
        f"📋 Задача: {task}\n"
        f"📞 Контакт: {row['contact']}\n"
        f"🆔 Telegram ID: {row['user_id']}"
    )


def split_into_messages(
    blocks: list[str], limit: int = MAX_MESSAGE_LENGTH
) -> list[str]:
    """Склеивает блоки в сообщения, не превышающие лимит Telegram."""
    messages: list[str] = []
    current: list[str] = []
    current_length = 0

    for block in blocks:
        block_length = len(block) + 2  # +2 — разделитель "\n\n"
        if current and current_length + block_length > limit:
            messages.append("\n\n".join(current))
            current = []
            current_length = 0
        current.append(block)
        current_length += block_length

    if current:
        messages.append("\n\n".join(current))

    return messages


# ---------------------------------------------------------------------------
# Команды
# ---------------------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        f"👋 Здравствуйте, {message.from_user.full_name}!\n\n"
        "Я бот приёма заявок. Оставьте заявку — и мы свяжемся с вами.\n\n"
        "Нажмите кнопку ниже, чтобы начать.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    if await state.get_state() is None:
        await message.answer(
            "Сейчас нечего отменять.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await state.clear()
    await message.answer(
        "❌ Заполнение заявки отменено.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext) -> None:
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ У вас нет доступа к этой команде.")
        return

    await state.clear()
    await message.answer(
        "🛠 Панель администратора\n\nВыберите действие:",
        reply_markup=admin_keyboard(),
    )


# ---------------------------------------------------------------------------
# Заявка: запуск и отмена
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "request:start")
async def start_request(
    callback: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    await state.set_state(RequestForm.name)
    await callback.answer()
    await bot.send_message(
        callback.from_user.id,
        "Шаг 1/3. Как вас зовут?",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(F.data == "request:cancel")
async def cancel_request(
    callback: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    await state.clear()
    await callback.answer("Заполнение отменено")

    if callback.message is not None:
        try:
            await bot.edit_message_reply_markup(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                reply_markup=None,
            )
        except TelegramAPIError:
            pass

    await bot.send_message(
        callback.from_user.id,
        "❌ Заполнение заявки отменено.",
        reply_markup=main_menu_keyboard(),
    )


# ---------------------------------------------------------------------------
# Заявка: шаги FSM
# ---------------------------------------------------------------------------


@router.message(RequestForm.name, F.text)
async def process_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()

    if len(name) < 2:
        await message.answer("Пожалуйста, укажите имя (минимум 2 символа).")
        return

    if len(name) > 100:
        await message.answer("Имя слишком длинное. Максимум 100 символов.")
        return

    await state.update_data(name=name)
    await state.set_state(RequestForm.task)
    await message.answer(
        "Шаг 2/3. Опишите задачу или вопрос.",
        reply_markup=cancel_keyboard(),
    )


@router.message(RequestForm.task, F.text)
async def process_task(message: Message, state: FSMContext) -> None:
    task = (message.text or "").strip()

    if len(task) < 5:
        await message.answer("Опишите задачу подробнее (минимум 5 символов).")
        return

    if len(task) > 2000:
        await message.answer("Описание слишком длинное. Максимум 2000 символов.")
        return

    await state.update_data(task=task)
    await state.set_state(RequestForm.contact)
    await message.answer(
        "Шаг 3/3. Как с вами связаться? Укажите телефон, email или @username.",
        reply_markup=cancel_keyboard(),
    )


@router.message(RequestForm.contact, F.text)
async def process_contact(
    message: Message, state: FSMContext, bot: Bot
) -> None:
    contact = (message.text or "").strip()

    if len(contact) < 3:
        await message.answer(
            "Контакт слишком короткий. Укажите телефон, email или @username."
        )
        return

    if len(contact) > 200:
        await message.answer("Контакт слишком длинный. Максимум 200 символов.")
        return

    data = await state.get_data()
    name = data.get("name", "")
    task = data.get("task", "")

    if not name or not task:
        await state.clear()
        await message.answer(
            "Не удалось восстановить данные заявки. Пожалуйста, начните заново.",
            reply_markup=main_menu_keyboard(),
        )
        return

    try:
        request_id = add_request(message.from_user.id, name, task, contact)
    except sqlite3.Error:
        logger.exception("Не удалось сохранить заявку в БД")
        await state.clear()
        await message.answer(
            "⚠️ Не удалось сохранить заявку. Попробуйте ещё раз позже.",
            reply_markup=main_menu_keyboard(),
        )
        return

    await state.clear()

    await message.answer(
        f"✅ Спасибо! Ваша заявка №{request_id} принята.\n"
        "Мы свяжемся с вами в ближайшее время.",
        reply_markup=main_menu_keyboard(),
    )

    username = (
        f"@{message.from_user.username}"
        if message.from_user.username
        else "не указан"
    )
    admin_text = (
        "🔔 Новая заявка\n\n"
        f"№{request_id}\n"
        f"👤 Имя: {name}\n"
        f"📋 Задача: {task}\n"
        f"📞 Контакт: {contact}\n"
        f"🆔 Telegram ID: {message.from_user.id}\n"
        f"🔗 Username: {username}"
    )

    try:
        await bot.send_message(ADMIN_ID, admin_text)
    except TelegramAPIError:
        logger.exception("Не удалось отправить уведомление администратору")


# ---------------------------------------------------------------------------
# Админ-панель
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:list")
async def show_requests(callback: CallbackQuery, bot: Bot) -> None:
    if not await ensure_admin(callback):
        return

    try:
        rows = get_requests()
    except sqlite3.Error:
        logger.exception("Не удалось получить заявки из БД")
        await callback.answer("⚠️ Ошибка базы данных.", show_alert=True)
        return

    if not rows:
        await callback.answer("📭 Заявок пока нет.", show_alert=True)
        return

    await callback.answer()

    messages = split_into_messages([format_request(row) for row in rows])
    messages[0] = f"📋 Всего заявок: {len(rows)}\n\n{messages[0]}"

    for text in messages:
        await bot.send_message(callback.from_user.id, text)


@router.callback_query(F.data == "admin:export")
async def export_requests(callback: CallbackQuery, bot: Bot) -> None:
    if not await ensure_admin(callback):
        return

    try:
        rows = get_requests()
    except sqlite3.Error:
        logger.exception("Не удалось получить заявки из БД")
        await callback.answer("⚠️ Ошибка базы данных.", show_alert=True)
        return

    if not rows:
        await callback.answer(
            "📭 Заявок пока нет — экспортировать нечего.",
            show_alert=True,
        )
        return

    await callback.answer()

    file_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            prefix="requests_",
            delete=False,
            encoding="utf-8-sig",
            newline="",
        ) as csv_file:
            file_path = Path(csv_file.name)
            writer = csv.writer(csv_file, delimiter=";")
            writer.writerow(
                ["ID", "User ID", "Имя", "Задача", "Контакт", "Дата создания"]
            )
            for row in rows:
                writer.writerow(
                    [
                        row["id"],
                        row["user_id"],
                        row["name"],
                        row["task"],
                        row["contact"],
                        row["created_at"],
                    ]
                )

        await bot.send_document(
            chat_id=callback.from_user.id,
            document=FSInputFile(file_path, filename="requests.csv"),
            caption=f"📊 Экспорт заявок: {len(rows)} шт.",
        )
    except OSError:
        logger.exception("Не удалось создать CSV-файл")
        await bot.send_message(
            callback.from_user.id,
            "⚠️ Не удалось создать CSV-файл. Попробуйте позже.",
        )
    except TelegramAPIError:
        logger.exception("Не удалось отправить CSV-файл")
        await bot.send_message(
            callback.from_user.id,
            "⚠️ Не удалось отправить файл. Попробуйте позже.",
        )
    finally:
        if file_path is not None:
            file_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Нетекстовые сообщения внутри FSM
# ---------------------------------------------------------------------------


@router.message(RequestForm.name)
async def process_name_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте имя текстовым сообщением.")


@router.message(RequestForm.task)
async def process_task_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, опишите задачу текстом.")


@router.message(RequestForm.contact)
async def process_contact_invalid(message: Message) -> None:
    await message.answer("Пожалуйста, отправьте контакт текстовым сообщением.")


# ---------------------------------------------------------------------------
# Прочие сообщения
# ---------------------------------------------------------------------------


@router.message(F.text)
async def fallback_text(message: Message) -> None:
    if (message.text or "").startswith("/"):
        await message.answer("🤔 Неизвестная команда. Используйте /start.")
        return

    await message.answer(
        "Чтобы оставить заявку, нажмите кнопку ниже.",
        reply_markup=main_menu_keyboard(),
    )


@router.message()
async def fallback_other(message: Message) -> None:
    await message.answer(
        "Пожалуйста, отправьте текстовое сообщение или используйте /start."
    )
