"""Tests for the Creator tab's Recommended Keywords scan and window.

The scan is local: it reads the post rows and the per-post index the tab
already built.  These tests pin the phrase boundaries, the per-post counting,
the scope rules and the UI wiring without touching the network or a real
SettingsTab.
"""

from PyQt6.QtCore import QItemSelectionModel
from PyQt6.QtWidgets import QApplication, QGridLayout
from tests.factories import Signal, make_tab_parent

from kemonodownloader import creator_downloader as cd, kd_recommended as rec, kd_theme
from kemonodownloader.kd_language import translate

INDEX = {
    "1": {
        "tag_list": ["AlienComic", "Sci-Fi"],
        "description": "a sketch dump of aliens. cats, dogs",
        "filenames_list": ["Alien-01.png", "BlackCat_01.webp"],
    },
    "2": {
        "tag_list": ["AlienComic", "Cats"],
        "description": "more alien sketches cats",
        "filenames_list": ["Alien-02.png", "BlackCat_02.webp"],
    },
    "3": {
        "tag_list": ["Cats"],
        "description": "don't forget the cat cafe visit https://example.com/art",
        "filenames_list": ["Cat_Study_01.png"],
    },
}
ROWS = [("1", "Alien Comic Page 3"), ("2", "Alien Comic Page 4"), ("3", "Post 3")]


def _count(**kwargs):
    defaults = {
        "min_count": 2,
        "max_words": 3,
        "ignore_common_words": True,
        "limit": 50,
    }
    defaults.update(kwargs)
    return rec.count_recommended_keywords(ROWS, INDEX, **defaults)


def _by_keyword(results):
    return {item.match_key: item for item in results}


def test_normalize_key_folds_width_and_case_but_keeps_kana_marks():
    assert rec.normalize_key("Ａｌｉｅｎ") == "alien"
    assert rec.normalize_key("Don\u2019t") == "don't"
    assert rec.normalize_key("  3D   Art ") == "3d art"

    # Accent folding must not strip the Japanese dakuten.
    assert rec.normalize_key("ブルーアーカイブ", ignore_accents=True) == (
        "ブルーアーカイブ"
    )
    assert rec.normalize_key("café", ignore_accents=True) == "cafe"


def test_tags_are_counted_as_whole_values():
    results = _by_keyword(_count(scopes={"tags"}))

    assert results["aliencomic"].count == 2
    assert results["aliencomic"].mentions == 2
    assert results["aliencomic"].scopes == frozenset({"tags"})
    assert results["cats"].count == 2

    # A tag's punctuation and spacing are part of the value, not a separator.
    single = _by_keyword(_count(scopes={"tags"}, min_count=1))
    assert single["sci-fi"].count == 1
    assert "sci fi" not in single


def test_tag_case_variants_share_one_count_and_keep_every_spelling():
    index = {
        "1": {"tag_list": ["BlackCat"]},
        "2": {"tag_list": ["blackcat"]},
    }

    results = rec.count_recommended_keywords(
        [("1", ""), ("2", "")], index, scopes={"tags"}, min_count=2
    )

    assert len(results) == 1
    assert results[0].count == 2
    assert set(results[0].variants) == {"BlackCat", "blackcat"}
    assert results[0].keyword in {"BlackCat", "blackcat"}


def test_title_phrases_only_join_across_whitespace():
    results = _by_keyword(_count(scopes={"title"}))

    assert results["alien comic"].count == 2
    assert results["alien comic page"].count == 2
    assert results["alien comic page"].mentions == 2
    # The trailing digit is dropped and ends the chain.
    assert "alien comic page 3" not in results
    assert "3" not in results
    # "Post 3" is the API's untitled fallback, not a real keyword.
    assert "post" not in results


def test_longer_phrase_ranks_before_its_own_words_on_a_tie():
    results = _count(scopes={"title"})

    assert results[0].match_key == "alien comic page"
    assert results[0].keyword == "Alien Comic Page"
    assert results[0].count == 2


def test_punctuation_and_dropped_tokens_break_phrases():
    index = {
        "1": {"description": "cats, dogs and page 3 art"},
        "2": {"description": "cats, dogs and page 3 art"},
    }
    results = _by_keyword(
        rec.count_recommended_keywords(
            [("1", ""), ("2", "")],
            index,
            scopes={"description"},
            min_count=2,
        )
    )

    assert results["cats"].count == 2
    assert results["dogs"].count == 2
    assert results["art"].count == 2
    assert "cats dogs" not in results
    assert "page art" not in results


def test_description_scope_does_not_borrow_title_words():
    results = _by_keyword(_count(scopes={"description"}))

    assert set(results) == {"cats"}
    assert "alien" not in results
    assert "alien comic" not in results


def test_filename_stems_split_on_camel_case_and_drop_extensions():
    results = _by_keyword(_count(scopes={"filenames"}))

    assert results["black cat"].count == 2
    assert results["black cat"].keyword == "BlackCat"
    assert results["black cat"].variants == ("BlackCat",)
    assert results["black cat"].scopes == frozenset({"filenames"})
    assert results["alien"].count == 2

    assert "png" not in results
    assert "webp" not in results
    assert "01" not in results


