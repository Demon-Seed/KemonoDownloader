"""Tests for the Creator tab's two saved config profiles.

"Save Config" stores the page's options and filters as the default for every
creator; "Save Creator Config" stores the same snapshot for one creator, and
that profile replaces the default while the creator is loaded. Post ticks are
deliberately not part of either profile.
"""

import copy
import json
import sqlite3
from types import SimpleNamespace

import pytest

from kemonodownloader import creator_downloader as cd
from kemonodownloader.creator_config import CreatorConfigStore

CREATOR_URL = "https://kemono.cr/patreon/user/42"
OTHER_CREATOR_URL = "https://kemono.cr/patreon/user/99"


class FakeSignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, callback):
        self._callbacks.append(callback)


def make_parent(tmp_path):
    class FakeTabs:
        def count(self):
            return 1

        def currentIndex(self):
            return 0

        def setTabEnabled(self, i, enabled):
            pass

    settings_tab = SimpleNamespace(
        settings_applied=SimpleNamespace(connect=lambda cb: None),
        language_changed=SimpleNamespace(connect=lambda cb: None),
        get_creator_posts_max_attempts=lambda: 1,
        get_post_data_max_retries=lambda: 1,
        get_file_download_max_retries=lambda: 1,
        get_api_request_max_retries=lambda: 1,
        get_simultaneous_downloads=lambda: 1,
    )
    return SimpleNamespace(
        cache_folder=str(tmp_path / "cache"),
        other_files_folder=str(tmp_path / "other"),
        download_folder=str(tmp_path / "download"),
        settings_tab=settings_tab,
        tabs=FakeTabs(),
        status_label=SimpleNamespace(setText=lambda s: None),
        animate_button=lambda *a, **k: None,
    )


def make_tab(qtbot, tmp_path, parent=None):
    tab = cd.CreatorDownloaderTab(parent or make_parent(tmp_path))
    qtbot.addWidget(tab)
    return tab


def tick(widget, value=True):
    """Set a checkbox without firing the live filter pass behind it."""
    widget.blockSignals(True)
    widget.setChecked(value)
    widget.blockSignals(False)


@pytest.fixture(autouse=True)
def no_blocking_dialogs(monkeypatch):
    """Record the save/refuse dialogs instead of showing them."""
    calls = []
    monkeypatch.setattr(
        cd.QMessageBox,
        "information",
        lambda *a, **k: calls.append(("information", a[1], a[2])),
    )
    monkeypatch.setattr(
        cd.QMessageBox, "warning", lambda *a, **k: calls.append(("warning", a[1], a[2]))
    )
    return calls


def test_store_round_trips_both_profiles(tmp_path):
    store = CreatorConfigStore(str(tmp_path))
    assert store.get_page_default() is None
    assert store.get_creator_config("patreon", "42") is None

    store.set_page_default({"options": {"main": True}})
    saved_default = store.get_page_default()
    assert saved_default is not None
    assert saved_default["options"] == {"main": True}

    store.set_creator_config("patreon", "42", {"options": {"main": False}})
    store.set_creator_config("patreon", "42", {"options": {"main": True}})
    saved_creator = store.get_creator_config("patreon", "42")
    assert saved_creator is not None
    assert saved_creator["options"] == {"main": True}
    assert store.get_creator_config("patreon", "99") is None


def test_store_ignores_other_versions_and_corrupt_payloads(tmp_path):
    store = CreatorConfigStore(str(tmp_path))

    conn = sqlite3.connect(store.db_path)
    conn.execute(
        "INSERT OR REPLACE INTO page_default (scope, payload, saved_at)"
        " VALUES ('default', ?, '')",
        (json.dumps({"version": 999, "options": {"main": True}}),),
    )
    conn.execute(
        "INSERT OR REPLACE INTO creator_config (service, creator_id, payload, saved_at)"
        " VALUES ('patreon', '77', 'not json', '')"
    )
    conn.commit()
    conn.close()

    # A row the tab cannot describe is ignored, never half-applied.
    assert store.get_page_default() is None
    assert store.get_creator_config("patreon", "77") is None


