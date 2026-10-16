import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests

import kemonodownloader.creator_downloader as cd


def make_thread_for_download(tmp_path, settings=None):
    dl = tmp_path / "dl"
    other = tmp_path / "other"
    dl.mkdir(exist_ok=True)
    other.mkdir(exist_ok=True)
    t = cd.CreatorDownloadThread(
        "svc",
        "42",
        str(dl),
        ["p1"],
        [],
        {},
        MagicMock(),
        str(other),
        {("svc", "42", "p1"): "Title"},
        False,
        settings,
        max_concurrent=1,
    )
    return t


def test_download_file_makedirs_failure(tmp_path, monkeypatch):
    settings = SimpleNamespace(file_download_max_retries=1, settings_tab=None)
    t = make_thread_for_download(tmp_path, settings=settings)
    file_url = "https://kemono.cr/media/1.png?f=file.png"
    t.files_to_download = [file_url]
    t.files_to_posts_map = {file_url: "p1"}
    t.post_files_map = {"p1": [file_url]}

    def bad_makedirs(*args, **kwargs):
        raise OSError("no space")

    monkeypatch.setattr(cd.os, "makedirs", bad_makedirs)

    asyncio.run(t.download_file(file_url, str(tmp_path / "dl"), 0, 1, page_number=1))

    assert file_url in t.failed_files


def test_download_file_requests_exception(monkeypatch, tmp_path):
    settings = SimpleNamespace(file_download_max_retries=1, settings_tab=None)
    t = make_thread_for_download(tmp_path, settings=settings)
    file_url = "https://kemono.cr/media/2.png?f=file2.png"
    t.files_to_download = [file_url]
    t.files_to_posts_map = {file_url: "p1"}
    t.post_files_map = {"p1": [file_url]}

    class S:
        def get(self, *a, **k):
            raise requests.RequestException("network")

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    asyncio.run(t.download_file(file_url, str(tmp_path / "dl"), 0, 1, page_number=1))

    assert file_url in t.failed_files
