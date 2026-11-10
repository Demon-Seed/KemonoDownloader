"""detect_files must survive the post shapes the API actually sends.

``analyze_post`` has always tolerated a null ``attachments`` list and a
non-dict ``file``; the file-detection path used to trust both, so one odd post
raised inside the preparation worker and that post's files vanished.
"""

from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd

DOMAIN = {
    "base_url": "https://kemono.cr",
    "api_base": "https://kemono.cr/api",
    "referer": "https://kemono.cr/",
    "file_base_url": "https://n1.kemono.cr",
}


def make_thread(**kwargs):
    """A preparation thread with all three categories enabled."""
    return cd.FilePreparationThread(
        [],
        {},
        {},
        True,
        True,
        True,
        SimpleNamespace(),
        **kwargs,
    )


def names(files):
    return [name for name, _url in files]


def test_null_attachments_are_ignored():
    thread = make_thread()
    post = {
        "id": "1",
        "title": "T",
        "attachments": None,
        "file": {"path": "/data/ab/cd/f.jpg", "name": "f.jpg"},
    }

    files = thread.detect_files(post, [".jpg"], DOMAIN)

    # The main file is still found; the null list simply contributes nothing.
    assert names(files) == ["f.jpg"]


def test_null_attachment_entries_are_skipped():
    thread = make_thread()
    post = {
        "id": "1",
        "attachments": [None, {"path": "/data/ab/cd/a.png", "name": "a.png"}],
    }

    files = thread.detect_files(post, [".png"], DOMAIN)

    assert names(files) == ["a.png"]


def test_string_file_field_is_not_read_as_a_path():
    """``"path" in "/data/f.jpg"`` is True, which used to index into a string."""
    thread = make_thread()
    post = {"id": "1", "file": "/data/ab/cd/f.jpg"}

    files = thread.detect_files(post, [".jpg"], DOMAIN)

    assert files == []


def test_a_normal_post_still_yields_every_file():
    thread = make_thread()
    post = {
        "id": "1",
        "file": {"path": "/data/ab/cd/f.jpg", "name": "f.jpg"},
        "attachments": [{"path": "/data/ab/cd/a.png", "name": "a.png"}],
        "content": '<p><img src="https://n1.kemono.cr/data/ab/cd/c.webp"/></p>',
    }

    files = thread.detect_files(post, [".jpg", ".png", ".webp"], DOMAIN)

    assert names(files) == ["f.jpg", "a.png", "c.webp"]
