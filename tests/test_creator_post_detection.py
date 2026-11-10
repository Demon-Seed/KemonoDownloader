import gzip
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import kemonodownloader.creator_downloader as cd


def make_gzipped_response(obj):
    j = json.dumps(obj).encode("utf-8")
    return gzip.compress(j)


def run_detection(monkeypatch, posts, **kwargs):
    """Run one detection pass over *posts* and return (thread, kept titles)."""
    settings = SimpleNamespace(
        creator_posts_max_attempts=1, settings_tab=SimpleNamespace()
    )

    class Resp:
        status_code = 200
        content = make_gzipped_response(posts)

    class S:
        def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    # Facts have to exist for the live filter pass to work on them.
    kwargs.setdefault("post_search_index", {})
    thread = cd.PostDetectionThread(
        "https://kemono.cr/artist/user/12", {}, settings, **kwargs
    )
    thread.posts_batch = SimpleNamespace(emit=MagicMock())
    thread.finished = SimpleNamespace(emit=MagicMock())
    thread.log = SimpleNamespace(emit=MagicMock())
    thread.error = SimpleNamespace(emit=MagicMock())

    thread.run()

    kept = [
        title
        for call in thread.posts_batch.emit.call_args_list
        for title, _ in call.args[0]
    ]
    return thread, kept


def visible_posts(thread):
    """Run the live filter pass over what the fetch kept."""
    filter_thread = cd.FilterThread(
        thread.finished.emit.call_args[0][0],
        {},
        "",
        post_search_index=thread.post_search_index or {},
        post_filters=thread.post_filters,
    )
    filter_thread.finished = SimpleNamespace(emit=MagicMock())
    filter_thread.run()
    return [
        title for title, _, _, _ in filter_thread.finished.emit.call_args[0][0]
    ]


def test_post_detection_with_list(monkeypatch):
    settings = SimpleNamespace(
        creator_posts_max_attempts=1, settings_tab=SimpleNamespace()
    )

    post = {
        "id": "p1",
        "title": "T1",
        "file": {"path": "/media/1.png", "name": "img1.png"},
    }

    class Resp:
        status_code = 200
        content = make_gzipped_response([post])

    class S:
        def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    post_titles = {}
    t = cd.PostDetectionThread(
        "https://kemono.cr/artist/user/10", post_titles, settings
    )
    t.posts_batch = SimpleNamespace(emit=MagicMock())
    t.finished = SimpleNamespace(emit=MagicMock())
    t.log = SimpleNamespace(emit=MagicMock())
    t.error = SimpleNamespace(emit=MagicMock())

    t.run()

    assert t.posts_batch.emit.called
    assert t.finished.emit.called


def test_post_detection_with_dict_posts(monkeypatch):
    settings = SimpleNamespace(
        creator_posts_max_attempts=1, settings_tab=SimpleNamespace()
    )

    post = {
        "id": "p2",
        "title": "T2",
        "attachments": [{"path": "/att/2.jpg", "name": "a2.jpg"}],
    }

    class Resp:
        status_code = 200
        content = make_gzipped_response({"posts": [post]})

    class S:
        def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    post_titles = {}
    t = cd.PostDetectionThread(
        "https://kemono.cr/artist/user/11", post_titles, settings
    )
    t.posts_batch = SimpleNamespace(emit=MagicMock())
    t.finished = SimpleNamespace(emit=MagicMock())
    t.log = SimpleNamespace(emit=MagicMock())
    t.error = SimpleNamespace(emit=MagicMock())

    t.run()

    assert t.posts_batch.emit.called
    assert t.finished.emit.called


def test_post_detection_invalid_url_emits_error():
    settings = SimpleNamespace(
        creator_posts_max_attempts=1, settings_tab=SimpleNamespace()
    )
    post_titles = {}
    t = cd.PostDetectionThread("https://kemono.cr/invalid/path", post_titles, settings)
    t.error = SimpleNamespace(emit=MagicMock())
    t.log = SimpleNamespace(emit=MagicMock())

    t.run()

    assert t.error.emit.called


