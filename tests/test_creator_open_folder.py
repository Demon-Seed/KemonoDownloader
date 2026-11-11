"""The "open creator folder" button and the folder hint behind it.

The button sits with the run controls but follows the folder, not the run: it
is visible from the start and greyed out until the current run's creator
folder actually exists on disk.
"""

import os
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd
from kemonodownloader.kd_language import translate


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


def make_tab(qtbot, tmp_path):
    tab = cd.CreatorDownloaderTab(make_parent(tmp_path))
    qtbot.addWidget(tab)
    return tab


class FakeSignal:
    def connect(self, *_args):
        return None


class FakeThread:
    def __init__(self, *args, **_kwargs):
        pass

    def __getattr__(self, _name):
        return FakeSignal()

    def start(self):
        return None


def test_the_button_starts_visibly_disabled(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)

    assert tab.creator_open_folder_btn.isEnabled() is False
    assert tab.creator_open_folder_btn.toolTip() == translate(
        "open_creator_folder_waiting"
    )
    assert tab.creator_open_folder_btn.text() == translate("open_creator_folder")
    # White icon, same as the run buttons beside it.
    assert not tab.creator_open_folder_btn.icon().isNull()


def test_a_confirmed_folder_enables_the_button(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    folder = tmp_path / "download" / "42_Creator"
    folder.mkdir(parents=True)

    tab._on_creator_folder_ready(str(folder))

    assert tab.creator_open_folder_btn.isEnabled() is True
    assert tab.creator_open_folder_btn.toolTip() == translate(
        "open_creator_folder_tooltip"
    )


def test_clicking_opens_the_folder(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    folder = tmp_path / "download" / "42_Creator"
    folder.mkdir(parents=True)
    tab._on_creator_folder_ready(str(folder))

    opened = []
    monkeypatch.setattr(cd.QDesktopServices, "openUrl", opened.append)

    tab.creator_open_folder_btn.click()

    assert len(opened) == 1
    assert opened[0].isLocalFile()
    opened_path = os.path.normpath(opened[0].toLocalFile())
    assert os.path.normcase(opened_path) == os.path.normcase(str(folder))


def test_a_vanished_folder_logs_and_disables_the_button(
    qtbot, tmp_path, monkeypatch
):
    tab = make_tab(qtbot, tmp_path)
    folder = tmp_path / "download" / "42_Creator"
    folder.mkdir(parents=True)
    tab._on_creator_folder_ready(str(folder))
    folder.rmdir()

    logged = []
    monkeypatch.setattr(
        tab,
        "append_log_to_console",
        lambda message, level="INFO": logged.append(message),
    )
    monkeypatch.setattr(cd.QDesktopServices, "openUrl", lambda url: None)

    tab.creator_open_folder_btn.click()

    assert tab.creator_open_folder_btn.isEnabled() is False
    assert logged and "42_Creator" in logged[0]


def test_the_button_stays_usable_during_a_download(qtbot, tmp_path):
    tab = make_tab(qtbot, tmp_path)
    folder = tmp_path / "download" / "42_Creator"
    folder.mkdir(parents=True)
    tab._on_creator_folder_ready(str(folder))

    tab.set_downloading_ui_state(True)

    assert tab.creator_open_folder_btn.isEnabled() is True


def test_a_new_run_disables_the_button_again(qtbot, tmp_path, monkeypatch):
    tab = make_tab(qtbot, tmp_path)
    folder = tmp_path / "download" / "42_Creator"
    folder.mkdir(parents=True)
    tab._on_creator_folder_ready(str(folder))
    assert tab.creator_open_folder_btn.isEnabled() is True

    monkeypatch.setattr(cd, "CreatorDownloadThread", FakeThread)
    files = {"https://n1.kemono.cr/data/a.png": "1"}
    tab._start_download_thread(
        list(files), dict(files), "https://kemono.cr/patreon/user/42"
    )

    assert tab.creator_open_folder_btn.isEnabled() is False


def test_the_thread_records_and_announces_its_folder_once(tmp_path):
    file_url = "https://n1.kemono.cr/data/a.png"
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{file_number}_{post_id}_{orig_name}",
        get_creator_filename_template_shared=lambda: (
            "{post_id}_{file_number}_{orig_name}"
        ),
        get_creator_folder_strategy=lambda: "per_post",
        get_creator_unique_filenames=lambda: True,
    )
    thread = cd.CreatorDownloadThread(
        "patreon",
        "42",
        str(tmp_path / "dl"),
        ["111"],
        [file_url],
        {file_url: "111"},
        None,
        str(tmp_path / "other"),
        {("patreon", "42", "111"): "Post"},
        SimpleNamespace(settings_tab=settings_tab, file_download_max_retries=1),
        max_concurrent=1,
    )
    thread.creator_name = "Creator"

    target_folder, _filename = thread.generate_filename_and_folder(
        file_url, str(tmp_path / "dl"), 0, 1, "111", "Post", 1
    )

    # Per-post strategy: the creator folder is the post folder's parent.
    assert thread._creator_folder == os.path.dirname(target_folder)
    assert os.path.basename(thread._creator_folder) == "42_Creator"

    seen = []
    thread.creator_folder_ready.connect(seen.append)
    thread._announce_creator_folder()
    thread._announce_creator_folder()

    assert seen == [thread._creator_folder]

