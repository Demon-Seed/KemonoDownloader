"""In-memory preview image cache: LRU order and explicit clearing."""

from kemonodownloader.preview_cache import PreviewImageCache


def test_store_get_and_clear():
    cache = PreviewImageCache(max_bytes=32)
    cache.store("a", b"1234")
    assert cache.get("a") == b"1234"
    assert cache.cached_bytes == 4

    cache.clear()

    assert cache.get("a") is None
    assert cache.cached_bytes == 0
    assert cache.cached_urls == ()


def test_hits_move_to_the_end_and_least_recent_is_evicted():
    cache = PreviewImageCache(max_bytes=12)
    cache.store("a", b"aaaa")
    cache.store("b", b"bbbb")
    assert cache.get("a") == b"aaaa"  # a is now the most recently used.

    cache.store("c", b"cccc")
    cache.store("d", b"dddd")  # 16 bytes -> evict b

    assert cache.cached_urls == ("a", "c", "d")
    assert cache.get("b") is None


def test_an_image_larger_than_the_budget_is_not_kept():
    cache = PreviewImageCache(max_bytes=4)

    cache.store("big", b"12345")

    assert cache.cached_urls == ()
    assert cache.cached_bytes == 0