def test_filetype_filter_drops_posts_without_a_selected_type(monkeypatch):
    posts = [
        {
            "id": "p1",
            "title": "PSD work",
            "file": {"path": "/m/1.psd", "name": "art.psd"},
        },
        {
            "id": "p2",
            "title": "Text only",
            "attachments": [{"path": "/a/n.txt", "name": "n.txt"}],
        },
    ]

    thread, kept = run_detection(monkeypatch, posts, required_filetypes={".psd"})

    # The fetch records the skip and still hands both posts over, so
    # unticking the filter can bring the text post back without a fetch.
    assert thread.filetype_skipped_count == 1
    assert thread.filtered_count == 1
    assert sorted(kept) == ["PSD work", "Text only"]
    assert visible_posts(thread) == ["PSD work"]


def test_filetype_filter_treats_jpeg_as_jpg(monkeypatch):
    posts = [
        {
            "id": "p3",
            "title": "JPEG work",
            "attachments": [{"path": "/a/p.jpeg", "name": "p.jpeg"}],
        },
    ]

    thread, kept = run_detection(monkeypatch, posts, required_filetypes={".jpg"})

    assert kept == ["JPEG work"]
    assert thread.filetype_skipped_count == 0


def test_filetype_filter_folds_jpeg_requirements_into_jpg(monkeypatch):
    posts = [
        {
            "id": "p5",
            "title": "JPEG work",
            "attachments": [{"path": "/a/p.jpeg", "name": "p.jpeg"}],
        },
    ]

    thread, kept = run_detection(monkeypatch, posts, required_filetypes={".jpeg"})

    assert kept == ["JPEG work"]
    assert thread.filetype_skipped_count == 0


def test_a_dropped_post_is_booked_under_one_filter_only(monkeypatch):
    posts = [
        {
            "id": "p6",
            "title": "art bundle",
            "published": "2020-01-01T00:00:00",
            "file": {"path": "/m/1.png", "name": "img.png"},
        },
    ]

    thread, kept = run_detection(
        monkeypatch,
        posts,
        skip_keywords=["art"],
        date_after=date(2024, 1, 1),
    )

    # Two filters match, but the post is only one skipped post: keyword
    # wins because it is checked first, and the buckets add up to 1.
    assert thread.filtered_count == 1
    assert thread.keyword_skipped_count == 1
    assert thread.date_skipped_count == 0
    assert kept == ["art bundle"]
    assert visible_posts(thread) == []


def test_filetype_filter_is_inert_without_selected_types(monkeypatch):
    posts = [
        {
            "id": "p2",
            "title": "Text only",
            "attachments": [{"path": "/a/n.txt", "name": "n.txt"}],
        },
    ]

    thread, kept = run_detection(monkeypatch, posts, required_filetypes=set())

    assert kept == ["Text only"]
    assert thread.filetype_skipped_count == 0


def test_filetype_filter_keeps_posts_with_nothing_to_compare(monkeypatch):
    posts = [{"id": "p4", "title": "Words only", "content": "just text"}]

    thread, kept = run_detection(monkeypatch, posts, required_filetypes={".png"})

    assert kept == ["Words only"]
    assert thread.filetype_skipped_count == 0


def test_relaxing_a_filter_brings_posts_back_without_another_fetch(monkeypatch):
    posts = [
        {
            "id": "p7",
            "title": "art bundle",
            "file": {"path": "/m/1.png", "name": "a.png"},
        },
        {
            "id": "p8",
            "title": "plain post",
            "file": {"path": "/m/2.png", "name": "b.png"},
        },
    ]

    thread, kept = run_detection(monkeypatch, posts, skip_keywords=["art"])

    assert sorted(kept) == ["art bundle", "plain post"]
    assert visible_posts(thread) == ["plain post"]

    # Same facts, relaxed filters. No second detection run: this is what makes
    # clearing a filter instant instead of a refetch.
    relaxed = cd.FilterThread(
        thread.finished.emit.call_args[0][0],
        {},
        "",
        post_search_index=thread.post_search_index,
        post_filters=cd.PostFilters(),
    )
    relaxed.finished = SimpleNamespace(emit=MagicMock())
    relaxed.run()

    shown = [title for title, _, _, _ in relaxed.finished.emit.call_args[0][0]]

    assert sorted(shown) == ["art bundle", "plain post"]
