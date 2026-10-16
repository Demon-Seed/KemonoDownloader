"""SQLite-based download history for creator posts.

Keeps track of *when* a post's files were last actually pulled from the
server, so the Creator Downloader tab can show a per-post date (next to the
post's publish date) and a per-creator date.

Only genuine downloads are recorded: a file that is skipped because it is
already on disk (hash database dedup) does not count as a download, so
re-checking a post you already have leaves its date alone.  No file paths are
stored, so the history survives files being moved or renamed.

The database lives next to ``file_hashes.db`` in the user's "Other Files"
directory and follows the same threading model as
:class:`kemonodownloader.hash_db.HashDB`: one connection per call, guarded by
a lock, in WAL mode.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional


def utc_now_iso() -> str:
    """Return the current UTC time as a stored-format timestamp."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def iso_to_local_date(timestamp: Optional[str]) -> str:
    """Render a stored timestamp as ``YYYY-MM-DD`` in the user's local time.

    Returns an empty string for missing or unparsable values so callers can
    treat "no date" and "bad date" the same way.
    """
    if not timestamp:
        return ""
    try:
        parsed = datetime.fromisoformat(timestamp)
    except (TypeError, ValueError):
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%Y-%m-%d")


class DownloadHistoryDB:
    """Thread-safe SQLite store of per-post download timestamps."""

    DB_FILENAME = "download_history.db"

    def __init__(self, directory: str):
        """Initialise the download history database.

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
        """Create the table if it is not present yet."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS post_downloads (
                        service         TEXT NOT NULL,
                        creator_id      TEXT NOT NULL,
                        post_id         TEXT NOT NULL,
                        last_downloaded TEXT NOT NULL,
                        PRIMARY KEY (service, creator_id, post_id)
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def record_post(
        self,
        service: str,
        creator_id: str,
        post_id: str,
        timestamp: Optional[str] = None,
    ) -> None:
        """Record when *post_id* was last downloaded.

        Parameters
        ----------
        service, creator_id, post_id:
            Identity of the post.  Post ids are only unique per creator, so
            all three parts are needed.
        timestamp:
            Stored-format timestamp; defaults to now (UTC).
        """
        if not service or not creator_id or not post_id:
            return
        timestamp = timestamp or utc_now_iso()
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO post_downloads
                    (service, creator_id, post_id, last_downloaded)
                    VALUES (?, ?, ?, ?)
                    """,
                    (str(service), str(creator_id), str(post_id), timestamp),
                )
                conn.commit()
            finally:
                conn.close()

    def forget_post(self, service: str, creator_id: str, post_id: str) -> None:
        """Remove a single post's record."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute(
                    "DELETE FROM post_downloads "
                    "WHERE service = ? AND creator_id = ? AND post_id = ?",
                    (str(service), str(creator_id), str(post_id)),
                )
                conn.commit()
            finally:
                conn.close()

    def clear(self) -> None:
        """Remove **all** records."""
        with self._lock:
            conn = self._get_connection()
            try:
                conn.execute("DELETE FROM post_downloads")
                conn.commit()
            finally:
                conn.close()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_post_times(self, service: str, creator_id: str) -> dict:
        """Return ``{post_id: timestamp}`` for one creator."""
        with self._lock:
            conn = self._get_connection()
            try:
                rows = conn.execute(
                    "SELECT post_id, last_downloaded FROM post_downloads "
                    "WHERE service = ? AND creator_id = ?",
                    (str(service), str(creator_id)),
                ).fetchall()
                return {
                    row["post_id"]: row["last_downloaded"]
                    for row in rows
                    if row["last_downloaded"]
                }
            finally:
                conn.close()

    def get_creator_time(self, service: str, creator_id: str) -> Optional[str]:
        """Return the newest timestamp recorded for a creator, or None."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT MAX(last_downloaded) AS latest FROM post_downloads "
                    "WHERE service = ? AND creator_id = ?",
                    (str(service), str(creator_id)),
                ).fetchone()
                if row and row["latest"]:
                    return row["latest"]
                return None
            finally:
                conn.close()

    def count(self) -> int:
        """Return the total number of recorded posts."""
        with self._lock:
            conn = self._get_connection()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) AS cnt FROM post_downloads"
                ).fetchone()
                return row["cnt"] if row else 0
            finally:
                conn.close()