def test_stopword_edges_are_dropped_but_interior_words_survive():
    index = {
        "1": {"description": "the art of war"},
        "2": {"description": "the art of war"},
    }
    rows = [("1", ""), ("2", "")]

    filtered = _by_keyword(
        rec.count_recommended_keywords(rows, index, scopes={"description"}, min_count=2)
    )
    assert "art of war" in filtered
    assert "art" in filtered
    assert "the" not in filtered
    assert "the art" not in filtered
    assert "of" not in filtered

    unfiltered = _by_keyword(
        rec.count_recommended_keywords(
            rows,
            index,
            scopes={"description"},
            min_count=2,
            ignore_common_words=False,
        )
    )
    assert "the" in unfiltered
    assert "the art" in unfiltered


def test_apostrophes_stay_inside_a_word():
    index = {
        "1": {"description": "don't stop"},
        "2": {"description": "don't stop"},
    }
    rows = [("1", ""), ("2", "")]

    results = _by_keyword(
        rec.count_recommended_keywords(
            rows,
            index,
            scopes={"description"},
            min_count=2,
            ignore_common_words=False,
        )
    )

    assert "don't" in results
    assert "don't stop" in results
    assert "don" not in results


def test_common_word_filter_drops_contractions_at_the_edge():
    index = {
        "1": {"description": "don't stop"},
        "2": {"description": "don't stop"},
    }
    results = _by_keyword(
        rec.count_recommended_keywords(
            [("1", ""), ("2", "")], index, scopes={"description"}, min_count=2
        )
    )

    assert "stop" in results
    assert "don't" not in results
    assert "don't stop" not in results


def test_accent_folding_merges_spellings_and_keeps_every_variant():
    index = {
        "1": {"description": "café art"},
        "2": {"description": "cafe art"},
    }
    rows = [("1", ""), ("2", "")]

    plain = _by_keyword(
        rec.count_recommended_keywords(rows, index, scopes={"description"}, min_count=2)
    )
    assert "art" in plain
    assert "café" not in plain
    assert "cafe" not in plain

    folded = _by_keyword(
        rec.count_recommended_keywords(
            rows,
            index,
            scopes={"description"},
            min_count=2,
            ignore_accents=True,
        )
    )
    assert folded["cafe"].count == 2
    assert set(folded["cafe"].variants) == {"cafe", "café"}


def test_one_vote_per_post_but_every_occurrence_is_a_mention():
    index = {
        "1": {"description": "cat cat cat"},
        "2": {"description": "cat"},
    }
    results = _by_keyword(
        rec.count_recommended_keywords(
            [("1", ""), ("2", "")], index, scopes={"description"}, min_count=2
        )
    )

    assert results["cat"].count == 2
    assert results["cat"].mentions == 4


def test_urls_and_handles_are_not_keywords():
    index = {
        "1": {"description": "see art at https://example.com/x now"},
        "2": {"description": "see art at https://example.com/x now"},
    }
    results = _by_keyword(
        rec.count_recommended_keywords(
            [("1", ""), ("2", "")], index, scopes={"description"}, min_count=1
        )
    )

    assert "art" in results
    assert "https" not in results
    assert "example" not in results
    assert "com" not in results


def test_min_count_is_an_inclusive_lower_bound():
    index = {
        "1": {"tag_list": ["Cats"]},
        "2": {"tag_list": ["Cats"]},
        "3": {"tag_list": ["Cats"]},
    }
    rows = [("1", ""), ("2", ""), ("3", "")]

    included = rec.count_recommended_keywords(rows, index, scopes={"tags"}, min_count=3)
    excluded = rec.count_recommended_keywords(rows, index, scopes={"tags"}, min_count=4)

    assert included[0].keyword == "Cats"
    assert included[0].count == 3
    assert excluded == []


def test_limit_caps_the_result_list():
    results = rec.count_recommended_keywords(
        ROWS, INDEX, scopes={"title"}, min_count=2, limit=1
    )

    assert len(results) == 1


def test_zero_limit_returns_every_match():
    results = rec.count_recommended_keywords(
        ROWS, INDEX, scopes={"title"}, min_count=2, limit=0
    )

    assert len(results) > 1


def test_empty_file_names_and_tags_are_ignored():
    index = {
        "1": {"filenames_list": ["", "   "], "tag_list": ["", "   "]},
        "2": {"filenames_list": ["", "   "], "tag_list": ["", "   "]},
    }

    results = rec.count_recommended_keywords(
        [("1", ""), ("2", "")],
        index,
        scopes={"filenames", "tags"},
        min_count=1,
    )

    assert results == []


def test_cancel_abandons_the_scan():
    assert (
        rec.count_recommended_keywords(
            ROWS, INDEX, scopes={"title"}, cancel=lambda: True
        )
        == []
    )


