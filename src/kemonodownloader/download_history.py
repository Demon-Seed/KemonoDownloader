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

from datetime import datetime, timezone
from typing import Optional

from kemonodownloader.sqlite_store import SQLiteStore


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


class DownloadHistoryDB(SQLiteStore):
    """Thread-safe SQLite store of per-post download timestamps."""

    DB_FILENAME = "download_history.db"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
        """Remove one post's download record."""
        if not service or not creator_id or not post_id:
            return
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
        self._delete_all("post_downloads")

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
        return self._count_rows("post_downloads")
