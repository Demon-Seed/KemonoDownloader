"""Tests for keyword auto-sorting (rules, routing, paths, links, parsers)."""

import os
from types import SimpleNamespace

from tests.factories import make_tab_parent

from kemonodownloader import creator_downloader as cd
from kemonodownloader.kd_language import translate


class DummySettingsTab:
    def __init__(self, template=None, strategy=None, shared=None):
        self._template = template or "{file_number}_{post_id}_{orig_name}"
        self._strategy = strategy or "per_post"
        self._shared = shared or "{post_id}_{file_number}_{orig_name}"

    def get_creator_filename_template(self):
        return self._template

    def get_creator_filename_template_shared(self):
        return self._shared

    def get_creator_folder_strategy(self):
        return self._strategy


class DummySettings:
    def __init__(self, settings_tab):
        self.settings_tab = settings_tab


FILE_URL = "https://example.test/files/art.jpg?f=art.jpg"


def make_thread(
    tmp_path,
    post_sort_folders=None,
    link_sort_matches=False,
    strategy="per_post",
    skip_folder=False,
    threshold=1,
    post_file_count=2,
    link_all_count=0,
):
    files = [FILE_URL]
    post_files = {"1": [FILE_URL]}
    for index in range(link_all_count):
        extra = f"https://example.test/files/art{index}.jpg?f=art{index}.jpg"
        files.append(extra)
        post_files["1"].append(extra)
    thread = cd.CreatorDownloadThread(
        "patreon",
        "123",
        str(tmp_path),
        ["1"],
        files,
        {url: "1" for url in files},
        None,
        str(tmp_path / "other"),
        {},
        DummySettings(DummySettingsTab(strategy=strategy)),
        max_concurrent=1,
        skip_folder_enabled=skip_folder,
        skip_folder_threshold=threshold,
        post_file_counts={"1": post_file_count},
        post_sort_folders=post_sort_folders,
        link_sort_matches=link_sort_matches,
    )
    thread.creator_name = "Creator"
    return thread


def creator_folder(tmp_path):
    return os.path.join(str(tmp_path), "123_Creator")


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def test_tag_rule_matches_whole_tags_case_insensitively():
    facts = {"tag_list": ["Cat", "Neko"]}
    assert cd.sort_rule_matches("P", facts, cd.SortRule("Cats", ("cat",)))
    assert cd.sort_rule_matches("P", facts, cd.SortRule("Cats", ("NEKO",)))
    assert not cd.sort_rule_matches(
        "P", facts, cd.SortRule("Cats", ("category",))
    )


def test_wildcards_are_shared_by_every_scope():
    facts = {
        "tag_list": ["BlackCat"],
        "filenames_list": ["blackcat_01.png"],
        "description": "a black cat pack",
    }
    assert cd.sort_rule_matches(
        "BlackCat", facts, cd.SortRule("Tags", ("black*",))
    )
    assert cd.sort_rule_matches(
        "BlackCat",
        facts,
        cd.SortRule("Title", ("black*",), scopes=frozenset({"title"})),
    )
    assert not cd.sort_rule_matches(
        "BlackCat",
        facts,
        cd.SortRule("Title", ("cat",), scopes=frozenset({"title"})),
    )
    assert cd.sort_rule_matches(
        "BlackCat",
        facts,
        cd.SortRule("Title", ("*cat*",), scopes=frozenset({"title"})),
    )
    assert cd.sort_rule_matches(
        "BlackCat",
        facts,
        cd.SortRule("Files", ("blackcat*",), scopes=frozenset({"filenames"})),
    )
    assert cd.sort_rule_matches(
        "BlackCat",
        facts,
        cd.SortRule("Desc", ("*cat*",), scopes=frozenset({"description"})),
    )


def test_pawchive_shaped_tags_and_wildcards():
    facts = {
        "tag_list": ["Ado", "Comic", "BlackCat", "3D art", "Seeking"]
    }
    for pattern in ("ado", "COMIC", "blackcat", "3D art", "seeking"):
        assert cd.sort_rule_matches("P", facts, cd.SortRule("F", (pattern,)))
    assert cd.sort_rule_matches("P", facts, cd.SortRule("F", ("3D*",)))
    assert cd.sort_rule_matches("P", facts, cd.SortRule("F", ("*cat",)))
    assert not cd.sort_rule_matches("P", facts, cd.SortRule("F", ("cat",)))
    assert cd.sort_rule_matches(
        "P", {"tag_list": ["cat"]}, cd.SortRule("F", ("c?t",))
    )
    assert not cd.sort_rule_matches(
        "P", {"tag_list": ["cart"]}, cd.SortRule("F", ("c?t",))
    )


def test_tag_rule_treats_brackets_as_literal():
    facts = {"tag_list": ["a[b]"]}
    assert cd.sort_rule_matches("P", facts, cd.SortRule("Brackets", ("a[b]",)))
    assert not cd.sort_rule_matches(
        "P", {"tag_list": ["a"]}, cd.SortRule("Brackets", ("[ab]",))
    )


def test_match_all_needs_every_value_and_scopes_combine():
    facts = {"tag_list": ["BlackCat"], "description": "3D art"}
    rule = cd.SortRule(
        "F",
        ("blackcat", "3D*"),
        match_all=True,
        scopes=frozenset({"tags", "description"}),
    )
    assert cd.sort_rule_matches("P", facts, rule)
    one_scope = cd.SortRule(
        "F",
        ("blackcat", "nothing"),
        match_all=True,
        scopes=frozenset({"tags", "description"}),
    )
    assert not cd.sort_rule_matches("P", facts, one_scope)


