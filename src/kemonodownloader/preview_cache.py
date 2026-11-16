"""In-memory cache for preview images.

Previews used to be written to a disk cache.  They are now kept only in
memory: the Creator tab owns one :class:`PreviewImageCache` for the whole
session, so opening a post a second time reuses the thumbnail bytes without
another request.  The cache is a bounded LRU keyed by image URL; the oldest
entry is dropped once the byte budget is exceeded, and the tab clears the
whole cache when it switches to another creator.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional, Tuple

# 64 MiB is enough for hundreds of Pawchive thumbnails while keeping the
# app's memory use predictable.  It is a cap on the compressed response
# bytes, not on decoded QImages (those are released separately as rows
# scroll out of view).
DEFAULT_PREVIEW_CACHE_BYTES = 64 * 1024 * 1024


class PreviewImageCache:
    """Thread-safe, size-bounded LRU of raw preview image bytes."""

    def __init__(self, max_bytes: int = DEFAULT_PREVIEW_CACHE_BYTES):
        self._max_bytes = max(1, int(max_bytes))
        self._lock = threading.Lock()
        self._entries: "OrderedDict[str, bytes]" = OrderedDict()
        self._total_bytes = 0

    def get(self, url: str) -> Optional[bytes]:
        """Return the bytes cached for *url*, marking it most recently used."""
        if not url:
            return None
        with self._lock:
            data = self._entries.get(url)
            if data is not None:
                self._entries.move_to_end(url)
            return data

    def store(self, url: str, data: bytes) -> None:
        """Cache *data* for *url*, evicting the oldest entries if needed."""
        if not url or not data:
            return
        with self._lock:
            previous = self._entries.pop(url, None)
            if previous is not None:
                self._total_bytes -= len(previous)
            self._entries[url] = data
            self._total_bytes += len(data)
            while self._total_bytes > self._max_bytes and self._entries:
                _old_url, old_data = self._entries.popitem(last=False)
                self._total_bytes -= len(old_data)

    def clear(self) -> None:
        """Drop every cached image, freeing its memory."""
        with self._lock:
            self._entries.clear()
            self._total_bytes = 0

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @property
    def cached_bytes(self) -> int:
        with self._lock:
            return self._total_bytes

    @property
    def cached_urls(self) -> Tuple[str, ...]:
        with self._lock:
            return tuple(self._entries)

    def __len__(self) -> int:
        return len(self.cached_urls)
