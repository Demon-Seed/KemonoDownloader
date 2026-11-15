"""The preview cache is disposable, bounded by size, and never touches strays."""

import hashlib
import os

from kemonodownloader import preview_cache as pc


def _entry(cache_dir, name, size, mtime):
    path = os.path.join(str(cache_dir), name)
    with open(path, "wb") as handle:
        handle.write(b"x" * size)
    os.utime(path, (mtime, mtime))
    return path


def _cache_name(seed):
    """A filename shaped like the ones PreviewThread writes."""
    return hashlib.md5(seed.encode()).hexdigest() + ".png"


def test_cache_path_matches_the_preview_thread_key(tmp_path):
    url = "https://file.pawchive.pw/data/59/97/photo.png"

    path = pc.preview_cache_path(url, str(tmp_path))

    expected = hashlib.md5(url.encode()).hexdigest() + ".png"
    assert os.path.basename(path) == expected
    assert os.path.dirname(path) == str(tmp_path)


def test_has_cached_preview_checks_only_the_expected_file(tmp_path):
    url = "https://file.pawchive.pw/data/59/97/photo.png"

    assert pc.has_cached_preview(url, str(tmp_path)) is False

    with open(pc.preview_cache_path(url, str(tmp_path)), "wb") as handle:
        handle.write(b"x")

    assert pc.has_cached_preview(url, str(tmp_path)) is True
    assert pc.has_cached_preview(url + "?other", str(tmp_path)) is False


def test_preview_cache_has_a_100_mb_cap():
    assert pc.PREVIEW_CACHE_MAX_BYTES == 100 * 1024 * 1024


def test_prune_keeps_the_newest_entries_under_the_size_cap(tmp_path):
    old = _entry(tmp_path, _cache_name("old"), 60, 1000)
    middle = _entry(tmp_path, _cache_name("middle"), 60, 2000)
    newest = _entry(tmp_path, _cache_name("newest"), 60, 3000)

    # Room for two entries only: the oldest goes first.
    removed, freed = pc.prune_preview_cache(str(tmp_path), max_bytes=130)

    assert (removed, freed) == (1, 60)
    assert not os.path.exists(old)
    assert os.path.exists(middle)
    assert os.path.exists(newest)


def test_prune_does_nothing_when_the_cache_is_under_the_cap(tmp_path):
    first = _entry(tmp_path, _cache_name("a"), 40, 1000)
    second = _entry(tmp_path, _cache_name("b"), 40, 2000)

    removed, freed = pc.prune_preview_cache(str(tmp_path), max_bytes=100)

    assert (removed, freed) == (0, 0)
    assert os.path.exists(first)
    assert os.path.exists(second)


def test_prune_ignores_files_that_are_not_cache_entries(tmp_path):
    entry = _entry(tmp_path, _cache_name("kept"), 40, 1000)
    stray = _entry(tmp_path, "notes.txt", 500, 2000)

    removed, freed = pc.prune_preview_cache(str(tmp_path), max_bytes=0)

    assert (removed, freed) == (1, 40)
    assert not os.path.exists(entry)
    assert os.path.exists(stray)


def test_prune_tolerates_a_missing_folder(tmp_path):
    missing = tmp_path / "does-not-exist"

    assert pc.prune_preview_cache(str(missing), max_bytes=0) == (0, 0)


def test_clear_removes_every_entry_but_not_strays(tmp_path):
    first = _entry(tmp_path, _cache_name("one"), 10, 1000)
    second = _entry(tmp_path, _cache_name("two"), 20, 2000)
    stray = _entry(tmp_path, "keep.me", 5, 3000)

    removed, freed = pc.clear_preview_cache(str(tmp_path))

    assert (removed, freed) == (2, 30)
    assert not os.path.exists(first)
    assert not os.path.exists(second)
    assert os.path.exists(stray)
    assert os.path.isdir(str(tmp_path))


def test_clear_tolerates_a_missing_folder(tmp_path):
    assert pc.clear_preview_cache(str(tmp_path / "missing")) == (0, 0)


def test_format_size_is_readable():
    assert pc.format_size(0) == "0 B"
    assert pc.format_size(1023) == "1023 B"
    assert pc.format_size(1024) == "1.0 KB"
    assert pc.format_size(1024 * 1024) == "1.0 MB"


def test_async_prune_trims_in_the_background(tmp_path):
    old = _entry(tmp_path, _cache_name("old"), 60, 1000)
    new = _entry(tmp_path, _cache_name("new"), 60, 2000)

    thread = pc.prune_preview_cache_async(str(tmp_path), max_bytes=60)
    thread.join(2)

    assert not thread.is_alive()
    assert not os.path.exists(old)
    assert os.path.exists(new)
