"""Unit tests for the shared post-filter rules.

The fetch and the live filter pass both call these, so a post can never be
judged one way while fetching and another way while filtering.
"""

from datetime import date

import kemonodownloader.creator_downloader as cd



def facts(**overrides):
    """A post that passes every filter, with just enough to test one rule."""
    base = {
        "filenames": "a.png",
        "filenames_list": ["a.png"],
        "description": "",
        "description_glued": "",
        "tags": "",
        "tag_list": [],
        "file_count": 1,
        "has_compressed": False,
        "extensions": [".png"],
        "published": date(2024, 6, 1),
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Skip keywords
# ---------------------------------------------------------------------------


def test_keywords_match_the_title_by_default():
    filters = cd.PostFilters(skip_keywords=("art", "sketch"))

    assert cd.post_skip_reason("My art dump", facts(), filters) == ("keywords", "art")
    assert cd.post_skip_reason("Plain post", facts(), filters) == (None, "")


def test_keywords_only_look_at_the_enabled_scopes():
    post = facts(filenames_list=["art.png"], tag_list=["art"])

    assert cd.keyword_skip_reason("Plain", post, cd.PostFilters(skip_keywords=("art",))) == ""
    assert (
        cd.keyword_skip_reason(
            "Plain", post, cd.PostFilters(skip_keywords=("art",), skip_scopes=frozenset({"filenames"}))
        )
        == "art"
    )


def test_keywords_fall_back_to_the_tag_glued_description():
    post = facts(description="alien comic", description_glued="aliencomic")
    filters = cd.PostFilters(
        skip_keywords=("aliencomic",), skip_scopes=frozenset({"description"})
    )

    assert cd.keyword_skip_reason("Plain", post, filters) == "aliencomic"
    assert cd.keyword_needed_rejoin("aliencomic", post, filters) is True


def test_an_old_rendering_hit_needs_no_rejoin_note():
    post = facts(description="alien comic", description_glued="")
    filters = cd.PostFilters(
        skip_keywords=("alien",), skip_scopes=frozenset({"description"})
    )

    assert cd.keyword_needed_rejoin("alien", post, filters) is False


def test_no_ticked_scope_means_no_keyword_skipping():
    filters = cd.PostFilters(skip_keywords=("art",), skip_scopes=frozenset())

    # Unticking every scope has always meant "do not skip by keyword".
    assert cd.post_skip_reason("art bundle", facts(), filters) == (None, "")


# ---------------------------------------------------------------------------
# Date range
# ---------------------------------------------------------------------------


def test_date_range_is_inclusive():
    filters = cd.PostFilters(date_after=date(2024, 6, 1), date_before=date(2024, 6, 1))

    assert cd.date_out_of_range(facts(), filters) is False
    assert cd.date_out_of_range(facts(published=date(2024, 5, 31)), filters) is True
    assert cd.date_out_of_range(facts(published=date(2024, 6, 2)), filters) is True


def test_unknown_date_is_kept():
    filters = cd.PostFilters(date_after=date(2024, 6, 1))

    assert cd.date_out_of_range(facts(published=None), filters) is False


# ---------------------------------------------------------------------------
# File count
# ---------------------------------------------------------------------------


def test_file_count_bounds_are_inclusive():
    filters = cd.PostFilters(file_count_min=2, file_count_max=4)

    assert cd.file_count_out_of_range(facts(file_count=1), filters) is True
    assert cd.file_count_out_of_range(facts(file_count=2), filters) is False
    assert cd.file_count_out_of_range(facts(file_count=4), filters) is False
    assert cd.file_count_out_of_range(facts(file_count=5), filters) is True


def test_keep_archives_lets_an_archive_post_through():
    filters = cd.PostFilters(file_count_min=9, keep_compressed=True)

    assert cd.file_count_out_of_range(facts(file_count=1, has_compressed=True), filters) is False
    assert cd.file_count_out_of_range(facts(file_count=1), filters) is True


# ---------------------------------------------------------------------------
# Filetypes
# ---------------------------------------------------------------------------


def test_filetypes_need_one_matching_file():
    filters = cd.PostFilters(required_filetypes=frozenset({".psd"}))

    assert cd.filetypes_out_of_scope(facts(extensions=[".psd", ".png"]), filters) is False
    assert cd.filetypes_out_of_scope(facts(extensions=[".png"]), filters) is True


def test_posts_with_no_readable_files_are_kept():
    filters = cd.PostFilters(required_filetypes=frozenset({".psd"}))

    assert cd.filetypes_out_of_scope(facts(extensions=[]), filters) is False


def test_jpeg_files_count_as_jpg_for_the_filetype_filter():
    post = cd.analyze_post({"id": "1", "attachments": [{"name": "p.jpeg"}]})
    filters = cd.PostFilters(required_filetypes=frozenset({".jpg"}))

    assert cd.post_skip_reason("JPEG post", post, filters) == (None, "")


# ---------------------------------------------------------------------------
# One skip, one reason
# ---------------------------------------------------------------------------


def test_the_first_matching_filter_books_the_post():
    post = facts(
        published=date(2020, 1, 1),
        file_count=10,
        extensions=[".png"],
    )
    filters = cd.PostFilters(
        skip_keywords=("art",),
        date_after=date(2024, 1, 1),
        file_count_max=2,
        required_filetypes=frozenset({".psd"}),
    )

    assert cd.post_skip_reason("art bundle", post, filters) == ("keywords", "art")
    assert cd.post_skip_reason("plain bundle", post, filters) == ("date", "")


def test_posts_without_facts_are_kept():
    filters = cd.PostFilters(
        skip_keywords=("art",),
        date_after=date(2024, 1, 1),
        file_count_min=5,
        required_filetypes=frozenset({".psd"}),
    )

    assert cd.post_skip_reason("art bundle", None, filters) == (None, "")
