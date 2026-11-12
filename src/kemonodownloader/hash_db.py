"""SQLite-based file hash storage for deduplication.

Replaces the old file_hashes.json approach with a proper SQLite database
for better concurrent access, data integrity, and performance.
"""

import json
import os
from typing import Optional

from kemonodownloader.sqlite_store import SQLiteStore


class HashDB(SQLiteStore):
    """Thread-safe SQLite database for storing file hashes.

    Stores URL hashes mapped to file paths and content hashes
    to enable file deduplication across downloads.
    """

    DB_FILENAME = "file_hashes.db"

    def __init__(self, directory: str):
        """Initialise the hash database.

        Parameters
        ----------
        directory:
            Directory where the database file will be stored.
        """
        super().__init__(directory)
        self._migrate_json(directory)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create table if not yet present and run schema migrations."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS file_hashes (
                        url_hash   TEXT PRIMARY KEY,
                        file_path  TEXT NOT NULL,
                        file_hash  TEXT NOT NULL,
                        url        TEXT NOT NULL,
                        file_size  INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.commit()
                # Migrate: add file_size column for databases created before
                # this column existed.  PRAGMA table_info returns one row per
                # column; if file_size is absent we add it.
                columns = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(file_hashes)").fetchall()
                }
                if "file_size" not in columns:
                    conn.execute(
                        "ALTER TABLE file_hashes "
                        "ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0"
                    )
                    conn.commit()
            finally:
                conn.close()

    def _migrate_json(self, directory: str) -> None:
        """One-time migration: import data from legacy ``file_hashes.json``."""
        json_path = os.path.join(directory, "file_hashes.json")
        if not os.path.exists(json_path):
            return
        try:
            with open(json_path, "r") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or not data:
                return
            with self._lock:
                conn = self._get_connection()
                try:
                    for url_hash, entry in data.items():
                        conn.execute(
                            """
                            INSERT OR IGNORE INTO file_hashes
                            (url_hash, file_path, file_hash, url, file_size)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                url_hash,
                                entry.get("file_path", ""),
                                entry.get("file_hash", ""),
                                entry.get("url", ""),
                                entry.get("file_size", 0),
                            ),
                        )
                    conn.commit()
                finally:
                    conn.close()
            # Rename the old JSON so it is not re-imported
            backup_path = json_path + ".migrated"
            try:
                os.rename(json_path, backup_path)
            except OSError:
                pass
        except (json.JSONDecodeError, IOError, OSError):
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def lookup(self, url_hash: str) -> Optional[dict]:
        """Return the stored entry for *url_hash*, or ``None``.

        Returns a dict with keys ``file_path``, ``file_hash``, ``url``,
        ``file_size``.
        """
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT file_path, file_hash, url, file_size "
                    "FROM file_hashes WHERE url_hash = ?",
                    (url_hash,),
                ).fetchone()
                if row:
                    return {
                        "file_path": row["file_path"],
                        "file_hash": row["file_hash"],
                        "url": row["url"],
                        "file_size": row["file_size"],
                    }
                return None
            finally:
                conn.close()

    def store(
        self,
        url_hash: str,
        file_path: str,
        file_hash: str,
        url: str,
        file_size: int = 0,
    ) -> None:
        """Insert or replace an entry."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO file_hashes
                    (url_hash, file_path, file_hash, url, file_size)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (url_hash, file_path, file_hash, url, file_size),
                )
                conn.commit()
            finally:
                conn.close()

    def count(self) -> int:
        """Return total number of stored hashes."""
        return self._count_rows("file_hashes")

    def clear(self) -> None:
        """Remove **all** entries."""
        self._delete_all("file_hashes")
