import hashlib
import os
from types import SimpleNamespace

from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


class FakeFileResponse:
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


class FakeAPIResponse:
    def __init__(self, data, code=200):
        self._data = data
        self.status_code = code

    def json(self):
        return self._data


class FakeSessionMulti:
    def __init__(self, profile_name, post_titles, file_chunks_map):
        self.profile_name = profile_name
        self.post_titles = post_titles
        self.file_chunks_map = file_chunks_map

    def get(self, url, *args, **kwargs):
        if url.endswith("/profile"):
            return FakeAPIResponse({"name": self.profile_name}, 200)
        if "/post/" in url:
            # return a post JSON
            pid = url.rstrip("/").split("/")[-1]
            title = self.post_titles.get(pid, f"Post_{pid}")
            return FakeAPIResponse({"title": title}, 200)
        if url in self.file_chunks_map:
            return FakeFileResponse(self.file_chunks_map[url])
        return FakeAPIResponse({}, 404)


class FakeHashDB:
    def __init__(self):
        self.store_calls = {}
        self.lookup_map = {}

    def lookup(self, url_hash):
        return self.lookup_map.get(url_hash)

    def store(self, url_hash, path, file_hash, file_url, file_size):
        self.store_calls[url_hash] = {
            "file_path": path,
            "file_hash": file_hash,
            "file_size": file_size,
        }


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


def test_creator_run_downloads_all_files(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "out_run")
    other_files_dir = str(tmp_path / "other_run")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file1 = "https://kemono.cr/files/a.png"
    file2 = "https://kemono.cr/files/b.png"
    files_to_download = [file1, file2]
    files_to_posts_map = {file1: "1", file2: "1"}

    chunks_a = [b"aaa"]
    chunks_b = [b"bbbb"]

    fake_session = FakeSessionMulti(
        "CreatorX", {"1": "MyPost"}, {file1: chunks_a, file2: chunks_b}
    )

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: fake_session,
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
        post_titles_map={},
        auto_rename_enabled=False,
        settings=settings,
        max_concurrent=2,
        download_text=False,
    )

    # Inject fake HashDB
    fake_db = FakeHashDB()
    thread.hash_db = fake_db

    # Run the full thread run loop synchronously
    thread.run()

    assert file1 in thread.completed_files
    assert file2 in thread.completed_files
    # HashDB should have stored entries for both files
    assert len(fake_db.store_calls) == 2


def test_creator_skips_existing_hash_entry(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "out_run2")
    other_files_dir = str(tmp_path / "other_run2")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/exists.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Create an existing file in other_files_dir
    existing_path = os.path.join(other_files_dir, "exists.png")
    with open(existing_path, "wb") as f:
        f.write(b"content")
    actual_size = os.path.getsize(existing_path)
    with open(existing_path, "rb") as f:
        file_hash = hashlib.md5(f.read()).hexdigest()

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
        max_concurrent=1,
        download_text=False,
    )

    # Monkeypatch session to ensure no network calls are attempted
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: (_ for _ in ()).throw(
            RuntimeError("Should not be called")
        ),
    )

    fake_db = FakeHashDB()
    # Return entry matching existing file
    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    fake_db.lookup_map[url_hash] = {
        "file_path": existing_path,
        "file_hash": file_hash,
        "file_size": actual_size,
    }
    thread.hash_db = fake_db

    # Call download_file which should detect existing file and skip download
    import asyncio

    asyncio.run(thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1))

    assert file_url in thread.completed_files
