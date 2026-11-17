"""Shared, Qt-free plumbing for the file and preview downloads.

Three things live here, all of them ported from upstream 5.14/5.15:

* :data:`DOWNLOAD_CHUNK_SIZE` and :class:`ProgressTracker`.  The download
  loops reported progress for every 8 KiB chunk, which queued tens of
  thousands of cross-thread signals for a large file - the window then spent
  its time formatting percentages instead of painting.  Chunks are 64 KiB now
  and a percentage is only reported when it changes (at most 101 per file).
* :func:`response_content_length`.  ``Content-Length`` describes the bytes on
  the wire, not the size ``iter_content`` produces after decompression, so a
  compressed response looked like a truncated transfer and was retried until
  the retry budget was gone.
* :func:`create_connection_guard` and :class:`RequestGate`.  Serialising
  connection opens is only needed on Windows + Python 3.14, where concurrent
  OpenSSL handshakes abort the process natively; everywhere else the guard is
  a no-op.  The gate keeps new Pawchive requests spaced, so dropping that lock
  does not turn a run into an unpaced burst.
"""

from __future__ import annotations

import contextlib
import sys
import threading
import time
from contextlib import AbstractContextManager
from typing import Callable, Optional
from urllib.parse import urlparse

# Large enough that Python's per-chunk overhead is negligible on a fast link,
# small enough that cancellation is still noticed promptly on a slow one.
DOWNLOAD_CHUNK_SIZE = 64 * 1024

# Spacing between new Pawchive file requests (~4 req/s).  Roughly the rate the
# old unconditional connection lock produced by accident: it is not a
# throughput cap for normal-sized files, but it stops a batch of workers from
# opening everything at the same instant.
PAWCHIVE_REQUEST_INTERVAL = 0.25


class ProgressTracker:
    """Turns a stream of byte counts into at most one report per percentage."""

    def __init__(self, total_size: int) -> None:
        self.total_size = max(int(total_size or 0), 0)
        self.downloaded = 0
        self._last_percent: Optional[int] = None

    def advance(self, chunk_size: int) -> Optional[int]:
        """Record *chunk_size* more bytes; return the percentage if it moved."""
        self.downloaded += max(int(chunk_size or 0), 0)
        percent = 0
        if self.total_size > 0:
            percent = min(int(self.downloaded * 100 / self.total_size), 100)
        if percent == self._last_percent:
            return None
        self._last_percent = percent
        return percent


def response_content_length(response) -> int:
    """Return the size the body will have once decoded, or 0 when unknown.

    A body that arrives compressed has a ``Content-Length`` that says nothing
    about the size ``iter_content`` decompresses, so the caller must not treat
    it as the expected size.
    """
    headers = getattr(response, "headers", None) or {}
    try:
        encoding = headers.get("content-encoding")
    except Exception:
        return 0
    if encoding not in (None, "", "identity"):
        return 0
    try:
        value = int(headers.get("content-length"))
    except (TypeError, ValueError):
        return 0
    return value if value > 0 else 0


def create_connection_guard() -> AbstractContextManager:
    """Return the guard used around opening a connection.

    On Windows + Python 3.14, concurrent SSL handshakes / reads in OpenSSL
    trigger native access-violation crashes, so opens are serialised there.
    Everywhere else connections can be opened in parallel, and returning a
    no-op keeps that path free of the old one-at-a-time bottleneck.
    """
    if sys.platform == "win32" and sys.version_info >= (3, 14):
        return threading.Lock()
    return contextlib.nullcontext()


def is_pawchive_host(url: str) -> bool:
    """True for ``pawchive.<suffix>`` and its subdomains, for any suffix.

    The site has moved between domains, so the suffix is not pinned.
    """
    hostname = (urlparse(str(url or "")).hostname or "").lower().rstrip(".")
    labels = hostname.split(".")
    return len(labels) >= 2 and labels[-2] == "pawchive" and bool(labels[-1])


