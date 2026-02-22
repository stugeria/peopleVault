import sqlite3
import os

DB_PATH = os.getenv("DB_PATH", "users.db")


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                notion_token TEXT NOT NULL,
                database_id TEXT NOT NULL
            )
        """)


def get_user(telegram_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT notion_token, database_id FROM users WHERE telegram_id = ?",
            (telegram_id,)
        ).fetchone()
    return {"notion_token": row[0], "database_id": row[1]} if row else None


def save_user(telegram_id: int, notion_token: str, database_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO users (telegram_id, notion_token, database_id)
            VALUES (?, ?, ?)
        """, (telegram_id, notion_token, database_id))


def delete_user(telegram_id: int):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
