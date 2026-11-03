"""Tests for the Creator tab's "Search by" scopes.

The search bar used to match post titles only. These tests pin the new
per-scope matching, the per-post index built while detecting posts (so a
scope toggle re-filters the loaded list instantly), and the translations.
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


INDEX = {
    "1": {
        "filenames": "alien-01.png bonus.zip",
        "description": "a sketch dump of aliens",
        "tags": "aliencomic sci-fi",
    }
}


# ---------------------------------------------------------------------------
# post_matches_search
# ---------------------------------------------------------------------------


def test_empty_search_text_matches_everything():
    assert cd.post_matches_search("Anything", "1", "", {"title"}, INDEX)
    assert cd.post_matches_search("Anything", "1", "", set(), {})


def test_title_scope_matches_title_case_insensitively():
    assert cd.post_matches_search("Alien Comic", "1", "ALIEN", {"title"}, INDEX)
    assert not cd.post_matches_search("Alien Comic", "1", "sketch", {"title"}, INDEX)


def test_filenames_scope_matches_indexed_filenames():
    assert cd.post_matches_search("Post", "1", "bonus", {"filenames"}, INDEX)
    assert not cd.post_matches_search("Post", "1", "bonus", {"title"}, INDEX)


def test_description_scope_matches_indexed_description():
    assert cd.post_matches_search("Post", "1", "dump", {"description"}, INDEX)
    assert not cd.post_matches_search("Post", "1", "dump", {"filenames"}, INDEX)


def test_tags_scope_matches_indexed_tags():
    assert cd.post_matches_search("Post", "1", "sci-fi", {"tags"}, INDEX)
    assert not cd.post_matches_search("Post", "1", "sci-fi", {"title"}, INDEX)


def test_scopes_combine_with_or():
    scopes = {"title", "tags"}
    assert cd.post_matches_search("Post", "1", "sci-fi", scopes, INDEX)
    assert cd.post_matches_search("Post Title", "1", "title", scopes, INDEX)
    assert not cd.post_matches_search("Post", "1", "bonus", scopes, INDEX)


def test_empty_scope_set_falls_back_to_the_title():
    assert cd.post_matches_search("Alien Comic", "1", "alien", set(), INDEX)
    assert not cd.post_matches_search("Alien Comic", "1", "sketch", set(), INDEX)


def test_post_without_index_entry_still_matches_on_title():
    assert cd.post_matches_search("Alien Comic", "404", "alien", {"title"}, INDEX)
    assert not cd.post_matches_search("Alien Comic", "404", "alien", {"tags"}, INDEX)


def test_missing_index_is_tolerated():
    assert cd.post_matches_search("Alien Comic", "1", "alien", {"title"}, None)
    assert not cd.post_matches_search("Alien Comic", "1", "alien", {"tags"}, None)



# ---------------------------------------------------------------------------
# FilterThread
# ---------------------------------------------------------------------------


POSTS = [("Alien Comic", ("1", "thumb1")), ("Other", ("2", "thumb2"))]


def _run_filter_thread(posts, search_text, **kwargs):
    thread = cd.FilterThread(posts, {"1": True, "2": False}, search_text, **kwargs)
    captured = []
    thread.finished = SimpleNamespace(emit=lambda items: captured.append(items))
    thread.run()
    return captured[0]


def test_filter_thread_defaults_to_title_only():
    assert _run_filter_thread(POSTS, "alien") == [("Alien Comic", "1", "thumb1", True)]
    assert _run_filter_thread(POSTS, "sketch", post_search_index=INDEX) == []


def test_filter_thread_honours_the_selected_scopes():
    result = _run_filter_thread(
        POSTS,
        "sketch",
        search_scopes={"description"},
        post_search_index=INDEX,
    )

    assert result == [("Alien Comic", "1", "thumb1", True)]


def test_filter_thread_matches_several_scopes_at_once():
    result = _run_filter_thread(
        POSTS,
        "bonus",
        search_scopes={"title", "filenames"},
        post_search_index=INDEX,
    )

    assert result == [("Alien Comic", "1", "thumb1", True)]


def test_filter_thread_keeps_checked_state():
    result = _run_filter_thread(POSTS, "", post_search_index=INDEX)

    assert [row[3] for row in result] == [True, False]


def test_filter_thread_stop_prevents_emitting():
    thread = cd.FilterThread(POSTS, {}, "alien")
    thread.finished = _signal()
    thread.stop()
    thread.run()

    thread.finished.emit.assert_not_called()


# ---------------------------------------------------------------------------
# Index built while detecting posts
# ---------------------------------------------------------------------------


def _run_detection(monkeypatch, posts, **kwargs):
    text = json.dumps(posts)
    resp = Resp(text.encode("utf-8"), text=text)

    class Session:
        def get(self, *args, **kwargs):
            return resp

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: Session())

    settings = SimpleNamespace(creator_posts_max_attempts=1, settings_tab=None)
    thread = cd.PostDetectionThread(
        "https://kemono.cr/patreon/user/1", {}, settings, **kwargs
    )
    thread.posts_batch = _signal()
    thread.finished = _signal()
    thread.log = _signal()
    thread.error = _signal()
    thread.run()
    return thread


DETECTED_POST = {
    "id": "1",
    "title": "Alien Comic",
    "content": "<p>A Sketch Dump</p>",
    "tags": ["AlienComic", "Sci-Fi"],
    "file": {"name": "Alien-01.PNG", "path": "/ab/1.png"},
    "attachments": [{"name": "Bonus.ZIP", "path": "/cd/2.zip"}],
}


def test_detection_builds_the_search_index(monkeypatch):
    index = {}
    _run_detection(monkeypatch, [DETECTED_POST], post_search_index=index)

    assert index["1"]["filenames"] == "alien-01.png bonus.zip"
    assert index["1"]["description"] == "a sketch dump"
    assert index["1"]["tags"] == "aliencomic sci-fi"


def test_detection_leaves_no_index_when_none_was_passed(monkeypatch):
    thread = _run_detection(monkeypatch, [DETECTED_POST])

    assert thread.post_search_index is None
    assert thread._analysis_cache == {}


def test_indexed_post_is_findable_by_every_new_scope(monkeypatch):
    index = {}
    _run_detection(monkeypatch, [DETECTED_POST], post_search_index=index)

    for needle, scope in (
        ("alien-01", "filenames"),
        ("sketch dump", "description"),
        ("sci-fi", "tags"),
        ("alien comic", "title"),
    ):
        assert cd.post_matches_search("Alien Comic", "1", needle, {scope}, index)


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------


def test_search_scope_keys_translated_in_all_languages():
    from kemonodownloader.kd_language import language_manager, translate

    keys = [
        "search_scope",
        "search_scope_title_toggle",
        "search_scope_filenames_toggle",
        "search_scope_description_toggle",
        "search_scope_tags_toggle",
    ]
    original = language_manager.current_language
    try:
        for language in language_manager.get_available_languages():
            language_manager.set_language(language)
            for key in keys:
                assert translate(key) not in ("", key)
    finally:
        language_manager.set_language(original)