class RequestGate:
    """Admits at most one request per *min_interval* seconds, process-wide."""

    def __init__(self, min_interval: float = PAWCHIVE_REQUEST_INTERVAL) -> None:
        self._min_interval = max(float(min_interval), 0.0)
        self._lock = threading.Lock()
        self._next_at = 0.0

    @property
    def min_interval(self) -> float:
        return self._min_interval

    def reset(self) -> None:
        """Forget the last grant, so the next call is admitted immediately."""
        with self._lock:
            self._next_at = 0.0

    def acquire(self, is_running: Optional[Callable[[], bool]] = None) -> bool:
        """Wait for a slot; ``False`` only when *is_running* says stop.

        Polls in short slices rather than sleeping the whole interval, so a
        cancelled run is noticed within ~50 ms.
        """
        if self._min_interval <= 0:
            return True
        while True:
            if is_running is not None and not is_running():
                return False
            with self._lock:
                now = time.monotonic()
                if now >= self._next_at:
                    self._next_at = now + self._min_interval
                    return True
                wait_for = self._next_at - now
            time.sleep(min(max(wait_for, 0.01), 0.05))

    def defer(self, seconds: float) -> None:
        """Push every later Pawchive request back by *seconds*.

        Used when the host answers 429: the wait it asked for applies to the
        whole process, not only to the worker that was told.
        """
        with self._lock:
            now = time.monotonic()
            self._next_at = max(self._next_at, now + max(float(seconds), 0.0))

    def wait_out(self, is_running: Optional[Callable[[], bool]] = None) -> bool:
        """Sleep while a deferral is pending; ``False`` only when cancelled.

        Unlike :meth:`acquire` this never reserves a slot, so requests that
        are not paced (preparation) still honour a pause the host asked for.
        """
        while True:
            if is_running is not None and not is_running():
                return False
            with self._lock:
                wait_for = self._next_at - time.monotonic()
            if wait_for <= 0:
                return True
            time.sleep(min(max(wait_for, 0.01), 0.1))


_gate = RequestGate()


def acquire_pawchive_slot(url: str, is_running=None) -> bool:
    """Wait for this process's next Pawchive request slot (no-op elsewhere)."""
    if not is_pawchive_host(url):
        return True
    return _gate.acquire(is_running)


def reset_pawchive_gate() -> None:
    """Clear the gate's next-allowed time (used by the test suite)."""
    _gate.reset()


def defer_pawchive_requests(seconds: float) -> None:
    """Pause every Pawchive request for *seconds* (a 429 asked for it)."""
    _gate.defer(seconds)


def wait_for_pawchive_cooldown(is_running=None) -> bool:
    """Block while a deferral is pending; ``False`` only when cancelled."""
    return _gate.wait_out(is_running)


# Download URL -> the URL on the media server the API named, filled while the
# file list is built.  Files keep their usual URL everywhere else (dedup,
# history, progress, retry); only the request itself goes to the media server,
# which saves the redirect from file.<domain>.
_direct_urls = {}
_direct_urls_lock = threading.Lock()


def remember_direct_url(url: str, direct_url: str) -> None:
    """Record which media server holds the file behind *url*."""
    if not url or not direct_url:
        return
    with _direct_urls_lock:
        _direct_urls[url] = direct_url


def direct_url_for(url: str):
    """Return the media-server URL for *url*, or ``None`` when unknown."""
    with _direct_urls_lock:
        return _direct_urls.get(url)


def forget_direct_url(url: str) -> None:
    """Stop using the media server for *url* (it failed); use the usual URL."""
    with _direct_urls_lock:
        _direct_urls.pop(url, None)


def clear_direct_urls() -> None:
    """Drop every remembered media-server URL (new run, and tests)."""
    with _direct_urls_lock:
        _direct_urls.clear()


# 403/429 answers seen while preparing files.  Preparation runs in its own
# thread, before the download thread that prints the end-of-run summary
# exists, so its counts are kept here and folded into that summary.
_prepare_rate_limit_hits = {}
_prepare_rate_limit_lock = threading.Lock()


def note_rate_limit(status_code) -> None:
    """Count one 403 or 429 answer from the file API."""
    try:
        code = int(status_code)
    except (TypeError, ValueError):
        return
    if code not in (403, 429):
        return
    with _prepare_rate_limit_lock:
        _prepare_rate_limit_hits[code] = _prepare_rate_limit_hits.get(code, 0) + 1


def rate_limit_counts() -> dict:
    """Snapshot of the preparation phase's 403/429 counts."""
    with _prepare_rate_limit_lock:
        return dict(_prepare_rate_limit_hits)


def reset_rate_limit_counts() -> None:
    """Clear the preparation counters (after a summary, and by the tests)."""
    with _prepare_rate_limit_lock:
        _prepare_rate_limit_hits.clear()
