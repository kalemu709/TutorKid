"""Postgres access and schema migrations."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS_DIR = ROOT / "migrations"


class Database:
    def __init__(self, database_url: str, min_size: int = 1, max_size: int = 10):
        self.database_url = database_url
        self.pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            kwargs={"row_factory": dict_row, "autocommit": False},
            open=True,
        )

    def close(self) -> None:
        self.pool.close()

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        with self.pool.connection() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def fetchone(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> Optional[dict]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                return cur.fetchone()

    def fetchall(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> list[dict]:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                return list(cur.fetchall())

    def execute(self, sql: str, params: Optional[tuple[Any, ...]] = None) -> None:
        with self.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())


def apply_migrations(database_url: str) -> list[str]:
    """Apply SQL files in migrations/ that are not yet recorded."""
    applied: list[str] = []
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version text PRIMARY KEY,
              applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        conn.commit()
        existing = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        files = sorted(path for path in MIGRATIONS_DIR.glob("*.sql") if path.is_file())
        for path in files:
            version = path.name
            if version in existing:
                continue
            sql = path.read_text(encoding="utf-8")
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
            applied.append(version)
    return applied


def database_url_from_env() -> Optional[str]:
    return os.environ.get("DATABASE_URL", "").strip() or None