def test_no_selected_scope_falls_back_to_the_title():
    results = rec.count_recommended_keywords(ROWS, INDEX, scopes=set(), min_count=2)

    assert _by_keyword(results)["alien comic"].count == 2
    assert all(item.scopes == frozenset({"title"}) for item in results)


def test_a_string_tag_list_is_split_on_commas():
    index = {
        "1": {"tag_list": "AlienComic,Cats"},
        "2": {"tag_list": "AlienComic,Cats"},
    }

    results = rec.count_recommended_keywords(
        [("1", ""), ("2", "")], index, scopes={"tags"}, min_count=2
    )

    assert _by_keyword(results)["aliencomic"].count == 2
    assert _by_keyword(results)["cats"].count == 2


def test_legacy_space_joined_tags_fall_back_to_individual_tags():
    index = {
        "1": {"tags": "aliencomic sci-fi"},
        "2": {"tags": "aliencomic cats"},
    }

    results = rec.count_recommended_keywords(
        [("1", ""), ("2", "")], index, scopes={"tags"}, min_count=2
    )

    assert _by_keyword(results)["aliencomic"].count == 2
    assert _by_keyword(results)["aliencomic"].keyword == "aliencomic"


def test_a_tag_is_one_phrase_even_when_it_has_several_words():
    index = {
        "1": {"tag_list": ["3D art"]},
        "2": {"tag_list": ["3D art"]},
    }

    results = rec.count_recommended_keywords(
        [("1", ""), ("2", "")],
        index,
        scopes={"tags"},
        min_count=2,
        max_words=1,
    )

    assert len(results) == 1
    assert results[0].keyword == "3D art"
    assert results[0].count == 2


def test_a_post_without_index_facts_still_counts_its_title():
    results = rec.count_recommended_keywords(
        [("1", "Alien Comic"), ("2", "Alien Comic")],
        {},
        scopes={"title", "tags"},
        min_count=2,
    )

    assert _by_keyword(results)["alien comic"].count == 2


def test_format_keyword_values_round_trips_commas_and_quotes():
    values = ["cat", "Hello, world", 'say "hi"', "back\\slash"]

    text = cd.format_keyword_values(values)

    assert '"Hello, world"' in text
    assert cd.parse_keyword_values(text) == values


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


def _result(
    keyword="AlienComic",
    count=2,
    mentions=2,
    scopes=frozenset({"tags"}),
    match_key="aliencomic",
    variants=("AlienComic",),
):
    return rec.RecommendedKeyword(
        keyword=keyword,
        count=count,
        mentions=mentions,
        scopes=scopes,
        match_key=match_key,
        variants=variants,
    )


class FakeRecommendedThread:
    """Stand-in worker that emits a fixed result list on start."""

    instances = []
    results = []

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.finished = Signal()
        self.running = False
        FakeRecommendedThread.instances.append(self)

    def start(self):
        self.running = True
        self.finished.emit(list(FakeRecommendedThread.results))
        self.running = False

    def isRunning(self):
        return self.running

    def stop(self):
        self.running = False

    def wait(self, _timeout=0):
        return True

    def deleteLater(self):
        pass


def _patch_thread(monkeypatch, results=None):
    FakeRecommendedThread.instances = []
    FakeRecommendedThread.results = list(results or [])
    monkeypatch.setattr(cd, "RecommendedKeywordsThread", FakeRecommendedThread)
    return FakeRecommendedThread.instances


def _make_tab(qtbot, tmp_path):
    tab = cd.CreatorDownloaderTab(make_tab_parent(tmp_path))
    qtbot.addWidget(tab)
    return tab


def _seed_posts(tab):
    tab.all_detected_posts = [
        ("Alien Comic", ("1", None)),
        ("Alien Comic", ("2", None)),
    ]
    tab.post_search_index = {
        "1": {"tag_list": ["AlienComic"], "description": "", "filenames_list": []},
        "2": {"tag_list": ["AlienComic"], "description": "", "filenames_list": []},
    }


