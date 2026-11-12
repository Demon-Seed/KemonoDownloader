"""Shared SQLite plumbing for the app's small stores.

``HashDB``, ``DownloadHistoryDB`` and ``CreatorConfigStore`` each keep their
own database file but want the same policy: one connection per call (safe
across threads), serialised by a lock, WAL journalling, and rows addressed by
column name. Only the tables and the queries differ, so those live in the
subclasses.
"""

import os
import sqlite3
import threading


class SQLiteStore:
    """Thread-safe SQLite database file with one connection per call."""

    #: File name inside the directory passed to ``__init__``.
    DB_FILENAME = ""

    def __init__(self, directory: str):
        os.makedirs(directory, exist_ok=True)
        self.db_path = os.path.join(directory, self.DB_FILENAME)
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new connection (one per call - safe for threads)."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create this store's tables. Subclasses implement it."""
        raise NotImplementedError

    def _count_rows(self, table: str) -> int:
        """Return how many rows *table* holds."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
                return row["cnt"] if row else 0
            finally:
                conn.close()

    def _delete_all(self, table: str) -> None:
        """Remove every row from *table*."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(f"DELETE FROM {table}")
                conn.commit()
            finally:
                conn.close()
