"""Tests for the "File Count From" post filter.

The filter counts a post's main file, attachments and content images, honours
both inclusive bounds, and never drops posts holding a ZIP/7Z/RAR when "Keep
Archives" is enabled.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import kemonodownloader.creator_downloader as cd


class Resp:
    def __init__(self, content_bytes, text=""):
        self.content = content_bytes
        self._text = text
        self.status_code = 200

    @property
    def text(self):
        return self._text

    def close(self):
        return None


def _signal():
    return SimpleNamespace(emit=MagicMock())


def _thread(**kwargs):
    settings = SimpleNamespace(creator_posts_max_attempts=1, settings_tab=None)
    return cd.PostDetectionThread(
        "https://kemono.cr/patreon/user/1", {}, settings, **kwargs
    )


def _post(**overrides):
    post = {
        "id": "1",
        "title": "A post",
        "file": {"name": "main.png", "path": "/m/main.png"},
        "attachments": [
            {"name": "a1.jpg", "path": "/a/1.jpg"},
            {"name": "a2.png", "path": "/a/2.png"},
        ],
        "content": "<p><img src='/c/1.jpg'/><img src='/c/2.jpg'/></p>",
    }
    post.update(overrides)
    return post


# ---------------------------------------------------------------------------
# parse_filter_count
# ---------------------------------------------------------------------------


def test_parse_filter_count_accepts_whole_numbers():
    assert cd.parse_filter_count("0") == 0
    assert cd.parse_filter_count(" 12 ") == 12


def test_parse_filter_count_rejects_junk_and_negatives():
    for value in ("", "   ", None, "abc", "1.5", "-2"):
        assert cd.parse_filter_count(value) is None


# ---------------------------------------------------------------------------
# analyze_post
# ---------------------------------------------------------------------------


def test_analyze_post_counts_every_file():
    analysis = cd.analyze_post(_post())

    assert analysis["file_count"] == 5  # main + 2 attachments + 2 content images
    assert analysis["has_compressed"] is False


def test_analyze_post_counts_unique_content_images_only():
    analysis = cd.analyze_post(_post(content="<img src='/c/1.jpg'/><img src='/c/1.jpg'/>"))

    assert analysis["file_count"] == 4  # main + 2 attachments + 1 unique image


def test_analyze_post_detects_compressed_files():
    for name in ("pack.zip", "pack.7Z", "pack.rar"):
        analysis = cd.analyze_post({"id": "1", "file": {"name": name}})
        assert analysis["has_compressed"] is True


# ---------------------------------------------------------------------------
# End-to-end detection run
# ---------------------------------------------------------------------------


POSTS = [
    {
        "id": "small",
        "title": "Small post",
        "file": {"name": "one.png", "path": "/m/1.png"},
    },
    {
        "id": "big",
        "title": "Big post",
        "file": {"name": "main.png", "path": "/m/main.png"},
        "attachments": [
            {"name": f"a{i}.png", "path": f"/a/{i}.png"} for i in range(4)
        ],
    },
    {
        "id": "archive",
        "title": "Archive post",
        "file": {"name": "pack.zip", "path": "/m/pack.zip"},
    },
]


def _run_detection(monkeypatch, posts, **kwargs):
    text = json.dumps(posts)
    resp = Resp(text.encode("utf-8"), text=text)

    class Session:
        def get(self, *args, **kwargs):
            return resp

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: Session())

    thread = _thread(**kwargs)
    thread.posts_batch = _signal()
    thread.finished = _signal()
    thread.log = _signal()
    thread.error = _signal()
    thread.run()
    return thread


def _detected_ids(thread):
    return [post_id for _, (post_id, _) in thread.finished.emit.call_args[0][0]]


def test_detection_applies_the_minimum_count(monkeypatch):
    thread = _run_detection(monkeypatch, POSTS, file_count_min=3)

    assert _detected_ids(thread) == ["big"]
    assert thread.file_count_skipped_count == 2


def test_detection_applies_the_maximum_count(monkeypatch):
    thread = _run_detection(monkeypatch, POSTS, file_count_max=1)

    assert sorted(_detected_ids(thread)) == ["archive", "small"]


def test_detection_keeps_archives_when_asked(monkeypatch):
    thread = _run_detection(
        monkeypatch, POSTS, file_count_min=3, file_count_keep_compressed=True
    )

    assert sorted(_detected_ids(thread)) == ["archive", "big"]


def test_detection_without_bounds_keeps_everything(monkeypatch):
    thread = _run_detection(monkeypatch, POSTS)

    assert len(_detected_ids(thread)) == 3
    assert thread.file_count_skipped_count == 0


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------


def test_file_count_keys_translated_in_all_languages():
    from kemonodownloader.kd_language import language_manager, translate

    keys = [
        "file_count_filter",
        "file_count_from_placeholder",
        "file_count_to",
        "file_count_to_placeholder",
        "file_count_keep_compressed",
        "file_count_help_title",
        "file_count_help_text",
        "invalid_file_count_ignored",
        "posts_skipped_by_file_count_filter",
    ]
    original = language_manager.current_language
    try:
        for language in language_manager.get_available_languages():
            language_manager.set_language(language)
            for key in keys:
                assert translate(key, 1) not in ("", key)
    finally:
        language_manager.set_language(original)



def test_analyze_post_tolerates_odd_posts():
    for post in (None, {}, [], {"id": "1", "file": None, "attachments": None}):
        analysis = cd.analyze_post(post)
        assert analysis["file_count"] == 0
        assert analysis["has_compressed"] is False


# ---------------------------------------------------------------------------
# _post_file_count_out_of_range
# ---------------------------------------------------------------------------


def test_no_bounds_never_filters():
    assert not _thread()._post_file_count_out_of_range(_post())


def test_minimum_bound_is_inclusive():
    assert not _thread(file_count_min=5)._post_file_count_out_of_range(_post())
    assert _thread(file_count_min=6)._post_file_count_out_of_range(_post())


def test_maximum_bound_is_inclusive():
    assert not _thread(file_count_max=5)._post_file_count_out_of_range(_post())
    assert _thread(file_count_max=4)._post_file_count_out_of_range(_post())


def test_both_bounds_form_a_range():
    assert _thread(file_count_min=6, file_count_max=9)._post_file_count_out_of_range(
        _post()
    )


def test_keep_archives_bypasses_the_filter():
    archive_post = _post(file={"name": "pack.zip", "path": "/m/pack.zip"})

    assert _thread(file_count_min=9)._post_file_count_out_of_range(archive_post)
    assert not _thread(
        file_count_min=9, file_count_keep_compressed=True
    )._post_file_count_out_of_range(archive_post)


def test_keep_archives_still_filters_posts_without_archives():
    assert _thread(
        file_count_min=9, file_count_keep_compressed=True
    )._post_file_count_out_of_range(_post())
