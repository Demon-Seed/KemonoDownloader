"""Saved Creator-tab config profiles.

Two independent profiles can be stored: one default used for every creator and
one per creator. A profile holds the Creator tab's options and post filters —
never its post ticks, which are a momentary choice rather than a setting. A
creator profile *replaces* the default while that creator is loaded; the two
are never blended, so switching creators is a profile switch.

The database lives next to ``file_hashes.db`` and ``download_history.db`` in
the user's "Other Files" directory and follows the same threading model as
:class:`kemonodownloader.download_history.DownloadHistoryDB`: one connection
per call, guarded by a lock, in WAL mode.
"""

import json
import os
import sqlite3
import threading
from typing import Optional

from .download_history import utc_now_iso

# Bumped when a stored payload's shape changes. A row written by a different
# version is ignored (and replaced by the next save) instead of being applied
# to widgets it may no longer describe.
SCHEMA_VERSION = 1


class CreatorConfigStore:
    """Thread-safe SQLite store of Creator-tab config profiles."""

    DB_FILENAME = "creator_configs.db"

    def __init__(self, directory: str):
        """Create the database file and its tables if they do not exist.

        Parameters
        ----------
        directory:
            Directory where the database file will be stored.
        """
        os.makedirs(directory, exist_ok=True)
        self.db_path = os.path.join(directory, self.DB_FILENAME)
        self._lock = threading.Lock()
        self._init_db()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_connection(self) -> sqlite3.Connection:
        """Create a new connection (one per call – safe for threads)."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create the tables if they are not present yet."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS page_default (
                        scope    TEXT PRIMARY KEY,
                        payload  TEXT NOT NULL,
                        saved_at TEXT NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS creator_config (
                        service    TEXT NOT NULL,
                        creator_id TEXT NOT NULL,
                        payload    TEXT NOT NULL,
                        saved_at   TEXT NOT NULL,
                        PRIMARY KEY (service, creator_id)
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _encode(payload: dict) -> str:
        """Serialise a profile, stamping the schema version on the way in."""
        data = dict(payload or {})
        data["version"] = SCHEMA_VERSION
        # The row keeps its own timestamp; a copy inside the payload would be
        # one more thing that can disagree.
        data.pop("saved_at", None)
        return json.dumps(data, sort_keys=True)

    @staticmethod
    def _decode(row) -> Optional[dict]:
        """Return a stored profile, or None when it cannot be trusted."""
        if row is None or not row["payload"]:
            return None
        try:
            data = json.loads(row["payload"])
        except (TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        if data.get("version") != SCHEMA_VERSION:
            return None
        return data

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def set_page_default(self, payload: dict) -> None:
        """Store *payload* as the default profile for every creator."""
        encoded = self._encode(payload)
        timestamp = utc_now_iso()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO page_default (scope, payload, saved_at)"
                    " VALUES ('default', ?, ?)",
                    (encoded, timestamp),
                )
                conn.commit()
            finally:
                conn.close()

    def set_creator_config(self, service: str, creator_id: str, payload: dict) -> None:
        """Store *payload* as the profile of one creator."""
        if not service or not creator_id:
            return
        encoded = self._encode(payload)
        timestamp = utc_now_iso()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO creator_config
                    (service, creator_id, payload, saved_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(service), str(creator_id), encoded, timestamp),
                )
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_page_default(self) -> Optional[dict]:
        """Return the default profile, or None when nothing is stored."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT payload, saved_at FROM page_default WHERE scope = 'default'"
                ).fetchone()
            finally:
                conn.close()
        return self._decode(row)

    def get_creator_config(self, service: str, creator_id: str) -> Optional[dict]:
        """Return one creator's profile, or None when it has none."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT payload, saved_at FROM creator_config"
                    " WHERE service = ? AND creator_id = ?",
                    (str(service), str(creator_id)),
                ).fetchone()
            finally:
                conn.close()
        return self._decode(row)

    def count_creator_configs(self) -> int:
        """Return how many creator profiles are stored."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM creator_config"
                ).fetchone()
                return row["cnt"] if row else 0
            finally:
                conn.close()
