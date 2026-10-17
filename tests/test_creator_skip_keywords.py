"""Tests for keyword matching against post descriptions.

The description scope matches against two renderings of the post HTML: the
space-joined string that has always been used, and a tag-glued string that
only removes the separators BeautifulSoup injects between inline elements.
These tests pin both the recovered matches and the cases that must stay
unmatched (author-typed whitespace, ``&nbsp;``, block boundaries).
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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


def _make_thread(keywords, scopes, messages=None):
    settings = SimpleNamespace(creator_posts_max_attempts=1, settings_tab=None)
    thread = cd.PostDetectionThread(
        "https://kemono.cr/patreon/user/1",
        {},
        settings,
        skip_keywords=keywords,
        skip_keywords_scopes=scopes,
    )
    log = _signal()
    if messages is not None:
        log.emit.side_effect = lambda message, level="INFO": messages.append(
            (message, level)
        )
    thread.log = log
    return thread


def _skip(keywords, scopes, post, title="Some post", messages=None):
    thread = _make_thread(keywords, scopes, messages)
    return thread._title_matches_skip_keyword(title, post)


# ---------------------------------------------------------------------------
# Candidate renderings
# ---------------------------------------------------------------------------


def test_candidates_keep_first_rendering_first():
    thread = _make_thread(["x"], {"description"})
    texts = thread._gather_post_description_texts(
        {"content": "<p>Alien <b>Comic</b></p>"}
    )

    assert texts[0] == "Alien  Comic"  # unchanged legacy rendering
    assert len(texts) == 2
    assert texts[1].strip() == "Alien Comic"  # inline tag re-joined


def test_candidates_single_entry_when_renderings_agree():
    thread = _make_thread(["x"], {"description"})

    assert thread._gather_post_description_texts({"content": "plain text"}) == (
        "plain text",
    )


@pytest.mark.parametrize("content", [None, "", {}, 123, []])
def test_candidates_tolerate_missing_or_odd_content(content):
    thread = _make_thread(["x"], {"description"})

    assert thread._gather_post_description_texts({"content": content}) == ()


def test_gather_post_description_still_returns_space_joined_text():
    thread = _make_thread(["x"], {"description"})
    post = {"content": "<p>Alien <b>Comic</b></p>"}

    assert thread._gather_post_description(post) == "Alien  Comic"
    assert thread._gather_post_description({}) == ""
    assert thread._gather_post_description({"content": 123}) == ""


# ---------------------------------------------------------------------------
# Matches recovered by re-joining inline tags
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("keyword", "content"),
    [
        # A word split by an inline tag: the page shows one word.
        ("AlienComic", "<p><b>Alien</b>Comic</p>"),
        # One author-typed space next to an inline tag: the old rendering
        # doubled it, so a single-space phrase could not match.
        ("Alien Comic", "<p>Alien <b>Comic</b></p>"),
        ("Alien Comic", "<p><b>Alien</b> Comic</p>"),
        ("SketchBook", "<p>Sketch<b>Book</b> dump</p>"),
        ("pre-order", "<p>pre<b>-</b>order now</p>"),
        ("visitmysite", "<p>visit<a href='/x'>my</a>site</p>"),
        ("Alien test Comic", "<p>Alien <b>test</b> Comic</p>"),
    ],
)
def test_rejoined_rendering_recovers_visible_keywords(keyword, content):
    messages = []

    assert _skip([keyword], {"description"}, {"content": content}, messages=messages)

    rejoin_logs = [m for m in messages if "[SKIP-KEYWORD]" in m[0]]
    assert len(rejoin_logs) == 1
    assert rejoin_logs[0][1] == "DEBUG"
    assert keyword in rejoin_logs[0][0]


def test_rejoined_hit_logs_the_matching_keyword():
    messages = []

    assert _skip(
        ["no-such-word", "AlienComic"],
        {"description"},
        {"content": "<p><b>Alien</b>Comic</p>"},
        messages=messages,
    )

    logged = [m for m, _level in messages if "[SKIP-KEYWORD]" in m]
    assert logged and "AlienComic" in logged[0]
    assert "no-such-word" not in logged[0]


def test_old_rendering_hit_does_not_emit_the_rejoin_log():
    messages = []

    # The legacy rendering invents a space, so "sketch" matches "Sketch Book".
    assert _skip(
        ["sketch"],
        {"description"},
        {"content": "<p><b>Sketch</b>Book</p>"},
        messages=messages,
    )

    assert not [m for m, _level in messages if "[SKIP-KEYWORD]" in m]


def test_old_rendering_keeps_matching_a_mid_word_tag_split():
    # "visit my site" today -> the keyword "my" must keep matching.
    assert _skip(["my"], {"description"}, {"content": "<p>visit<a>my</a>site</p>"})


# ---------------------------------------------------------------------------
# Cases that must stay unmatched
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("keyword", "content"),
    [
        # Author typed an extra space: no normalization happens.
        ("Alien Comic", "<p>Alien <b> Comic</b></p>"),
        # Non-breaking space is not a word separator.
        ("JP version", "<p>JP&nbsp;version</p>"),
        # Block-level elements stay boundaries: paragraphs never fuse.
        ("AlienComic", "<p>Alien</p><p>Comic</p>"),
        ("AlienComic", "<p>Alien<br>Comic</p>"),
        ("AlienComic", "<div>Alien</div><div>Comic</div>"),
        # Style text is not part of the description.
        ("sketch", "<style>.sketch{color:red}</style><p>body</p>"),
        # Whole-word semantics are unchanged.
        ("sketch", "<p>Sketches</p>"),
    ],
)
def test_no_new_match_for_preserved_author_whitespace(keyword, content):
    assert not _skip([keyword], {"description"}, {"content": content})


# ---------------------------------------------------------------------------
# Scope isolation: only the description branch changes
# ---------------------------------------------------------------------------


def test_description_match_ignored_when_scope_is_title():
    post = {"title": "Something", "content": "<p><b>Alien</b>Comic</p>"}

    assert not _skip(["AlienComic"], {"title"}, post)


def test_description_match_ignored_with_empty_scope_set():
    post = {"content": "<p><b>Alien</b>Comic</p>"}

    assert not _skip(["AlienComic"], set(), post)


def test_no_keywords_means_no_match():
    post = {"content": "<p><b>Alien</b>Comic</p>"}

    assert not _skip([], {"description"}, post)


def test_missing_post_dict_is_tolerated():
    assert not _skip(["AlienComic"], {"description"}, None)


def test_titles_are_matched_raw_without_html_parsing():
    post = {"title": "<b>Alien</b>Comic"}

    # Raw text only: the markup is not stripped, so the fused keyword misses.
    assert not _skip(["AlienComic"], {"title"}, post, title=post["title"])
    # ...but a keyword that is a whole word in the raw text still matches.
    assert _skip(["Alien"], {"title"}, post, title=post["title"])


def test_filenames_scope_is_unaffected():
    post = {
        "title": "Something",
        "content": "<p><b>Alien</b>Comic</p>",
        "file": {"name": "Alien-01.png", "path": "/ab/cd/hash.png"},
    }

    assert not _skip(["AlienComic"], {"filenames"}, post)


def test_first_matching_keyword_helper():
    assert cd._first_matching_keyword(["nope", "AlienComic"], "AlienComic") == (
        "AlienComic"
    )
    assert cd._first_matching_keyword(["nope"], "AlienComic") == ""
    assert cd._first_matching_keyword([], "AlienComic") == ""


# ---------------------------------------------------------------------------
# End-to-end detection run
# ---------------------------------------------------------------------------


def _run_detection(monkeypatch, keyword, content):
    posts = [{"id": "1", "title": "Test post", "content": content}]
    text = json.dumps(posts)
    resp = Resp(text.encode("utf-8"), text=text)

    class Session:
        def get(self, *args, **kwargs):
            return resp

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: Session())

    thread = _make_thread([keyword], {"description"})
    thread.posts_batch = _signal()
    thread.finished = _signal()
    thread.run()
    return thread


def test_run_drops_post_matched_only_after_rejoining(monkeypatch):
    thread = _run_detection(monkeypatch, "AlienComic", "<p><b>Alien</b>Comic</p>")

    thread.posts_batch.emit.assert_not_called()
    assert thread.keyword_skipped_count == 1
    assert thread.filtered_count == 1
    assert thread.total_detected == 1
    assert thread.finished.emit.call_args[0][0] == []


def test_run_keeps_post_when_description_does_not_match(monkeypatch):
    thread = _run_detection(monkeypatch, "AlienComic", "<p>Something else</p>")

    thread.posts_batch.emit.assert_called_once()
    assert thread.keyword_skipped_count == 0
    assert thread.filtered_count == 0
    assert len(thread.finished.emit.call_args[0][0]) == 1


def test_run_still_drops_post_matched_by_the_old_rendering(monkeypatch):
    thread = _run_detection(monkeypatch, "sketch", "<p><b>Sketch</b>Book</p>")

    thread.posts_batch.emit.assert_not_called()
    assert thread.keyword_skipped_count == 1


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------


def test_rejoin_log_translated_in_all_languages():
    from kemonodownloader.kd_language import language_manager, translate

    original = language_manager.current_language
    try:
        for language in language_manager.get_available_languages():
            language_manager.set_language(language)
            text = translate("skip_keyword_matched_after_rejoin", "AlienComic")
            assert text != "skip_keyword_matched_after_rejoin"
            assert "AlienComic" in text
    finally:
        language_manager.set_language(original)
