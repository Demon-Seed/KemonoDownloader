"""Disk cache for Creator-tab image previews.

The preview thread writes a re-encoded copy of each image it shows (at most
800x800) here, keyed by the source URL. The cache is disposable: the oldest
entries are dropped once it grows past :data:`PREVIEW_CACHE_MAX_BYTES`, and
the Settings tab can clear it on demand.

Thumbnail-first previews are deliberately *not* cached. A thumbnail is a
small, cheap request, and the full render - which is what repeat previews
use - already short-circuits it once it is cached.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading

# Hard ceiling for the Cache folder. 100 MB holds a few thousand 800 px
# renders, which is far more than the tab can meaningfully reuse.
PREVIEW_CACHE_MAX_BYTES = 100 * 1024 * 1024

# Only files this module wrote are ever pruned: a 32-character md5 followed
# by the source URL's extension. Anything else in Cache/ is left alone.
_CACHE_ENTRY_RE = re.compile(r"^[0-9a-f]{32}\.[A-Za-z0-9]+$")


def preview_cache_path(url, cache_dir):
    """Return the cache file that holds the preview of *url*."""
    extension = os.path.splitext(str(url))[1]
    digest = hashlib.md5(str(url).encode()).hexdigest()
    return os.path.join(cache_dir, digest + extension)


def has_cached_preview(url, cache_dir):
    """True when a preview of *url* is already on disk."""
    try:
        return os.path.isfile(preview_cache_path(url, cache_dir))
    except (TypeError, OSError):
        return False


def _cache_entries(cache_dir):
    """Yield ``(path, size, mtime)`` for every preview cache entry."""
    try:
        with os.scandir(cache_dir) as scan:
            entries = list(scan)
    except OSError:
        return
    for entry in entries:
        if not _CACHE_ENTRY_RE.match(entry.name):
            continue
        try:
            if not entry.is_file(follow_symlinks=False):
                continue
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            continue
        yield entry.path, stat.st_size, stat.st_mtime


def format_size(num_bytes):
    """Return a compact human-readable size for the cache feedback."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def prune_preview_cache(cache_dir, max_bytes=PREVIEW_CACHE_MAX_BYTES):
    """Delete the oldest entries until the cache fits *max_bytes*.

    Returns ``(removed_count, bytes_freed)``. Best effort: an entry that
    cannot be removed (locked, permission) is skipped rather than aborting
    the whole pass. There is no age limit; an unused entry may live forever
    as long as the folder stays under the size ceiling.
    """
    entries = list(_cache_entries(cache_dir))
    total = sum(size for _path, size, _mtime in entries)
    if total <= max_bytes:
        return 0, 0

    removed = 0
    freed = 0
    for path, size, _mtime in sorted(entries, key=lambda item: item[2]):
        if total <= max_bytes:
            break
        try:
            os.remove(path)
        except OSError:
            continue
        total -= size
        removed += 1
        freed += size
    return removed, freed


def clear_preview_cache(cache_dir):
    """Delete every preview cache entry, keeping the folder itself.

    Returns ``(removed_count, bytes_freed)``.
    """
    removed = 0
    freed = 0
    for path, size, _mtime in list(_cache_entries(cache_dir)):
        try:
            os.remove(path)
        except OSError:
            continue
        removed += 1
        freed += size
    return removed, freed


def prune_preview_cache_async(cache_dir, max_bytes=PREVIEW_CACHE_MAX_BYTES):
    """Run :func:`prune_preview_cache` off the UI thread.

    Startup should not wait while a large Cache folder is scanned and trimmed.
    The worker is a daemon so a user closing the window never waits for it.
    """
    thread = threading.Thread(
        target=prune_preview_cache,
        args=(cache_dir, max_bytes),
        name="preview-cache-prune",
        daemon=True,
    )
    thread.start()
    return thread