def test_keyword_rows_line_up_without_a_label(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab.update_ui_text()

    assert tab.creator_sort_enabled_check.text() == ""
    assert tab.creator_sort_rules_btn.text() == "Keyword Folder Sorting"
    assert tab.creator_recommended_btn.text() == "Recommended Keywords"

    layout = tab.creator_options_group.layout()
    sort_grid = None
    for index in range(layout.count()):
        candidate = layout.itemAt(index).layout()
        if isinstance(candidate, QGridLayout) and (
            candidate.indexOf(tab.creator_sort_enabled_check) >= 0
        ):
            sort_grid = candidate
            break
    assert sort_grid is not None

    def position(widget):
        return sort_grid.getItemPosition(sort_grid.indexOf(widget))[:2]

    # The switch shares row 0 with the folder button; the recommended button
    # is directly below it in the same column.
    assert position(tab.creator_sort_enabled_check) == (0, 0)
    assert position(tab.creator_sort_rules_btn) == (0, 1)
    assert position(tab.creator_recommended_btn) == (1, 1)


def test_all_check_boxes_use_the_shared_theme_style(qtbot, tmp_path):
    style = kd_theme.checkbox_style()

    assert "width: 16px" in style
    assert "height: 16px" in style
    assert "QCheckBox::indicator:hover" in style
    assert "QCheckBox::indicator:checked" in style
    assert "QCheckBox::indicator:indeterminate" in style
    assert "QCheckBox::indicator:disabled" in style
    assert "image: url(" in style
    assert "checkbox_checked_4863b8.png" in style
    assert "checkbox_minus_4863b8.png" in style

    tab = _make_tab(qtbot, tmp_path)
    # The formerly custom boxes no longer override the shared indicator; the
    # ordinary ones never did, so every checkbox now gets the same theme rule.
    assert "QCheckBox::indicator" not in tab.creator_sort_enabled_check.styleSheet()
    assert "QCheckBox::indicator" not in tab.creator_main_check.styleSheet()


def test_dialog_matches_the_sort_editor_styling(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [_result()])
    dialog = cd.RecommendedKeywordsDialog([], {})
    sort_dialog = cd.SortRulesDialog([], False, False, [], {}, set())
    qtbot.addWidget(dialog)
    qtbot.addWidget(sort_dialog)

    assert dialog.windowTitle() == "Recommended Keywords"
    assert dialog.styleSheet() == sort_dialog.styleSheet()
    assert "#2B2D31" in dialog._table.styleSheet()
    assert "#2B2D31" in sort_dialog._rule_list.styleSheet()


def test_post_is_text_only_requires_known_empty_file_facts():
    assert cd.post_is_text_only({"file_count": 0, "filenames_list": []})
    assert not cd.post_is_text_only({"file_count": 1, "filenames_list": []})
    assert not cd.post_is_text_only({"file_count": 0, "filenames_list": ["page.jpg"]})
    assert not cd.post_is_text_only({"file_count": 0, "extensions": [".jpg"]})
    assert not cd.post_is_text_only({"tag_list": []})
    assert not cd.post_is_text_only(None)


def test_recommended_scan_ignores_text_posts_by_default(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [])
    index = {
        "1": {"tag_list": ["Sketch"], "file_count": 0, "filenames_list": []},
        "2": {"tag_list": ["Sketch"], "file_count": 2, "filenames_list": ["a.jpg"]},
    }
    posts = [("Text post", ("1", None)), ("Art post", ("2", None))]
    dialog = cd.RecommendedKeywordsDialog(posts, index)
    qtbot.addWidget(dialog)

    assert dialog._ignore_text_posts.isChecked()
    assert FakeRecommendedThread.instances[-1].args[0] == [("2", "Art post")]

    dialog._ignore_text_posts.setChecked(False)
    dialog._start_scan()
    assert FakeRecommendedThread.instances[-1].args[0] == [
        ("1", "Text post"),
        ("2", "Art post"),
    ]
    dialog.close()


def test_recommended_scan_hides_keywords_covered_by_skip_filters(qtbot, monkeypatch):
    _patch_thread(
        monkeypatch,
        [
            _result(),
            _result(
                keyword="Sketch",
                count=2,
                mentions=3,
                scopes=frozenset({"title"}),
                match_key="sketch",
                variants=("Sketch",),
            ),
        ],
    )
    filters = cd.PostFilters(
        skip_keywords=("Alien*",),
        skip_scopes=frozenset({"tags"}),
    )
    dialog = cd.RecommendedKeywordsDialog(
        [], {}, options={"ignore_filtered_keywords": True}, filters=filters
    )
    qtbot.addWidget(dialog)

    assert dialog._ignore_filtered_keywords.isChecked()
    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 0).text() == "Sketch"
    assert translate("recommended_keywords_ignored_filters", 1) in (
        dialog._status_label.text()
    )

    dialog._ignore_filtered_keywords.setChecked(False)

    assert dialog._table.rowCount() == 2
    assert translate("recommended_keywords_ignored_filters", 1) not in (
        dialog._status_label.text()
    )
    dialog.close()


def test_recommended_scan_hides_file_filter_keywords_for_filename_results(
    qtbot, monkeypatch
):
    _patch_thread(
        monkeypatch,
        [
            _result(
                keyword="BlackCat",
                scopes=frozenset({"filenames"}),
                match_key="black cat",
                variants=("BlackCat",),
            ),
            _result(
                keyword="AlienComic",
                scopes=frozenset({"tags"}),
            ),
        ],
    )
    dialog = cd.RecommendedKeywordsDialog(
        [],
        {},
        options={"ignore_filtered_keywords": True},
        filters=cd.PostFilters(),
        file_skip_keywords=("BlackCat",),
    )
    qtbot.addWidget(dialog)

    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 0).text() == "AlienComic"
    dialog.close()