def test_snapshot_holds_options_and_filters_only(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    snapshot = tab._config_snapshot()

    # No post ticks, no URL box, no search text: a profile is configuration.
    assert set(snapshot) == {"options", "filters", "search_scopes", "sorting"}
    assert set(snapshot["sorting"]) == {"enabled", "link_all", "rules"}
    assert snapshot["sorting"]["rules"] == []
    assert set(snapshot["options"]) == {
        "main",
        "attachments",
        "content",
        "download_text",
        "skip_folder",
        "skip_folder_max",
        "force_compressed_folder",
        "skip_images_if_compressed",
        "filetypes",
    }
    assert set(snapshot["filters"]) == {
        "skip_keywords",
        "skip_scopes",
        "file_skip_keywords",
        "date_from",
        "date_to",
        "file_count_from",
        "file_count_to",
        "keep_compressed",
        "filter_no_selected_filetypes",
        "hide_downloaded",
    }


def test_default_profile_restores_every_widget(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    tick(tab.creator_main_check)
    tick(tab.creator_attachments_check)
    tick(tab.creator_content_check)
    tick(tab.creator_download_text_check)
    tick(tab.creator_skip_folder_check)
    tab.creator_skip_folder_combo.setCurrentIndex(4)  # value 5
    tick(tab.creator_force_compressed_folder_check)
    tick(tab.creator_skip_images_check)
    tick(tab.creator_ext_checks[".jpg"])
    tick(tab.creator_ext_checks[".pdf"])
    tab.skip_keywords_edit.setText("wallpaper, sketch")
    tick(tab.skip_scope_checkboxes["title"], False)
    tick(tab.skip_scope_checkboxes["tags"])
    tab.file_skip_keywords_edit.setText("psd")
    tab.date_from_edit.setText("2024-01-01")
    tab.date_to_edit.setText("2024-12-31")
    tab.file_count_from_edit.setText("2")
    tab.file_count_to_edit.setText("9")
    tick(tab.file_count_keep_compressed_check)
    tick(tab.filter_no_selected_filetypes_check)
    tick(tab.search_scope_checkboxes["title"], False)
    tick(tab.search_scope_checkboxes["filenames"])
    tick(tab.creator_hide_downloaded_check)

    assert tab.save_page_config() is True

    fresh = make_tab(qtbot, tmp_path)

    assert fresh.creator_main_check.isChecked() is True
    assert fresh.creator_attachments_check.isChecked() is True
    assert fresh.creator_content_check.isChecked() is True
    assert fresh.creator_download_text_check.isChecked() is True
    assert fresh.creator_skip_folder_check.isChecked() is True
    assert fresh.creator_skip_folder_combo.currentData() == 5
    assert fresh.creator_force_compressed_folder_check.isChecked() is True
    assert fresh.creator_skip_images_check.isChecked() is True
    assert fresh.creator_ext_checks[".jpg"].isChecked() is True
    assert fresh.creator_ext_checks[".pdf"].isChecked() is True
    assert fresh.creator_ext_checks[".png"].isChecked() is False
    assert fresh.skip_keywords_edit.text() == "wallpaper, sketch"
    assert fresh.skip_scope_checkboxes["title"].isChecked() is False
    assert fresh.skip_scope_checkboxes["tags"].isChecked() is True
    assert fresh.file_skip_keywords_edit.text() == "psd"
    assert fresh.date_from_edit.text() == "2024-01-01"
    assert fresh.date_to_edit.text() == "2024-12-31"
    assert fresh.file_count_from_edit.text() == "2"
    assert fresh.file_count_to_edit.text() == "9"
    assert fresh.file_count_keep_compressed_check.isChecked() is True
    assert fresh.filter_no_selected_filetypes_check.isChecked() is True
    assert fresh.creator_hide_downloaded_check.isChecked() is True
    assert fresh.search_scope_checkboxes["title"].isChecked() is False
    assert fresh.search_scope_checkboxes["filenames"].isChecked() is True


def test_creator_profile_replaces_the_default(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    # Default: skip the post folder for small posts, and a keyword filter.
    tick(tab.creator_skip_folder_check)
    tab.skip_keywords_edit.setText("wallpaper")
    assert tab.save_page_config() is True

    # Creator 42 gets its own profile: neither of those.
    tab.current_creator_url = CREATOR_URL
    tab._load_config_for_creator()
    tick(tab.creator_skip_folder_check, False)
    tab.skip_keywords_edit.setText("")
    assert tab.save_creator_config() is True

    # Loading 42 applies its profile as-is, not blended with the default.
    tab.current_creator_url = CREATOR_URL
    tab._load_config_for_creator()
    assert tab.creator_skip_folder_check.isChecked() is False
    assert tab.skip_keywords_edit.text() == ""

    # A creator without a profile falls back to the default, not to 42's.
    tab.current_creator_url = OTHER_CREATOR_URL
    tab._load_config_for_creator()
    assert tab.creator_skip_folder_check.isChecked() is True
    assert tab.skip_keywords_edit.text() == "wallpaper"


def test_clearing_the_viewed_creator_restores_the_default_profile(
    qtbot, tmp_path, monkeypatch
):
    """Removing the viewed creator hands every field back to the default."""
    tab = make_tab(qtbot, tmp_path)
    # The remove handler re-runs the filter pass; that has its own coverage.
    tab.filter_items = lambda: None

    # The default profile leaves the built-in values behind on every field,
    # so a partial restore cannot pass by accident.
    tick(tab.creator_main_check)
    tick(tab.creator_attachments_check)
    tick(tab.creator_content_check)
    tick(tab.creator_download_text_check)
    tick(tab.creator_skip_folder_check)
    tab.creator_skip_folder_combo.setCurrentIndex(4)  # value 5
    tick(tab.creator_force_compressed_folder_check)
    tick(tab.creator_skip_images_check)
    tick(tab.creator_ext_checks[".jpg"])
    tick(tab.creator_ext_checks[".pdf"])
    tab.skip_keywords_edit.setText("wallpaper, sketch")
    tick(tab.skip_scope_checkboxes["title"], False)
    tick(tab.skip_scope_checkboxes["tags"])
    tab.file_skip_keywords_edit.setText("psd")
    tab.date_from_edit.setText("2024-01-01")
    tab.date_to_edit.setText("2024-12-31")
    tab.file_count_from_edit.setText("2")
    tab.file_count_to_edit.setText("9")
    tick(tab.file_count_keep_compressed_check)
    tick(tab.filter_no_selected_filetypes_check)
    tick(tab.search_scope_checkboxes["title"], False)
    tick(tab.search_scope_checkboxes["filenames"])
    assert tab.save_page_config() is True
    expected = tab._config_snapshot()

    # The creator's own profile turns every one of those around.
    tab.current_creator_url = CREATOR_URL
    tab._load_config_for_creator()
    tick(tab.creator_main_check, False)
    tick(tab.creator_attachments_check, False)
    tick(tab.creator_content_check, False)
    tick(tab.creator_download_text_check, False)
    tick(tab.creator_skip_folder_check, False)
    tab.creator_skip_folder_combo.setCurrentIndex(0)  # value 1
    tick(tab.creator_force_compressed_folder_check, False)
    tick(tab.creator_skip_images_check, False)
    tick(tab.creator_ext_checks[".jpg"], False)
    tick(tab.creator_ext_checks[".pdf"], False)
    tab.skip_keywords_edit.setText("sketch")
    tick(tab.skip_scope_checkboxes["title"])
    tick(tab.skip_scope_checkboxes["tags"], False)
    tab.file_skip_keywords_edit.setText("")
    tab.date_from_edit.setText("")
    tab.date_to_edit.setText("")
    tab.file_count_from_edit.setText("")
    tab.file_count_to_edit.setText("")
    tick(tab.file_count_keep_compressed_check, False)
    tick(tab.filter_no_selected_filetypes_check, False)
    tick(tab.search_scope_checkboxes["title"])
    tick(tab.search_scope_checkboxes["filenames"], False)
    assert tab.save_creator_config() is True
    assert tab.skip_keywords_edit.text() == "sketch"

    # Removing the viewed creator from the queue is how the page is cleared.
    tab.creator_queue.append((CREATOR_URL, False))
    monkeypatch.setattr(
        cd.QMessageBox,
        "question",
        lambda *args, **kwargs: cd.QMessageBox.StandardButton.Yes,
    )
    tab.create_remove_handler(CREATOR_URL)()

    assert tab.current_creator_url is None
    # Whole-snapshot equality: every option and filter is back on the default.
    assert tab._config_snapshot() == expected
    assert tab.creator_save_creator_config_btn.isEnabled() is False


def test_clearing_a_creator_without_a_default_restores_the_builtin_state(
    qtbot, tmp_path, monkeypatch
):
    """With no saved default the page returns to its built-in state."""
    tab = make_tab(qtbot, tmp_path)
    tab.filter_items = lambda: None
    expected = copy.deepcopy(tab._config_snapshot())

    tab.current_creator_url = CREATOR_URL
    tick(tab.creator_skip_folder_check)
    tab.skip_keywords_edit.setText("sketch")
    assert tab.save_creator_config() is True

    tab.creator_queue.append((CREATOR_URL, False))
    monkeypatch.setattr(
        cd.QMessageBox,
        "question",
        lambda *args, **kwargs: cd.QMessageBox.StandardButton.Yes,
    )
    tab.create_remove_handler(CREATOR_URL)()

    assert tab._config_snapshot() == expected


def test_no_saved_profiles_means_the_builtin_page_state(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    # Captured before any stored profile could touch the widgets.
    assert tab._builtin_config["options"]["skip_folder"] is False

    tick(tab.creator_skip_folder_check)
    tab.skip_keywords_edit.setText("temporary")
    tab.current_creator_url = CREATOR_URL
    tab._load_config_for_creator()

    assert tab.creator_skip_folder_check.isChecked() is False
    assert tab.skip_keywords_edit.text() == ""


def test_a_broken_filter_entry_refuses_the_save(qtbot, tmp_path, no_blocking_dialogs):
    tab = make_tab(qtbot, tmp_path)
    tab.date_from_edit.setText("2026-13-99")

    assert tab.save_page_config() is False

    assert tab._config_store().get_page_default() is None
    assert no_blocking_dialogs[-1][0] == "warning"
    assert cd.translate("config_save_invalid_title") == no_blocking_dialogs[-1][1]


def test_creator_button_needs_a_loaded_creator(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.creator_save_config_btn.isEnabled() is True
    assert tab.creator_save_creator_config_btn.isEnabled() is False

    tab.current_creator_url = CREATOR_URL
    tab._load_config_for_creator()
    assert tab.creator_save_creator_config_btn.isEnabled() is True

    # Both go quiet during a run: the download already snapshotted its options.
    tab.downloading = True
    tab._refresh_config_buttons()
    assert tab.creator_save_config_btn.isEnabled() is False
    assert tab.creator_save_creator_config_btn.isEnabled() is False


def test_creator_config_without_a_creator_is_refused(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.save_creator_config() is False
    assert tab._config_store().get_creator_config("patreon", "42") is None


def test_a_missing_store_only_logs(
    qtbot, tmp_path, monkeypatch, no_blocking_dialogs
):
    tab = make_tab(qtbot, tmp_path)

    def boom(directory):
        raise OSError("no room left")

    # Fail the store open, exactly as a broken Data Directory would.
    monkeypatch.setattr(cd, "CreatorConfigStore", boom)
    tab._config_store_instance = None
    tab._config_store_dir = None
    tab._config_store_failed_dir = None

    assert tab.save_page_config() is False
    assert no_blocking_dialogs == []
    messages = [message for message, _colour in tab.log_lines_from(0)]
    assert any("config" in message.lower() for message in messages)
    # The failed open is remembered rather than retried on every save.
    assert tab._config_store() is None
    assert tab._config_store_failed_dir == tab.other_files_dir
    # Loading is just as tolerant.
    tab._load_page_config()
    tab.current_creator_url = CREATOR_URL
    tab._load_config_for_creator()


def test_the_builtin_baseline_is_never_mutated(qtbot, tmp_path):
    """Applying the baseline must not consume it; it is the fallback forever."""
    tab = make_tab(qtbot, tmp_path)
    before = copy.deepcopy(tab._builtin_config)

    tick(tab.creator_skip_folder_check)
    tab._apply_config(tab._builtin_config)

    assert tab.creator_skip_folder_check.isChecked() is False
    assert tab._builtin_config == before


def test_applying_a_profile_while_posts_are_loaded_refilters_once(qtbot, tmp_path):
    """A restored filter has to be applied to a list that is already there."""
    tab = make_tab(qtbot, tmp_path)
    calls = []
    tab.filter_items = lambda: calls.append(1)
    tab.all_detected_posts = [("A post", ("1", None))]

    tab._apply_config({"filters": {"skip_keywords": "x"}})

    assert calls == [1]
    assert tab.skip_keywords_edit.text() == "x"


def test_a_creator_save_needs_a_usable_identity(qtbot, tmp_path, no_blocking_dialogs):
    """No identity means no write and no success message."""
    tab = make_tab(qtbot, tmp_path)
    store = tab._config_store()
    payload = tab._config_snapshot()

    # Half an identity, and an empty one, both refuse instead of writing the
    # page default and reporting a save that never happened.
    assert tab._store_config(payload, "patreon", "") is False
    assert tab._store_config(payload, "", "") is False
    assert store.get_page_default() is None
    assert no_blocking_dialogs == []


def test_a_creator_url_without_a_service_is_refused(qtbot, tmp_path):
    """split_creator_url yields an empty service for a non-creator URL."""
    tab = make_tab(qtbot, tmp_path)
    tab.current_creator_url = "https://kemono.cr/notacreator"

    assert tab.save_creator_config() is False
    assert tab._config_store().get_page_default() is None


def test_config_buttons_unlock_when_a_run_ends(qtbot, tmp_path):
    """A finished run must hand the page back, not leave the buttons greyed."""
    tab = make_tab(qtbot, tmp_path)
    tab.current_creator_url = CREATOR_URL
    tab._refresh_config_buttons()
    assert tab.creator_save_config_btn.isEnabled() is True

    tab.downloading = True
    tab.set_downloading_ui_state(True)
    assert tab.creator_save_config_btn.isEnabled() is False
    assert tab.creator_save_creator_config_btn.isEnabled() is False

    tab.downloading = False
    tab._download_thread = None
    tab.set_downloading_ui_state(False)

    assert tab.creator_save_config_btn.isEnabled() is True
    assert tab.creator_save_creator_config_btn.isEnabled() is True


def test_cleanup_thread_unlocks_the_config_buttons(qtbot, tmp_path):
    """The thread-lifetime beat: the retry button unlocks here, so must these."""
    tab = make_tab(qtbot, tmp_path)
    tab.current_creator_url = CREATOR_URL

    class FakeThread:
        failed_files = {}

        def isRunning(self):
            return False

        def wait(self, ms):
            return True

        def deleteLater(self):
            pass

    thread = FakeThread()
    tab.active_threads = [thread]
    tab._download_thread = thread
    tab.downloading = True
    tab._refresh_config_buttons()
    assert tab.creator_save_config_btn.isEnabled() is False

    # creator_download_finished() ran while the thread was still winding down.
    tab.downloading = False
    tab.cleanup_thread(thread)

    assert tab._download_thread is None
    assert tab.creator_save_config_btn.isEnabled() is True
    assert tab.creator_save_creator_config_btn.isEnabled() is True


def test_creator_load_hands_the_saved_filters_to_the_fetch(qtbot, tmp_path):
    captured = {}

    class FakePostDetectionThread:
        def __init__(self, url, post_titles_map, settings, **kwargs):
            captured.update(kwargs)
            self.finished = FakeSignal()
            self.posts_batch = FakeSignal()
            self.log = FakeSignal()
            self.error = FakeSignal()

        def start(self):
            pass

    tab = make_tab(qtbot, tmp_path)
    tab.skip_keywords_edit.setText("keepme")
    tab.current_creator_url = CREATOR_URL
    assert tab.save_creator_config() is True

    # A later change is not what this creator's profile says any more.
    tab.skip_keywords_edit.setText("")
    tab.creator_queue.append((CREATOR_URL, False))

    original = cd.PostDetectionThread
    cd.PostDetectionThread = FakePostDetectionThread
    try:
        tab.check_creator_from_queue(CREATOR_URL)
    finally:
        cd.PostDetectionThread = original

    assert captured["post_filters"].skip_keywords == ("keepme",)
    assert tab.skip_keywords_edit.text() == "keepme"


def test_switching_creators_applies_the_new_profile_explicitly(qtbot, tmp_path):
    """No creator-to-creator switch may keep the previous creator's rules."""
    tab = make_tab(qtbot, tmp_path)
    tab.filter_items = lambda: None

    # Page default: sorting on, one Cats rule.
    tab.creator_sort_enabled_check.setChecked(True)
    tab._sort_rules = [cd.SortRule("Cats", values=("cat",))]
    assert tab.save_page_config() is True

    # Creator 42 has its own profile: sorting off, a Dogs rule.
    tab.current_creator_url = CREATOR_URL
    tab._load_config_for_creator()
    tab.creator_sort_enabled_check.setChecked(False)
    tab._sort_rules = [cd.SortRule("Dogs", values=("dog",))]
    assert tab.save_creator_config() is True

    # Creator 99 has no profile: the page default, not 42's values.
    tab.current_creator_url = OTHER_CREATOR_URL
    tab._load_config_for_creator()
    assert tab.creator_sort_enabled_check.isChecked() is True
    assert [rule.folder for rule in tab._sort_rules] == ["Cats"]

    # Back to 42: its own values, explicitly.
    tab.current_creator_url = CREATOR_URL
    tab._load_config_for_creator()
    assert tab.creator_sort_enabled_check.isChecked() is False
    assert [rule.folder for rule in tab._sort_rules] == ["Dogs"]


def test_a_profile_without_the_sorting_key_gets_the_page_default(qtbot, tmp_path):
    """A creator profile saved before sorting existed must not inherit rules."""
    tab = make_tab(qtbot, tmp_path)
    tab.filter_items = lambda: None
    store = tab._config_store()
    store.set_page_default(
        {
            "sorting": {
                "enabled": True,
                "link_all": True,
                "rules": [
                    {"folder": "Cats", "kind": "tag", "values": ["cat"]}
                ],
            }
        }
    )
    # A creator profile written before the sorting key existed.
    store.set_creator_config("patreon", "42", {"options": {"skip_folder": True}})

    tab.current_creator_url = CREATOR_URL
    tab._sort_rules = [cd.SortRule("Junk", values=("junk",))]
    tab._load_config_for_creator()

    assert tab.creator_sort_enabled_check.isChecked() is True
    assert tab._sort_link_all is True
    assert [rule.folder for rule in tab._sort_rules] == ["Cats"]
    assert tab.creator_skip_folder_check.isChecked() is True


