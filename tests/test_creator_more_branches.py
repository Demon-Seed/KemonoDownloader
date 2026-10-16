import asyncio
import os
from types import SimpleNamespace

import requests

from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


def make_settings():
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: None,
        get_creator_folder_strategy=lambda: "per_post",
        get_proxy_settings=lambda: None,
    )
    return ThreadSettings(
        creator_posts_max_attempts=1,
        post_data_max_retries=1,
        file_download_max_retries=1,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def test_request_exception_records_failure(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "req_fail")
    other_files_dir = str(tmp_path / "other_req")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/err.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    def bad_get(*a, **k):
        raise requests.RequestException("network error")

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: SimpleNamespace(get=bad_get),
    )

    settings = make_settings()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creator123", "1"): "MyPost"},
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    asyncio.run(thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1))

    assert file_url in thread.failed_files
    assert "network error" in thread.failed_files[file_url]


def test_download_post_text_only_once(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "dt_once")
    other_files_dir = str(tmp_path / "other_dt")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    settings = make_settings()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creator123", "1"): "MyPost"},
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    class FakeSessionCount:
        def __init__(self):
            self.calls = 0

        def get(self, *a, **k):
            self.calls += 1

            class R:
                status_code = 200

                def json(self):
                    return {"post": {"content": "<p>Hello</p>"}}

            return R()

    fake = FakeSessionCount()
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: fake,
    )

    post_folder = str(tmp_path / "postfolder")
    os.makedirs(post_folder, exist_ok=True)

    asyncio.run(thread.download_post_text_if_needed("1", post_folder))
    asyncio.run(thread.download_post_text_if_needed("1", post_folder))

    assert fake.calls == 1
    assert os.path.exists(os.path.join(post_folder, "desc_1.txt"))


def test_redownload_when_hash_size_mismatch(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "rd_mismatch")
    other_files_dir = str(tmp_path / "other_rd")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/re.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Create an existing file with a size that differs from the DB entry
    existing_path = os.path.join(other_files_dir, "re.png")
    with open(existing_path, "wb") as f:
        f.write(b"old")

    fake_db = SimpleNamespace(
        lookup=lambda h: {
            "file_path": existing_path,
            "file_hash": "oldhash",
            "file_size": 999,
        },
        store=lambda *a, **k: setattr(fake_db, "stored", True),
    )

    class FakeFileResp:
        def __init__(self, chunks):
            self._chunks = chunks
            self.status_code = 200
            self.headers = {"content-length": str(sum(len(c) for c in chunks))}

        def iter_content(self, chunk_size=8192):
            for c in self._chunks:
                yield c

        def raise_for_status(self):
            return None

        def close(self):
            return None

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: SimpleNamespace(
            get=lambda *a, **k: FakeFileResp([b"n"])
        ),
    )

    settings = make_settings()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creator123", "1"): "MyPost"},
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )
    thread.hash_db = fake_db

    asyncio.run(thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1))

    assert getattr(fake_db, "stored", False) is True


def test_get_desc_folder_for_post_various_strategies(tmp_path):
    base = str(tmp_path / "base_desc")
    os.makedirs(base, exist_ok=True)

    settings = make_settings()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=base,
        selected_posts=["1"],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={("svc", "creator123", "1"): "MyPost"},
        auto_rename_enabled=False,
        settings=settings,
        download_text=False,
    )

    # per_post (default)
    d = thread.get_desc_folder_for_post(
        os.path.join(
            base, f"{thread.creator_id}_{thread.creator_name or thread.creator_id}"
        ),
        "1",
        "MyPost",
    )
    assert "1_MyPost" in d

    # single_folder
    thread.settings.settings_tab = SimpleNamespace(
        get_creator_folder_strategy=lambda: "single_folder"
    )
    d2 = thread.get_desc_folder_for_post(
        os.path.join(
            base, f"{thread.creator_id}_{thread.creator_name or thread.creator_id}"
        ),
        "1",
        "MyPost",
    )
    assert d2.endswith(
        os.path.join(f"{thread.creator_id}_{thread.creator_name or thread.creator_id}")
    )

    # by_file_type
    thread.settings.settings_tab = SimpleNamespace(
        get_creator_folder_strategy=lambda: "by_file_type"
    )
    d3 = thread.get_desc_folder_for_post(
        os.path.join(
            base, f"{thread.creator_id}_{thread.creator_name or thread.creator_id}"
        ),
        "1",
        "MyPost",
    )
    assert d3.endswith("txt") or "txt" in d3