def test_recommended_filters_can_change_after_the_scan(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [_result()])
    posts = [("Alien Comic", ("1", None))]
    dialog = cd.RecommendedKeywordsDialog(
        posts, {}, options={"ignore_filtered_keywords": True}
    )
    qtbot.addWidget(dialog)

    assert dialog._table.rowCount() == 1

    dialog.set_filters(
        cd.PostFilters(
            skip_keywords=("AlienComic",),
            skip_scopes=frozenset({"tags"}),
        )
    )

    assert dialog._table.rowCount() == 0
    assert dialog._empty_label.text() == translate(
        "recommended_keywords_empty_filtered"
    )

    dialog.set_filters(cd.PostFilters())

    assert dialog._table.rowCount() == 1
    dialog.close()


def test_recommended_scan_deduplicates_post_ids():
    results = rec.count_recommended_keywords(
        [("1", "Alien Comic"), ("1", "Alien Comic")],
        {"1": {"tag_list": ["AlienComic"]}},
        scopes={"tags"},
        min_count=1,
    )

    assert [(item.keyword, item.count) for item in results] == [("AlienComic", 1)]


def test_dialog_defaults_to_title_and_tags_and_lists_results(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [_result()])
    dialog = cd.RecommendedKeywordsDialog([], {})
    qtbot.addWidget(dialog)

    assert dialog._scope_checks["title"].isChecked()
    assert dialog._scope_checks["tags"].isChecked()
    assert not dialog._scope_checks["description"].isChecked()
    assert not dialog._scope_checks["filenames"].isChecked()
    assert dialog._min_posts.value() == 2
    assert dialog._max_words.currentData() == 3
    assert dialog._ignore_common.isChecked()
    assert not dialog._ignore_accents.isChecked()
    assert dialog._ignore_text_posts.isChecked()
    assert not dialog._ignore_filtered_keywords.isChecked()

    assert dialog._table.rowCount() == 1
    assert dialog._table.item(0, 0).text() == "AlienComic"
    assert dialog._table.item(0, 1).text() == "2"
    assert dialog._table.item(0, 2).text() == "2"
    assert dialog._search_btn.isEnabled()
    assert dialog._empty_label.isHidden()


def test_empty_scan_shows_the_hint_and_disables_actions(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [])
    dialog = cd.RecommendedKeywordsDialog([], {})
    qtbot.addWidget(dialog)

    assert dialog._table.rowCount() == 0
    assert not dialog._empty_label.isHidden()
    assert dialog._empty_label.text() == translate("recommended_keywords_no_posts")
    assert not dialog._search_btn.isEnabled()
    assert not dialog._add_skip_btn.isEnabled()
    assert not dialog._copy_btn.isEnabled()


def test_all_text_posts_explain_the_scan_option(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [])
    index = {"1": {"file_count": 0, "filenames_list": []}}
    dialog = cd.RecommendedKeywordsDialog([("Text post", ("1", None))], index)
    qtbot.addWidget(dialog)

    assert dialog._empty_label.text() == translate(
        "recommended_keywords_only_text_posts"
    )
    dialog.close()


def test_no_matches_with_posts_loaded_explains_the_threshold(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [])
    dialog = cd.RecommendedKeywordsDialog([("A post", ("1", None))], {})
    qtbot.addWidget(dialog)

    assert dialog._table.rowCount() == 0
    assert not dialog._empty_label.isHidden()
    assert dialog._empty_label.text() == translate("recommended_keywords_empty")


def test_dialog_passes_its_controls_to_the_scan(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [_result()])
    dialog = cd.RecommendedKeywordsDialog([], {})
    qtbot.addWidget(dialog)

    dialog._scope_checks["title"].setChecked(False)
    dialog._min_posts.setValue(5)
    dialog._max_words.setCurrentIndex(0)
    dialog._ignore_accents.setChecked(True)
    dialog._start_scan()

    thread = FakeRecommendedThread.instances[-1]
    assert thread.args[2] == {"tags"}
    assert thread.kwargs["min_count"] == 5
    assert thread.kwargs["max_words"] == 1
    assert thread.kwargs["ignore_accents"] is True


def test_dialog_search_emits_the_keyword_and_its_scopes(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [_result()])
    dialog = cd.RecommendedKeywordsDialog([], {})
    qtbot.addWidget(dialog)
    captured = []
    dialog.search_requested.connect(
        lambda keyword, scopes: captured.append((keyword, scopes))
    )

    dialog._table.selectRow(0)
    dialog._search_btn.click()

    assert captured == [("AlienComic", frozenset({"title", "tags"}))]


def test_dialog_add_to_skip_emits_every_variant_and_the_result_scopes(
    qtbot, monkeypatch
):
    _patch_thread(
        monkeypatch,
        [
            _result(
                keyword="cafe",
                scopes=frozenset({"description"}),
                match_key="cafe",
                variants=("cafe", "café"),
            )
        ],
    )
    dialog = cd.RecommendedKeywordsDialog([], {})
    qtbot.addWidget(dialog)
    captured = []
    dialog.skip_keywords_requested.connect(
        lambda variants, scopes: captured.append((variants, scopes))
    )

    dialog._add_skip_btn.click()

    assert captured == [(("cafe", "café"), frozenset({"description"}))]


