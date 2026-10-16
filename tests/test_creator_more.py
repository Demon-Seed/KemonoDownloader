import asyncio
import os

import requests

from kemonodownloader import creator_downloader as cd


def test_generate_filename_template_fallback(qapp, tmp_path):
    class SettingsTab:
        def get_creator_filename_template(self):
            return "{nonexistent}"

        def get_creator_folder_strategy(self):
            return "per_post"

    class Settings:
        settings_tab = SettingsTab()

    thread = cd.CreatorDownloadThread(
        "svc",
        "creator",
        str(tmp_path),
        ["1"],
        [],
        {},
        object(),
        str(tmp_path),
        {("svc", "creator", "1"): "Title"},
        True,
        Settings(),
        1,
    )

    folder, filename = thread.generate_filename_and_folder(
        "https://kemono.cr/some/file.txt", str(tmp_path), 0, 1, "1", "Title", page_number=1
    )
    # Template formatting should have fallen back to post_id_orig_name
    assert (
        filename.startswith("1_") or filename.startswith("post_1_") or "1_" in filename
    )


def test_get_desc_folder_for_post_variants(qapp, tmp_path):
    class SettingsTab:
        def get_creator_folder_strategy(self):
            return "by_file_type"

    class Settings:
        settings_tab = SettingsTab()

    thread = cd.CreatorDownloadThread(
        "svc",
        "creator",
        str(tmp_path),
        ["1"],
        [],
        {},
        object(),
        str(tmp_path),
        {},
        True,
        Settings(),
        1,
    )

    creator_folder = os.path.join(str(tmp_path), "creator_folder")
    # by_file_type -> txt subfolder
    d = thread.get_desc_folder_for_post(creator_folder, "1", "Title")
    assert os.path.basename(d) == "txt"

    # single_folder
    thread.settings.settings_tab.get_creator_folder_strategy = lambda: "single_folder"
    d2 = thread.get_desc_folder_for_post(creator_folder, "1", "Title")
    assert d2 == os.path.normpath(creator_folder)

    # per_post
    thread.settings.settings_tab.get_creator_folder_strategy = lambda: "per_post"
    d3 = thread.get_desc_folder_for_post(creator_folder, "2", "Some Post")
    assert os.path.basename(d3).startswith("2_")


def test_download_file_folder_creation_error(monkeypatch, qapp, tmp_path):
    class SettingsTab:
        pass

    class Settings:
        settings_tab = SettingsTab()
        file_download_max_retries = 1

    download_folder = str(tmp_path)
    file_url = "https://kemono.cr/path/fail.dat"

    thread = cd.CreatorDownloadThread(
        "svc",
        "creator",
        download_folder,
        ["1"],
        [file_url],
        {file_url: "1"},
        object(),
        str(tmp_path),
        {("svc", "creator", "1"): "Title"},
        True,
        Settings(),
        1,
    )

    # Cause os.makedirs to raise OSError inside module
    def fake_makedirs(path, exist_ok=False):
        raise OSError("no space")

    monkeypatch.setattr(cd.os, "makedirs", fake_makedirs)

    completed = []
    thread.file_completed.connect(
        lambda idx, url, success: completed.append((idx, url, success))
    )

    asyncio.run(thread.download_file(file_url, download_folder, 0, 1, page_number=1))

    # file_completed should have been emitted with success False
    assert any(not c[2] for c in completed)
    assert file_url in thread.failed_files


def test_download_file_request_exception_retries(monkeypatch, qapp, tmp_path):
    class SettingsTab:
        pass

    class Settings:
        settings_tab = SettingsTab()
        file_download_max_retries = 1

    download_folder = str(tmp_path)
    file_url = "https://kemono.cr/path/noresp.dat"

    thread = cd.CreatorDownloadThread(
        "svc",
        "creator",
        download_folder,
        ["1"],
        [file_url],
        {file_url: "1"},
        object(),
        str(tmp_path),
        {("svc", "creator", "1"): "Title"},
        True,
        Settings(),
        1,
    )

    # Make session.get raise RequestException
    def fake_get_session(tab=None):
        class S:
            def get(self, url, headers=None, stream=None, timeout=None):
                raise requests.RequestException("down")

        return S()

    monkeypatch.setattr(cd, "get_session", fake_get_session)

    completed = []
    thread.file_completed.connect(
        lambda idx, url, success: completed.append((idx, url, success))
    )

    asyncio.run(thread.download_file(file_url, download_folder, 0, 1, page_number=1))

    assert any(not c[2] for c in completed)
    assert file_url in thread.failed_files


def test_tab_update_file_completion_reads_thread_error(qapp, tmp_path):
    parent = type("P", (), {})()
    parent.cache_folder = str(tmp_path)
    parent.other_files_folder = str(tmp_path)
    parent.download_folder = str(tmp_path)

    tab = cd.CreatorDownloaderTab(parent)

    # Create a real CreatorDownloadThread and set a failed_files mapping
    class SettingsTab:
        pass

    class Settings:
        settings_tab = SettingsTab()

    file_url = "https://kemono.cr/x.dat"
    thread = cd.CreatorDownloadThread(
        "svc",
        "creator",
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        tab.creator_console,
        str(tmp_path),
        {},
        True,
        Settings(),
        1,
    )
    thread.failed_files[file_url] = "boom"
    tab.active_threads.append(thread)

    # Call update_file_completion with failure
    tab.update_file_completion(0, file_url, False)
    assert file_url in tab.failed_files