def test_wildcard_only_values_never_match():
    facts = {"tag_list": ["cat"]}
    for value in ("*", "?", "**"):
        assert not cd.sort_rule_matches(
            "P", facts, cd.SortRule("F", (value,))
        )


def test_title_rule_works_without_facts():
    rule = cd.SortRule("Cats", ("cat",), scopes=frozenset({"title"}))
    assert cd.sort_rule_matches("A cat picture", None, rule) is True
    tag_rule = cd.SortRule("Cats", ("cat",))
    assert cd.sort_rule_matches("A cat picture", None, tag_rule) is False


def test_disabled_and_empty_rules_never_match():
    facts = {"tag_list": ["cat"]}
    assert not cd.sort_rule_matches(
        "P", facts, cd.SortRule("Cats", ("cat",), enabled=False)
    )
    assert not cd.sort_rule_matches("P", facts, cd.SortRule("Cats", ()))


def test_sort_matching_does_not_use_the_plain_matcher(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("keyword settings leaked into sorting")

    monkeypatch.setattr(cd, "_keyword_matches_text", explode)
    facts = {"tag_list": ["Cat"], "description": "a Cat picture"}
    assert cd.sort_rule_matches(
        "A Cat picture", facts, cd.SortRule("Cats", ("cat",))
    )


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_post_tags_handles_pawchive_arrays():
    assert cd.parse_post_tags("{Ado,Comic}") == ["Ado", "Comic"]
    assert cd.parse_post_tags('{3D,"3D art",BlackCat}') == [
        "3D",
        "3D art",
        "BlackCat",
    ]
    assert cd.parse_post_tags('{"Hello, world",Cat}') == [
        "Hello, world",
        "Cat",
    ]
    assert cd.parse_post_tags('{"He said \\"hi\\"",Cat}') == [
        'He said "hi"',
        "Cat",
    ]
    assert cd.parse_post_tags("") == []
    assert cd.parse_post_tags("{}") == []
    assert cd.parse_post_tags("Ado,Comic") == ["Ado", "Comic"]
    assert cd.parse_post_tags("{'Ado','Comic'}") == ["Ado", "Comic"]


def test_parse_keyword_values_supports_quotes_and_escapes():
    assert cd.parse_keyword_values('Cat, "Hello, world", 3D art') == [
        "Cat",
        "Hello, world",
        "3D art",
    ]
    assert cd.parse_keyword_values('"He said \\"hi\\""') == ['He said "hi"']
    assert cd.parse_keyword_values("") == []
    assert cd.wildcard_value_is_unusable("*")
    assert cd.wildcard_value_is_unusable(" ?* ")
    assert not cd.wildcard_value_is_unusable("3D*")


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_resolve_routes_by_rule_order_and_keeps_every_match():
    posts = [
        ("One", ("1", "t")),
        ("Two", ("2", "t")),
        ("Three", ("3", "t")),
        ("Four", ("4", "t")),
    ]
    facts = {
        "1": {"tag_list": ["cat", "wallpaper"]},
        "2": {"tag_list": ["cat"]},
        "4": {"tag_list": ["dog"]},
    }
    rules = [
        cd.SortRule("Cats", ("cat",)),
        cd.SortRule("Walls", ("wallpaper",)),
    ]

    routing = cd.resolve_sort_folders(posts, facts, rules)

    assert routing.folders["1"] == ("Cats", "Walls")
    assert routing.folders["2"] == ("Cats",)
    assert "3" not in routing.folders, "no facts means no tag routing"
    assert "4" not in routing.folders
    assert routing.counts == {"Cats": 2}
    assert routing.multi_match == 1
    assert routing.missing_facts == 1
    assert routing.unsorted == 1


def test_resolve_routes_title_only_post_without_facts():
    posts = [("A cat picture", ("1", "t"))]
    rules = [cd.SortRule("Cats", ("cat",), scopes=frozenset({"title"}))]
    routing = cd.resolve_sort_folders(posts, {}, rules)
    assert routing.folders == {"1": ("Cats",)}
    assert routing.missing_facts == 0


def test_resolve_routes_unsorted_posts_to_the_configured_folder():
    posts = [("One", ("1", "t")), ("Two", ("2", "t"))]
    facts = {"1": {"tag_list": ["cat"]}, "2": {"tag_list": ["dog"]}}
    rules = [cd.SortRule("Cats", ("cat",))]

    routing = cd.resolve_sort_folders(
        posts, facts, rules, unsorted_folder="Unsorted"
    )

    assert routing.folders == {"1": ("Cats",), "2": ("Unsorted",)}
    assert routing.counts == {"Cats": 1, "Unsorted": 1}
    assert routing.unsorted == 1


def test_resolve_skips_disabled_rules():
    posts = [("One", ("1", "t"))]
    facts = {"1": {"tag_list": ["cat"]}}
    rules = [cd.SortRule("Cats", ("cat",), enabled=False)]
    routing = cd.resolve_sort_folders(posts, facts, rules)
    assert routing.folders == {}
    assert routing.unsorted == 1


def test_resolve_does_not_repeat_the_same_folder():
    posts = [("One", ("1", "t"))]
    facts = {"1": {"tag_list": ["cat"]}}
    rules = [
        cd.SortRule("Cats", ("cat",)),
        cd.SortRule("cats", ("cat",)),
    ]
    routing = cd.resolve_sort_folders(posts, facts, rules)
    assert routing.folders == {"1": ("Cats",)}
    assert routing.multi_match == 0


def test_normalize_sort_folder_rejects_unsafe_names():
    assert cd.normalize_sort_folder("Cats") == ("Cats", "")
    assert cd.normalize_sort_folder("  Cat Art  ")[0] == "Cat_Art"
    for bad in (
        "",
        ".",
        "..",
        "Art/Cats",
        "Art\\Cats",
        "C:/Cats",
        "../Cats",
        "CON",
    ):
        folder, problem = cd.normalize_sort_folder(bad)
        assert folder == ""
        assert problem


def test_rule_dict_round_trip_has_no_kind():
    rule = cd.SortRule(
        "Cats",
        ("cat", "neko"),
        match_all=True,
        scopes=frozenset({"title", "tags"}),
        enabled=False,
    )
    data = cd.sort_rule_to_dict(rule)
    assert "kind" not in data
    restored = cd.sort_rule_from_dict(data)
    assert restored == rule
    assert cd.sort_rules_from_config({"rules": [data]}) == [rule]


def test_legacy_kind_migrates_to_scopes():
    tag = cd.sort_rule_from_dict(
        {
            "folder": "Cats",
            "kind": "tag",
            "values": ["cat"],
            "scopes": ["title"],
        }
    )
    assert tag.scopes == frozenset({"tags"})
    keyword = cd.sort_rule_from_dict(
        {"folder": "Walls", "kind": "keyword", "values": ["wall"]}
    )
    assert keyword.scopes == frozenset({"title", "tags"})
    scoped = cd.sort_rule_from_dict(
        {
            "folder": "Desc",
            "kind": "keyword",
            "values": ["wall"],
            "scopes": ["description"],
        }
    )
    assert scoped.scopes == frozenset({"description"})
    new = cd.sort_rule_from_dict({"folder": "New", "values": ["cat"]})
    assert new.scopes == frozenset({"tags"})
    parsed = cd.sort_rule_from_dict(
        {"folder": "F", "values": '"Hello, world",Cat'}
    )
    assert parsed.values == ("Hello, world", "Cat")
    dropped = cd.sort_rule_from_dict(
        {"folder": "F", "values": ["*", "cat"]}
    )
    assert dropped.values == ("cat",)



# ---------------------------------------------------------------------------
# Folder resolution in the download thread
# ---------------------------------------------------------------------------


def test_sorted_post_gets_a_keyword_folder_under_the_creator_folder(tmp_path):
    thread = make_thread(tmp_path, post_sort_folders={"1": ("Cats",)})

    target, _filename = thread.generate_filename_and_folder(
        FILE_URL, str(tmp_path), 0, 1, "1", "Post", 1
    )

    assert target.startswith(os.path.join(creator_folder(tmp_path), "Cats"))
    assert os.path.dirname(target) != creator_folder(tmp_path)
    assert thread._creator_folder == creator_folder(tmp_path)


def test_skip_folder_keeps_the_file_in_the_keyword_folder(tmp_path):
    thread = make_thread(
        tmp_path,
        post_sort_folders={"1": ("Cats",)},
        skip_folder=True,
        threshold=2,
        post_file_count=1,
    )

    target, _filename = thread.generate_filename_and_folder(
        FILE_URL, str(tmp_path), 0, 1, "1", "Post", 1
    )

    assert target == os.path.join(creator_folder(tmp_path), "Cats")


def test_single_folder_strategy_uses_the_keyword_folder(tmp_path):
    thread = make_thread(
        tmp_path, post_sort_folders={"1": ("Cats",)}, strategy="single_folder"
    )
    target, _ = thread.generate_filename_and_folder(
        FILE_URL, str(tmp_path), 0, 1, "1", "Post", 1
    )
    assert target == os.path.join(creator_folder(tmp_path), "Cats")


def test_by_file_type_strategy_nests_under_the_keyword_folder(tmp_path):
    thread = make_thread(
        tmp_path, post_sort_folders={"1": ("Cats",)}, strategy="by_file_type"
    )
    target, _ = thread.generate_filename_and_folder(
        FILE_URL, str(tmp_path), 0, 1, "1", "Post", 1
    )
    assert target == os.path.join(creator_folder(tmp_path), "Cats", "jpg")


def test_unmatched_post_stays_in_the_creator_folder(tmp_path):
    thread = make_thread(tmp_path, post_sort_folders={"1": ("Cats",)})
    target, _ = thread.generate_filename_and_folder(
        FILE_URL, str(tmp_path), 0, 1, "2", "Other", 1
    )
    assert os.path.dirname(target) != os.path.join(
        creator_folder(tmp_path), "Cats"
    )
    assert target.startswith(creator_folder(tmp_path))


def test_description_folder_follows_the_keyword_folder(tmp_path):
    thread = make_thread(
        tmp_path, post_sort_folders={"1": ("Cats",)}, strategy="per_post"
    )
    desc_folder = thread.get_desc_folder_for_post(
        creator_folder(tmp_path), "1", "Post"
    )
    assert desc_folder.startswith(os.path.join(creator_folder(tmp_path), "Cats"))
    assert thread.get_desc_folder_for_post(
        creator_folder(tmp_path), "2", "Post"
    ).startswith(creator_folder(tmp_path))


# ---------------------------------------------------------------------------
# Hardlink mode
# ---------------------------------------------------------------------------


def make_primary(tmp_path, folder="Cats", name="art.jpg"):
    primary = os.path.join(creator_folder(tmp_path), folder, name)
    os.makedirs(os.path.dirname(primary), exist_ok=True)
    with open(primary, "wb") as handle:
        handle.write(b"image-bytes")
    return primary


def test_link_mode_hardlinks_into_every_extra_folder(tmp_path):
    thread = make_thread(
        tmp_path,
        post_sort_folders={"1": ("Cats", "Walls")},
        link_sort_matches=True,
    )
    primary = make_primary(tmp_path)

    created = thread._link_extra_sort_copies(
        "1", primary, "art.jpg", str(tmp_path)
    )

    linked = os.path.join(creator_folder(tmp_path), "Walls", "art.jpg")
    assert created == 1
    assert os.path.exists(linked)
    assert os.path.samefile(primary, linked)
    assert thread.linked_sort_files == 1


def test_link_mode_off_creates_nothing(tmp_path):
    thread = make_thread(
        tmp_path,
        post_sort_folders={"1": ("Cats", "Walls")},
        link_sort_matches=False,
    )
    primary = make_primary(tmp_path)

    assert thread._link_extra_sort_copies("1", primary, "art.jpg") == 0
    assert not os.path.exists(os.path.join(creator_folder(tmp_path), "Walls"))


def test_link_mode_is_idempotent(tmp_path):
    thread = make_thread(
        tmp_path,
        post_sort_folders={"1": ("Cats", "Walls")},
        link_sort_matches=True,
    )
    primary = make_primary(tmp_path)
    thread._link_extra_sort_copies("1", primary, "art.jpg", str(tmp_path))

    assert (
        thread._link_extra_sort_copies(
            "1", primary, "art.jpg", str(tmp_path)
        )
        == 0
    )
    assert os.listdir(os.path.join(creator_folder(tmp_path), "Walls")) == [
        "art.jpg"
    ]


def test_a_failed_link_is_a_warning_not_a_failure(tmp_path, monkeypatch):
    thread = make_thread(
        tmp_path,
        post_sort_folders={"1": ("Cats", "Walls")},
        link_sort_matches=True,
    )
    primary = make_primary(tmp_path)

    def refuse(*_args, **_kwargs):
        raise OSError("hardlinks not supported")

    monkeypatch.setattr(cd.os, "link", refuse)

    assert thread._link_extra_sort_copies("1", primary, "art.jpg") == 0
    assert thread.failed_sort_links == 1



# ---------------------------------------------------------------------------
# Tab wiring
# ---------------------------------------------------------------------------


def make_tab(qtbot, tmp_path):
    tab = cd.CreatorDownloaderTab(make_tab_parent(tmp_path, window=True))
    qtbot.addWidget(tab)
    tab.current_creator_url = "https://kemono.cr/patreon/user/123"
    return tab


def test_resolve_run_sort_folders_covers_only_ticked_posts_with_files(
    qtbot, tmp_path
):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    tab.creator_sort_enabled_check.setChecked(True)
    tab.all_detected_posts = [
        ("One (2024-01-01)", ("1", "thumb")),
        ("Two (2024-01-02)", ("2", "thumb")),
        ("Three (2024-01-03)", ("3", "thumb")),
    ]
    tab.post_search_index = {
        "1": {"tag_list": ["cat"]},
        "2": {"tag_list": ["cat"]},
        "3": {"tag_list": ["cat"]},
    }
    tab.posts_to_download = ["1", "2", "3"]

    folders, link_all = tab._resolve_run_sort_folders({"1", "3"})

    assert folders == {"1": ("Cats",), "3": ("Cats",)}
    assert link_all is False


def test_download_unsorted_filters_and_routes_unmatched_posts(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    tab.creator_sort_enabled_check.setChecked(True)
    tab.all_detected_posts = [("One", ("1", "thumb")), ("Two", ("2", "thumb"))]
    tab.post_search_index = {
        "1": {"tag_list": ["cat"]},
        "2": {"tag_list": ["dog"]},
    }
    tab.posts_to_download = ["1", "2"]

    tab._sort_download_unsorted = False
    assert tab._post_ids_to_download() == ["1"]

    tab._sort_download_unsorted = True
    tab._sort_unsorted_folder = "Unsorted"
    folders, _link_all = tab._resolve_run_sort_folders()

    assert folders == {"1": ("Cats",), "2": ("Unsorted",)}


def test_sorting_disabled_resolves_nothing(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    tab.creator_sort_enabled_check.setChecked(False)
    tab.all_detected_posts = [("One", ("1", "thumb"))]
    tab.post_search_index = {"1": {"tag_list": ["cat"]}}
    tab.posts_to_download = ["1"]

    assert tab._resolve_run_sort_folders({"1"}) == ({}, False)


def test_start_download_thread_passes_and_snapshots_the_routing(
    qtbot, tmp_path, monkeypatch
):
    captured = {}

    class FakeDownloadThread:
        def __init__(self, *args, **kwargs):
            captured["kwargs"] = kwargs
            for name in (
                "file_progress",
                "file_completed",
                "post_completed",
                "creator_folder_ready",
                "log",
                "finished",
            ):
                setattr(self, name, SimpleNamespace(connect=lambda *a, **k: None))

        def start(self):
            pass

    monkeypatch.setattr(cd, "CreatorDownloadThread", FakeDownloadThread)
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    tab.creator_sort_enabled_check.setChecked(True)
    tab.all_detected_posts = [
        ("One", ("1", "thumb")),
        ("Two", ("2", "thumb")),
    ]
    tab.post_search_index = {
        "1": {"tag_list": ["cat"]},
        "2": {"tag_list": ["cat"]},
    }
    tab.posts_to_download = ["1", "2"]
    tab.total_files_to_download = 1

    tab._start_download_thread(
        ["https://x/file.jpg"], {"https://x/file.jpg": "1"}
    )

    assert captured["kwargs"]["post_sort_folders"] == {"1": ("Cats",)}
    assert captured["kwargs"]["link_sort_matches"] is False
    assert tab._last_run_post_sort_folders == {"1": ("Cats",)}

    # A retry passes its snapshot; `{}` means "no routing", not "re-resolve".
    tab._sort_rules = [cd.SortRule("Dogs", ("dog",))]
    tab._start_download_thread(
        ["https://x/file.jpg"],
        {"https://x/file.jpg": "1"},
        post_sort_folders={},
    )
    assert captured["kwargs"]["post_sort_folders"] == {}


def test_open_sort_rules_dialog_is_modeless_and_reused(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]

    tab._open_sort_rules_dialog()
    first = tab._sort_rules_dialog
    assert first is not None
    assert first.isModal() is False

    tab._open_sort_rules_dialog()
    assert tab._sort_rules_dialog is first

    tab._close_sort_rules_dialog()
    first.reject()


def test_dialog_status_follows_the_page_switch(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    tab.creator_sort_enabled_check.setChecked(False)
    tab._open_sort_rules_dialog()
    dialog = tab._sort_rules_dialog

    assert translate("sort_status_off") in dialog._status_label.text()
    tab.creator_sort_enabled_check.setChecked(True)
    assert translate("sort_status_on") in dialog._status_label.text()


def test_applying_the_modeless_dialog_updates_the_tab(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = []
    tab._open_sort_rules_dialog()
    dialog = tab._sort_rules_dialog

    dialog._add_rule()
    dialog._folder_edit.setText("Dogs")
    dialog._values_edit.setText("dog")
    dialog._commit_editor()
    dialog._apply()

    assert [rule.folder for rule in tab._sort_rules] == ["Dogs"]
    assert tab._sort_rules[0].values == ("dog",)
    qtbot.wait(10)
    assert tab._sort_rules_dialog is None


def test_a_download_closes_the_rules_editor(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    tab._open_sort_rules_dialog()
    dialog = tab._sort_rules_dialog
    assert dialog.isVisible()

    tab.set_downloading_ui_state(True)

    assert dialog.isVisible() is False



# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------


def make_dialog(
    qtbot,
    rules=None,
    link_all=False,
    sorting_enabled=True,
    download_unsorted=True,
    unsorted_folder="",
):
    dialog = cd.SortRulesDialog(
        rules=rules if rules is not None else [cd.SortRule("Cats", ("cat",))],
        sorting_enabled=sorting_enabled,
        link_all=link_all,
        download_unsorted=download_unsorted,
        unsorted_folder=unsorted_folder,
        posts=[("One", ("1", "thumb")), ("Two", ("2", "thumb"))],
        post_search_index={
            "1": {"tag_list": ["cat"]},
            "2": {"tag_list": ["dog"]},
        },
        ticked_ids=["1", "2"],
    )
    qtbot.addWidget(dialog)
    return dialog


def test_dialog_is_modeless_and_shows_the_page_switch_status(qtbot):
    dialog = make_dialog(qtbot)
    assert dialog.isModal() is False
    assert translate("sort_status_on") in dialog._status_label.text()
    assert not hasattr(dialog, "_enabled_check")
    assert not hasattr(dialog, "_save_default_btn")

    off = make_dialog(qtbot, sorting_enabled=False)
    assert translate("sort_status_off") in off._status_label.text()


def test_dialog_previews_the_loaded_posts(qtbot):
    dialog = make_dialog(qtbot)

    preview = dialog._preview.toPlainText()
    assert translate("sort_preview_line", "Cats", 1) in preview
    assert translate("sort_preview_unsorted", 1) in preview


def test_dialog_add_creates_a_valid_unique_folder(qtbot):
    dialog = make_dialog(qtbot, rules=[])

    assert dialog._editor_group.isEnabled() is False
    assert dialog._no_rules_label.isHidden() is False

    dialog._add_rule()
    assert dialog.rules()[0].folder == "New Folder"
    assert cd.normalize_sort_folder(dialog.rules()[0].folder)[1] == ""
    assert dialog._editor_group.isEnabled() is True

    dialog._add_rule()
    assert [rule.folder for rule in dialog.rules()] == [
        "New Folder",
        "New Folder 2",
    ]
    assert "(no folder)" not in dialog._rule_list.item(0).text()


def test_dialog_preview_uses_lenient_tag_matching(qtbot):
    dialog = make_dialog(
        qtbot,
        rules=[cd.SortRule("F", ("ブルーアーカイブ",))],
    )
    dialog._posts = [("One", ("1", "thumb"))]
    dialog._ticked_ids = {"1"}
    dialog._post_search_index = {
        "1": {"tag_list": ["アイン(ブルーアーカイブ)"]}
    }

    dialog._update_preview()
    assert translate("sort_preview_unsorted", 1) in dialog._preview.toPlainText()

    dialog.set_lenient_tags(True)
    assert translate("sort_preview_line", "F", 1) in dialog._preview.toPlainText()


def test_dialog_download_unsorted_controls(qtbot):
    dialog = make_dialog(qtbot, download_unsorted=False)

    assert dialog.download_unsorted() is False
    assert dialog._unsorted_button.text() == "Set Unsorted"

    dialog._download_unsorted_check.setChecked(True)
    assert dialog.download_unsorted() is True


def test_dialog_unsorted_button_sets_clears_and_prevents_replacement(qtbot):
    dialog = make_dialog(
        qtbot,
        rules=[
            cd.SortRule("Cats", ("cat",)),
            cd.SortRule("Dogs", ("dog",)),
        ],
    )

    assert dialog._unsorted_button.text() == "Set Unsorted"
    dialog._unsorted_button.click()
    assert dialog.unsorted_folder() == "Cats"
    assert dialog._unsorted_button.text() == "Clear Unsorted"

    dialog._rule_list.setCurrentRow(1)
    assert dialog._unsorted_button.text() == "Clear Unsorted"
    assert dialog._unsorted_button.isEnabled() is True

    dialog._unsorted_button.click()
    assert dialog.unsorted_folder() == ""
    assert dialog._unsorted_button.text() == "Set Unsorted"

    dialog._unsorted_button.click()
    assert dialog.unsorted_folder() == "Dogs"
    assert dialog._unsorted_button.text() == "Clear Unsorted"


def test_dialog_adds_and_edits_a_rule(qtbot):
    dialog = make_dialog(qtbot)
    dialog._add_rule()

    dialog._folder_edit.setText("Dogs")
    dialog._values_edit.setText("dog")
    dialog._commit_editor()

    assert [rule.folder for rule in dialog.rules()] == ["Cats", "Dogs"]
    assert dialog.rules()[1].values == ("dog",)
    assert translate("sort_preview_line", "Dogs", 1) in dialog._preview.toPlainText()


def test_dialog_summary_shows_values_scopes_and_all(qtbot):
    dialog = make_dialog(
        qtbot,
        rules=[
            cd.SortRule(
                "Cats",
                ("cat", "neko"),
                match_all=True,
                scopes=frozenset({"title", "tags"}),
            )
        ],
    )
    text = dialog._rule_list.item(0).text()
    assert "1. Cats - cat, neko" in text
    assert "Title" in text and "Tags" in text
    assert translate("sort_rule_all") in text


def test_dialog_rejects_duplicates_and_wildcard_only_values(
    qtbot, monkeypatch
):
    warnings = []
    monkeypatch.setattr(
        cd.QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args)
    )
    dialog = make_dialog(
        qtbot,
        rules=[
            cd.SortRule("Cats", ("cat",)),
            cd.SortRule("cats", ("dog",)),
        ],
    )
    assert dialog._validate_and_normalise() is False
    assert warnings

    dialog._rules[1] = dialog._rules[1]._replace(folder="Dogs")
    assert dialog._validate_and_normalise() is True

    wildcard = make_dialog(qtbot, rules=[cd.SortRule("Cats", ("*",))])
    assert wildcard._validate_and_normalise() is False


def test_dialog_help_view_toggles(qtbot):
    dialog = make_dialog(qtbot)
    assert dialog._pages.currentWidget() is dialog._editor_page

    dialog._toggle_help()
    assert dialog._pages.currentWidget() is dialog._help_page
    assert "Keyword syntax" in dialog._help_browser.toHtml()

    dialog._toggle_help()
    assert dialog._pages.currentWidget() is dialog._editor_page


def test_dialog_apply_emits_applied(qtbot):
    dialog = make_dialog(qtbot)
    applied = []
    dialog.applied.connect(lambda: applied.append(True))
    dialog._apply()
    assert applied == [True]


def test_dialog_link_mode_preview_counts_extra_folders(qtbot):
    dialog = make_dialog(
        qtbot,
        rules=[
            cd.SortRule("Cats", ("cat",)),
            cd.SortRule("Walls", ("cat",)),
        ],
        link_all=True,
    )

    preview = dialog._preview.toPlainText()
    assert translate("sort_preview_multi", 1) in preview
    assert translate("sort_preview_extra_links", 1) in preview



# ---------------------------------------------------------------------------
# Skip boxes: wildcard terms and quoted values
# ---------------------------------------------------------------------------


def test_skip_wildcards_and_plain_terms_differ():
    assert cd._keyword_or_wildcard_match(["black*"], "BlackCat")
    assert cd._keyword_or_wildcard_match(["*cat*"], "BlackCat")
    assert not cd._keyword_or_wildcard_match(["cat"], "BlackCat")
    assert not cd._keyword_or_wildcard_match(["cat"], "blackcat")
    assert cd._keyword_or_wildcard_match(["*cat*"], "blackcat")
    assert cd._keyword_or_wildcard_match(["c?t"], "cat")


def test_tag_matching_behavior_switches_whole_tag_and_substring():
    facts = {"tag_list": ["アイン(ブルーアーカイブ)"]}
    rule = cd.SortRule("F", ("ブルーアーカイブ",))

    assert not cd.sort_rule_matches("P", facts, rule)
    assert cd.sort_rule_matches("P", facts, rule, lenient_tags=True)

    filters = cd.PostFilters(
        skip_keywords=("ブルーアーカイブ",),
        skip_scopes=frozenset({"tags"}),
    )
    assert cd.keyword_skip_reason("P", facts, filters) == ""
    assert (
        cd.keyword_skip_reason(
            "P", facts, filters._replace(lenient_tags=True)
        )
        == "ブルーアーカイブ"
    )


def test_skip_wildcards_match_whole_tags():
    facts = {"tag_list": ["BlackCat"], "description": "not a match"}
    filters = cd.PostFilters(
        skip_keywords=("black*",),
        skip_scopes=frozenset({"tags"}),
    )
    assert cd.keyword_skip_reason("P", facts, filters) == "black*"
    plain = cd.PostFilters(
        skip_keywords=("black",),
        skip_scopes=frozenset({"tags"}),
    )
    assert cd.keyword_skip_reason("P", facts, plain) == ""


def test_post_filter_inputs_support_quoted_values_and_warn_on_wildcards(
    qtbot, tmp_path
):
    tab = make_tab(qtbot, tmp_path)
    tab.skip_keywords_edit.setText('"Hello, world", cat, *')
    tab.file_skip_keywords_edit.setText("cover, ?")

    filters, warnings = tab._post_filters_from_widgets()

    assert filters.skip_keywords == ("Hello, world", "cat")
    assert tab._file_skip_keywords_from_widgets() == ["cover"]
    assert "wildcard_only_keyword_ignored" in warnings


# ---------------------------------------------------------------------------
# Labels, placeholders and help
# ---------------------------------------------------------------------------


def test_file_preparation_uses_the_shared_wildcard_matcher():
    thread = cd.FilePreparationThread.__new__(cd.FilePreparationThread)
    thread.file_skip_keywords = ["*cat*"]
    thread.lenient_punctuation = False

    assert thread._file_matches_skip_keyword("BlackCat.png") == "*cat*"
    assert thread._file_matches_skip_keyword("cover.png") == ""


def test_creator_tab_uses_the_keyword_labels(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab.update_ui_text()

    assert tab.creator_sort_enabled_check.text() == "Sort posts by keyword"
    assert tab.creator_sort_rules_btn.text() == "Keyword Rules"
    assert (
        tab.skip_keywords_edit.placeholderText()
        == "e.g. JP, EN (comma-separated)"
    )
    assert (
        tab.file_skip_keywords_edit.placeholderText()
        == "e.g. JP, EN (comma-separated)"
    )


def test_dialog_labels_and_placeholders(qtbot):
    dialog = make_dialog(qtbot)

    assert dialog.windowTitle() == "Sort posts by keyword"
    assert dialog._rules_group.title() == "Rules"
    assert dialog._unsorted_button.parent() is dialog._rules_group
    assert dialog._editor_group.title() == "Rule Settings"
    assert dialog._run_settings_group.title() == "Run Settings"
    assert dialog._preview.height() == 65
    assert dialog._match_combo.itemText(0) == "Any value"
    assert dialog._match_combo.itemText(1) == "All values"
    assert (
        dialog._values_edit.placeholderText()
        == "e.g. JP, EN (comma-separated)"
    )
    assert translate("sort_rules_label") == "Rules"


def test_keyword_help_text_has_a_dedicated_syntax_block():
    sort_help = translate("sort_help_text")
    assert "Keyword syntax" in sort_help
    assert "<table" in sort_help
    assert "Any value</b> (OR)" in sort_help
    assert "All values</b> (AND)" in sort_help
    assert "a post with tag cat OR title dog matches" in sort_help
    assert "アイン(ブルーアーカイブ)" in sort_help
    assert "Keyword Matching Rules" not in sort_help
    assert "The Punctuation Matching Behavior setting applies" in sort_help
    assert "content images are not checked" in sort_help
    assert "Cat, Neko" not in sort_help
    assert "skip order" not in sort_help.lower()

    syntax_help = translate("keyword_syntax_help_text")
    assert "Keyword syntax" in syntax_help
    assert "<table" in syntax_help
    assert "Punctuation Matching Behavior setting" in syntax_help
    assert "<a " not in syntax_help

    for key in ("skip_posts_keywords_help_text", "skip_files_keywords_help_text"):
        text = translate(key)
        # Contextual help points at the shared syntax topic instead of
        # repeating the whole table in every box.
        assert "Keyword syntax in Related" in text
        assert "Punctuation Matching Behavior setting" in text
        assert "<table" not in text
        assert "<a " not in text
        assert "Keyword Matching Rules" not in text
        assert "In sorting rules, Tags must match the whole tag" not in text
        assert "plain values still follow" not in text


def test_sorting_translation_keys_exist_and_old_ones_are_gone():
    for key in (
        "sort_title",
        "sort_apply",
        "sort_by_keyword",
        "sort_by_keyword_tooltip",
        "sort_keyword_rules",
        "sort_keyword_rules_tooltip",
        "sort_status_on",
        "sort_status_off",
        "sort_help_title",
        "sort_help_back",
        "sort_help_text",
        "sort_no_rules_hint",
        "sort_new_folder",
        "sort_link_all",
        "sort_link_all_tooltip",
        "sort_download_unsorted",
        "sort_download_unsorted_tooltip",
        "sort_set_unsorted",
        "sort_clear_unsorted",
        "sort_set_unsorted_tooltip",
        "sort_clear_unsorted_tooltip",
        "sort_unsorted_marker",
        "sort_rule_settings",
        "sort_run_settings",
        "sort_no_sorted_posts",
        "sort_rules_label",
        "sort_rule_add",
        "sort_rule_remove",
        "sort_rule_up",
        "sort_rule_down",
        "sort_rule_folder",
        "sort_rule_values",
        "sort_rule_any",
        "sort_rule_all",
        "sort_rule_no_values",
        "sort_scope_title",
        "sort_scope_tags",
        "sort_scope_filenames",
        "sort_scope_description",
        "sort_preview_label",
        "sort_preview_none",
        "sort_preview_line",
        "sort_preview_unsorted",
        "sort_preview_unsorted_skipped",
        "sort_preview_missing",
        "sort_preview_multi",
        "sort_preview_extra_links",
        "sort_invalid_folder",
        "sort_missing_values",
        "sort_wildcard_only_value",
        "sort_duplicate_folder",
        "sort_log_summary",
        "sort_log_none",
        "sort_log_no_rules",
        "sort_links_summary",
        "sort_link_failed",
        "wildcard_only_keyword_ignored",
    ):
        assert translate(key) and translate(key) != key
    for removed in (
        "sort_save_default",
        "sort_enable_label",
        "sort_help",
        "sort_rule_hint",
        "sort_rule_kind_tag",
        "sort_rule_kind_keyword",
        "sort_into_tag_folders",
        "sort_tag_folders",
    ):
        assert translate(removed) == removed



def test_dialog_title_rule_previews_post_without_facts(qtbot):
    dialog = make_dialog(qtbot)
    dialog._rules = [
        cd.SortRule("Cats", ("one",), scopes=frozenset({"title"}))
    ]
    dialog._post_search_index = {}
    dialog._refresh_list()
    dialog._load_editor()

    preview = dialog._preview.toPlainText()
    assert translate("sort_preview_line", "Cats", 1) in preview


def test_dialog_value_with_comma_round_trips(qtbot):
    dialog = make_dialog(qtbot, rules=[])
    dialog._add_rule()
    dialog._values_edit.setText('"Hello, world", cat')
    dialog._commit_editor()

    assert dialog.rules()[0].values == ("Hello, world", "cat")
    dialog._rule_list.setCurrentRow(0)
    dialog._load_editor()
    assert dialog._values_edit.text() == '"Hello, world", cat'


def test_creator_change_closes_the_rules_editor(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [cd.SortRule("Cats", ("cat",))]
    tab._open_sort_rules_dialog()
    dialog = tab._sort_rules_dialog

    tab._load_config_for_creator()

    assert dialog.isVisible() is False



def test_sort_literal_edges_follow_punctuation_rules():
    facts = {"filenames_list": ["1.5.png", "zip-01.png"]}
    dot_rule = cd.SortRule(
        "Dots", (".5",), scopes=frozenset({"filenames"})
    )
    wild_dot_rule = cd.SortRule(
        "WildDots", (".5*",), scopes=frozenset({"filenames"})
    )
    zip_rule = cd.SortRule(
        "Zips", ("zip-",), scopes=frozenset({"filenames"})
    )
    bracket_rule = cd.SortRule(
        "Brackets", ("[JP]",), scopes=frozenset({"title"})
    )

    assert not cd.sort_rule_matches("P", facts, dot_rule)
    assert cd.sort_rule_matches(
        "P", facts, dot_rule, lenient_punctuation=True
    )
    assert not cd.sort_rule_matches("P", facts, wild_dot_rule)
    assert cd.sort_rule_matches(
        "P", facts, wild_dot_rule, lenient_punctuation=True
    )
    assert not cd.sort_rule_matches("P", facts, zip_rule)
    assert cd.sort_rule_matches(
        "P", facts, zip_rule, lenient_punctuation=True
    )
    assert cd.sort_rule_matches("123[JP] art", {}, bracket_rule)
    assert cd.sort_rule_matches(
        "123[JP] art", {}, bracket_rule, lenient_punctuation=True
    )


def test_sort_star_edges_ignore_punctuation_rules():
    facts = {"filenames_list": ["1.5.png"]}
    rule = cd.SortRule(
        "Dots", ("*.5*",), scopes=frozenset({"filenames"})
    )

    assert cd.sort_rule_matches("P", facts, rule)
    assert cd.sort_rule_matches("P", facts, rule, lenient_punctuation=True)


def test_question_mark_edge_keeps_its_boundary():
    assert cd._wildcard_matches("cat?", "cats")
    assert not cd._wildcard_matches("cat?", "catsup")
    assert not cd._wildcard_matches(
        "cat?", "catsup", lenient_punctuation=True
    )


def test_run_sort_folders_uses_punctuation_setting(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [
        cd.SortRule("Dots", (".5",), scopes=frozenset({"filenames"}))
    ]
    tab.creator_sort_enabled_check.setChecked(True)
    tab.all_detected_posts = [("One", ("1", "thumb"))]
    tab.post_search_index = {"1": {"filenames_list": ["1.5.png"]}}
    tab.posts_to_download = ["1"]

    tab._parent.settings_tab.get_punctuation_matching_rules = lambda: "default"
    assert tab._resolve_run_sort_folders({"1"}) == ({}, False)

    tab._parent.settings_tab.get_punctuation_matching_rules = lambda: "lenient"
    assert tab._resolve_run_sort_folders({"1"}) == (
        {"1": ("Dots",)},
        False,
    )


def test_dialog_preview_updates_with_punctuation_setting(qtbot):
    dialog = cd.SortRulesDialog(
        rules=[
            cd.SortRule("Dots", (".5",), scopes=frozenset({"filenames"}))
        ],
        sorting_enabled=True,
        link_all=False,
        posts=[("One", ("1", "thumb"))],
        post_search_index={"1": {"filenames_list": ["1.5.png"]}},
        ticked_ids=["1"],
        lenient_punctuation=False,
    )
    qtbot.addWidget(dialog)

    assert translate("sort_preview_line", "Dots", 1) not in (
        dialog._preview.toPlainText()
    )
    dialog.set_lenient_punctuation(True)
    assert translate("sort_preview_line", "Dots", 1) in (
        dialog._preview.toPlainText()
    )


def test_settings_apply_refreshes_open_sort_dialog(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    tab._sort_rules = [
        cd.SortRule("Dots", (".5",), scopes=frozenset({"filenames"}))
    ]
    tab.all_detected_posts = [("One", ("1", "thumb"))]
    tab.post_search_index = {"1": {"filenames_list": ["1.5.png"]}}
    tab.posts_to_download = ["1"]
    tab._parent.settings_tab.get_punctuation_matching_rules = lambda: "default"
    tab._open_sort_rules_dialog()
    dialog = tab._sort_rules_dialog
    assert translate("sort_preview_line", "Dots", 1) not in (
        dialog._preview.toPlainText()
    )

    tab._parent.settings_tab.get_punctuation_matching_rules = lambda: "lenient"
    tab._on_matching_settings_applied()

    assert translate("sort_preview_line", "Dots", 1) in (
        dialog._preview.toPlainText()
    )