def test_dialog_copy_puts_the_keyword_on_the_clipboard(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [_result()])
    dialog = cd.RecommendedKeywordsDialog([], {})
    qtbot.addWidget(dialog)

    dialog._copy_btn.click()

    assert QApplication.clipboard().text() == "AlienComic"


def test_dialog_create_rule_uses_the_most_populated_selection_as_name(
    qtbot, monkeypatch
):
    _patch_thread(
        monkeypatch,
        [
            _result(
                keyword="Sketch",
                count=5,
                mentions=8,
                scopes=frozenset({"tags"}),
                match_key="sketch",
                variants=("Sketch", "sketch"),
            ),
            _result(
                keyword="Fanart",
                count=2,
                mentions=3,
                scopes=frozenset({"title"}),
                match_key="fanart",
                variants=("Fanart",),
            ),
        ],
    )
    dialog = cd.RecommendedKeywordsDialog([], {})
    qtbot.addWidget(dialog)
    model = dialog._table.model()
    selection = dialog._table.selectionModel()
    selection.clear()
    for row in (0, 1):
        selection.select(
            model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )
    captured = []
    dialog.create_rule_requested.connect(
        lambda folder, values, scopes: captured.append((folder, values, scopes))
    )

    dialog._create_rule_btn.click()

    assert captured == [
        (
            "Sketch",
            ("Sketch", "Fanart"),
            frozenset({"title", "tags"}),
        )
    ]
    dialog.close()


def test_dialog_multiple_selection_feeds_search_skip_and_copy(qtbot, monkeypatch):
    _patch_thread(
        monkeypatch,
        [
            _result(keyword="Sketch", count=5, variants=("Sketch",)),
            _result(keyword="Fanart", count=2, variants=("Fanart",)),
        ],
    )
    dialog = cd.RecommendedKeywordsDialog([], {})
    qtbot.addWidget(dialog)
    model = dialog._table.model()
    selection = dialog._table.selectionModel()
    selection.clear()
    for row in (0, 1):
        selection.select(
            model.index(row, 0),
            QItemSelectionModel.SelectionFlag.Select
            | QItemSelectionModel.SelectionFlag.Rows,
        )
    skipped = []
    dialog.skip_keywords_requested.connect(
        lambda variants, scopes: skipped.append((variants, scopes))
    )

    dialog._add_skip_btn.click()
    dialog._copy_btn.click()

    assert skipped == [(("Sketch", "Fanart"), frozenset({"tags"}))]
    assert QApplication.clipboard().text() == "Sketch\nFanart"
    dialog.close()


# ---------------------------------------------------------------------------
# Wiring back into the Creator tab
# ---------------------------------------------------------------------------


def test_tab_create_rule_adds_or_merges_a_sorting_rule(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)

    tab._create_rule_from_recommended("Sketch", ("Sketch", "sketch"), {"tags"})

    assert len(tab._sort_rules) == 1
    assert tab._sort_rules[0].folder == "Sketch"
    assert tab._sort_rules[0].values == ("Sketch", "sketch")
    assert tab._sort_rules[0].scopes == frozenset({"tags"})
    tab.close()


