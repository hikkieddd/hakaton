"""Опциональное хранилище фактов в PostgreSQL.

Включается заданием переменной окружения ``BK_DATABASE_URL``
(например ``postgresql+psycopg://user:pass@localhost:5432/budget``).

Если переменная не задана или библиотека SQLAlchemy не установлена,
бэкенд работает в файловом режиме (CSV/XLSX) без изменений.
"""
from __future__ import annotations

import os
import re
from typing import Optional

import pandas as pd

ENV_DSN = "BK_DATABASE_URL"
TABLE_NAME = os.environ.get("BK_DATABASE_TABLE", "bk_facts")


class StorageBackend:
    """Базовый класс. Реализация-заглушка: режим выключен."""

    enabled: bool = False

    def dsn_safe(self) -> str:
        return ""

    def load_facts(self) -> pd.DataFrame:
        return pd.DataFrame()

    def save_facts(self, df: pd.DataFrame) -> None:
        return None


class PostgresStorage(StorageBackend):
    """Хранилище фактов в PostgreSQL."""

    enabled = True

    def __init__(self, dsn: str, table: str = TABLE_NAME):
        # Импорт здесь, чтобы зависимость была опциональной.
        from sqlalchemy import create_engine

        self.dsn = dsn
        self.table = table
        self.engine = create_engine(dsn, pool_pre_ping=True, future=True)

    def dsn_safe(self) -> str:
        """Скрывает пароль в DSN для логов."""
        return re.sub(r"://([^:/]+):[^@]+@", r"://\1:***@", self.dsn)

    def load_facts(self) -> pd.DataFrame:
        from sqlalchemy import text

        with self.engine.connect() as conn:
            exists = conn.execute(text(
                "SELECT to_regclass(:t) IS NOT NULL AS ok"
            ), {"t": self.table}).scalar()
            if not exists:
                return pd.DataFrame()
            df = pd.read_sql_query(f"SELECT * FROM {self.table}", conn)
        if df.empty:
            return df
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
        if "amount" in df.columns:
            df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        return df

    def save_facts(self, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        # Pandas не дружит с object-колонками типа NaT — приведём к строкам/типам.
        out = df.copy()
        for col in out.columns:
            if out[col].dtype == object:
                out[col] = out[col].astype(str).where(out[col].notna(), None)
        if "date" in out.columns:
            out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out.to_sql(self.table, self.engine, if_exists="replace", index=False, chunksize=2000)


def get_storage() -> StorageBackend:
    """Создаёт активное хранилище по переменным окружения.

    Никогда не падает: при любых ошибках возвращает выключенный backend.
    """
    dsn = os.environ.get(ENV_DSN)
    if not dsn:
        return StorageBackend()
    try:
        # Проверка наличия SQLAlchemy.
        import sqlalchemy  # noqa: F401
    except Exception as exc:
        print(f"[storage] SQLAlchemy не установлен: {exc} — режим PostgreSQL отключён")
        return StorageBackend()
    try:
        return PostgresStorage(dsn)
    except Exception as exc:
        print(f"[storage] не удалось инициализировать PostgreSQL ({exc}) — переход в файловый режим")
        return StorageBackend()
