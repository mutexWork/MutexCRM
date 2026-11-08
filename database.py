"""Работа с базой данных SQLite: инициализация и операции с заявками."""

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

DB_PATH: Path = Path(__file__).resolve().parent / "requests.db"


def _connect() -> sqlite3.Connection:
    """Создаёт соединение с базой данных."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    """Создаёт таблицу requests, если она ещё не существует."""
    with closing(_connect()) as connection, connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                task TEXT NOT NULL,
                contact TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )


def add_request(user_id: int, name: str, task: str, contact: str) -> int:
    """Добавляет новую заявку и возвращает её id."""
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with closing(_connect()) as connection, connection:
        cursor = connection.execute(
            """
            INSERT INTO requests (user_id, name, task, contact, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, name, task, contact, created_at),
        )
        return int(cursor.lastrowid)


def get_requests(limit: int | None = None) -> list[sqlite3.Row]:
    """Возвращает заявки, начиная с самых новых."""
    query = "SELECT * FROM requests ORDER BY id DESC"
    params: tuple[Any, ...] = ()

    if limit is not None:
        query += " LIMIT ?"
        params = (limit,)

    with closing(_connect()) as connection:
        return connection.execute(query, params).fetchall()