def test_tab_create_rule_keeps_an_open_sort_editor_in_sync(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    tab._open_sort_rules_dialog()
    dialog = tab._sort_rules_dialog
    dialog._add_rule()
    dialog._clear_rule_selection()

    tab._create_rule_from_recommended("Sketch", ("Sketch",), {"tags"})

    assert dialog.isVisible()
    assert [rule.folder for rule in dialog.rules()] == [
        "Cats",
        "New Folder",
        "Sketch",
    ]
    assert dialog._rule_list.currentRow() == 2
    assert [rule.folder for rule in tab._sort_rules] == [
        "Cats",
        "New Folder",
        "Sketch",
    ]
    tab._close_sort_rules_dialog()


def test_create_rule_button_tracks_the_selected_sorting_rule(
    qtbot, tmp_path, monkeypatch
):
    tab = _make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    _patch_thread(monkeypatch, [])

    tab._open_sort_rules_dialog()
    sort_dialog = tab._sort_rules_dialog
    tab._open_recommended_keywords_dialog()
    recommended = tab._recommended_keywords_dialog

    assert recommended._create_rule_btn.text() == translate(
        "recommended_keywords_add_to_rule"
    )

    sort_dialog._clear_rule_selection()
    assert recommended._create_rule_btn.text() == translate(
        "recommended_keywords_create_rule"
    )

    sort_dialog._rule_list.setCurrentRow(0)
    assert recommended._create_rule_btn.text() == translate(
        "recommended_keywords_add_to_rule"
    )

    tab._close_sort_rules_dialog()
    assert recommended._create_rule_btn.text() == translate(
        "recommended_keywords_create_rule"
    )
    tab._close_recommended_keywords_dialog()


def test_open_sort_editor_after_recommendations_refreshes_the_rule_action(
    qtbot, tmp_path, monkeypatch
):
    tab = _make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    _patch_thread(monkeypatch, [])

    tab._open_recommended_keywords_dialog()
    recommended = tab._recommended_keywords_dialog
    assert recommended._create_rule_btn.text() == translate(
        "recommended_keywords_create_rule"
    )

    tab._open_sort_rules_dialog()

    assert recommended._create_rule_btn.text() == translate(
        "recommended_keywords_add_to_rule"
    )
    tab._close_recommended_keywords_dialog()
    tab._close_sort_rules_dialog()


def test_tab_add_to_selected_rule_merges_instead_of_creating(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab._sort_rules = [
        cd.SortRule("Cats", ("cat",)),
        cd.SortRule("Dogs", ("dog",)),
    ]
    tab._open_sort_rules_dialog()
    dialog = tab._sort_rules_dialog
    assert dialog.selected_rule_index() == 0

    tab._create_rule_from_recommended("Sketch", ("sketch",), {"title"})

    assert [rule.folder for rule in dialog.rules()] == ["Cats", "Dogs"]
    assert dialog.rules()[0].values == ("cat", "sketch")
    assert dialog.rules()[0].scopes == frozenset({"tags", "title"})
    assert dialog.rules()[1].values == ("dog",)
    assert dialog.selected_rule_index() == 0
    tab._close_sort_rules_dialog()


def test_tab_dialog_rows_follow_the_filtered_post_list(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab.all_detected_posts = [("All", ("1", None))]
    tab.filtered_posts = [("Visible", "2", "thumb", False)]
    tab._filtered_rows_ready = True

    assert tab._dialog_post_rows() == [("Visible", ("2", "thumb"))]

    tab._filtered_rows_ready = False
    assert tab._dialog_post_rows() == [("All", ("1", None))]


def test_tab_search_applies_the_text_and_scopes(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    calls = []
    tab.filter_items = lambda: calls.append("filter")

    tab._apply_recommended_search("AlienComic", {"tags"})

    assert tab.creator_search_input.text() == "AlienComic"
    assert tab.search_scope_checkboxes["tags"].isChecked()
    assert not tab.search_scope_checkboxes["title"].isChecked()
    assert calls == ["filter"]


def test_tab_search_refilters_when_the_text_is_already_there(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    calls = []
    tab.filter_items = lambda: calls.append("filter")
    tab.creator_search_input.blockSignals(True)
    tab.creator_search_input.setText("AlienComic")
    tab.creator_search_input.blockSignals(False)

    tab._apply_recommended_search("AlienComic", {"title"})

    assert tab.search_scope_checkboxes["title"].isChecked()
    assert calls == ["filter"]


def test_tab_adds_a_quoted_skip_keyword_and_enables_its_scope(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab.skip_keywords_edit.blockSignals(True)
    tab.skip_keywords_edit.setText("existing")
    tab.skip_keywords_edit.blockSignals(False)
    calls = []
    tab.filter_items = lambda: calls.append("filter")

    tab._add_recommended_skip_keywords(("Hello, world", "café"), {"tags"})

    assert '"Hello, world"' in tab.skip_keywords_edit.text()
    assert cd.parse_keyword_values(tab.skip_keywords_edit.text()) == [
        "existing",
        "Hello, world",
        "café",
    ]
    assert tab.skip_scope_checkboxes["tags"].isChecked()
    assert calls == ["filter"]


def test_tab_does_not_add_the_same_skip_keyword_twice(qtbot, tmp_path):
    tab = _make_tab(qtbot, tmp_path)
    tab.filter_items = lambda: None

    tab._add_recommended_skip_keywords(("Hello, world",), {"tags"})
    text = tab.skip_keywords_edit.text()
    tab._add_recommended_skip_keywords(("Hello, world",), {"tags"})

    assert tab.skip_keywords_edit.text() == text


def test_button_opens_the_window_with_the_loaded_posts(qtbot, tmp_path, monkeypatch):
    tab = _make_tab(qtbot, tmp_path)
    _seed_posts(tab)
    _patch_thread(monkeypatch, [_result()])

    tab.creator_recommended_btn.click()

    dialog = tab._recommended_keywords_dialog
    assert dialog is not None
    assert dialog.isVisible()
    assert dialog._post_rows == [("1", "Alien Comic"), ("2", "Alien Comic")]
    assert dialog._table.rowCount() == 1

    tab._close_recommended_keywords_dialog()
    assert not dialog.isVisible()
    assert tab._recommended_keywords_dialog is None


def test_button_passes_the_active_skip_filters_to_the_window(
    qtbot, tmp_path, monkeypatch
):
    tab = _make_tab(qtbot, tmp_path)
    _seed_posts(tab)
    _patch_thread(monkeypatch, [_result()])
    for widget, value in (
        (tab.skip_keywords_edit, "AlienComic"),
        (tab.file_skip_keywords_edit, "BlackCat"),
    ):
        widget.blockSignals(True)
        widget.setText(value)
        widget.blockSignals(False)
    for scope, checked in (("title", False), ("tags", True)):
        checkbox = tab.skip_scope_checkboxes[scope]
        checkbox.blockSignals(True)
        checkbox.setChecked(checked)
        checkbox.blockSignals(False)

    tab.creator_recommended_btn.click()

    dialog = tab._recommended_keywords_dialog
    assert dialog is not None
    assert dialog._filters.skip_keywords == ("AlienComic",)
    assert dialog._filters.skip_scopes == frozenset({"tags"})
    assert dialog._file_skip_keywords == ("BlackCat",)
    tab._close_recommended_keywords_dialog()


def test_file_skip_edits_refresh_the_open_recommendation_window(
    qtbot, tmp_path, monkeypatch
):
    tab = _make_tab(qtbot, tmp_path)
    _seed_posts(tab)
    _patch_thread(monkeypatch, [_result()])
    tab.creator_recommended_btn.click()
    dialog = tab._recommended_keywords_dialog

    tab.file_skip_keywords_edit.setText("BlackCat")

    assert dialog._file_skip_keywords == ("BlackCat",)
    tab._close_recommended_keywords_dialog()


def test_button_opens_even_with_no_posts_loaded(qtbot, tmp_path, monkeypatch):
    tab = _make_tab(qtbot, tmp_path)
    _patch_thread(monkeypatch, [])

    tab.creator_recommended_btn.click()

    dialog = tab._recommended_keywords_dialog
    assert dialog is not None
    assert dialog.isVisible()
    assert dialog._post_rows == []
    tab._close_recommended_keywords_dialog()


def test_recommended_button_is_usable_while_busy(qtbot, tmp_path, monkeypatch):
    tab = _make_tab(qtbot, tmp_path)
    _patch_thread(monkeypatch, [])

    tab.set_fetching_ui_state(True)
    assert tab.creator_recommended_btn.isEnabled()
    tab.creator_recommended_btn.click()
    assert tab._recommended_keywords_dialog is not None
    tab._close_recommended_keywords_dialog()

    tab.set_downloading_ui_state(True)
    assert tab.creator_recommended_btn.isEnabled()


def test_dialog_options_round_trip_and_report_changes(qtbot, monkeypatch):
    _patch_thread(monkeypatch, [])
    options = {
        "scopes": ["tags"],
        "min_count": 5,
        "max_words": 1,
        "ignore_common_words": False,
        "ignore_accents": True,
        "ignore_text_posts": False,
        "ignore_filtered_keywords": False,
    }
    dialog = cd.RecommendedKeywordsDialog([], {}, options=options)
    qtbot.addWidget(dialog)

    assert dialog.options() == options
    assert dialog._scope_checks["tags"].isChecked()
    assert dialog._ignore_common.isChecked() is False
    assert dialog._ignore_accents.isChecked() is True
    assert dialog._ignore_text_posts.isChecked() is False
    assert dialog._ignore_filtered_keywords.isChecked() is False

    reported = []
    dialog.options_changed.connect(reported.append)
    dialog._scope_checks["title"].setChecked(True)

    assert reported[-1]["scopes"] == ["tags", "title"]


def test_window_closes_when_the_page_is_refetched(qtbot, tmp_path, monkeypatch):
    tab = _make_tab(qtbot, tmp_path)
    _seed_posts(tab)
    _patch_thread(monkeypatch, [_result()])
    tab.creator_recommended_btn.click()
    dialog = tab._recommended_keywords_dialog
    assert dialog is not None and dialog.isVisible()

    tab.set_fetching_ui_state(True)

    assert not dialog.isVisible()


def test_recommended_translation_keys_exist():
    for key in (
        "recommended_keywords",
        "recommended_keywords_tooltip",
        "recommended_keywords_title",
        "recommended_keywords_intro",
        "recommended_keywords_scopes",
        "recommended_keywords_min_posts",
        "recommended_keywords_posts_suffix",
        "recommended_keywords_phrase_length",
        "recommended_keywords_ignore_common",
        "recommended_keywords_ignore_accents",
        "recommended_keywords_ignore_filters",
        "recommended_keywords_ignore_filters_tooltip",
        "recommended_keywords_ignore_text_posts",
        "recommended_keywords_ignored_filters",
        "recommended_keywords_ignored_text_posts",
        "recommended_keywords_refresh",
        "recommended_keywords_column_keyword",
        "recommended_keywords_column_posts",
        "recommended_keywords_column_mentions",
        "recommended_keywords_search",
        "recommended_keywords_add_skip",
        "recommended_keywords_add_to_rule",
        "recommended_keywords_add_to_rule_tooltip",
        "recommended_keywords_copy",
        "recommended_keywords_create_rule",
        "recommended_keywords_create_rule_tooltip",
        "recommended_keywords_rule_added",
        "recommended_keywords_rule_updated",
        "recommended_keywords_empty",
        "recommended_keywords_empty_filtered",
        "recommended_keywords_scanning",
        "recommended_keywords_summary",
        "recommended_keywords_added",
        "recommended_keywords_no_posts",
        "recommended_keywords_only_text_posts",
        "recommended_keywords_help_title",
        "recommended_keywords_help_text",
    ):
        assert translate(key) != key

    assert translate("sort_keyword_rules") == "Keyword Folder Sorting"
