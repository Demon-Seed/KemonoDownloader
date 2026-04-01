import asyncio
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


class DummySignal:
    def __init__(self):
        self.emitted = False
        self.last_args = None

    def emit(self, *args):
        self.emitted = True
        self.last_args = args


class DummyHashDB:
    def __init__(self, other_files_dir):
        pass

    def lookup(self, *a, **k):
        return None

    def store(self, *a, **k):
        return None


def make_thread(tmp_path, settings=None):
    file_url = "https://ex.test/media/file.png"
    t = cd.CreatorDownloadThread(
        service="svc",
        creator_id="c1",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["p1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "p1"},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        auto_rename_enabled=False,
        settings=settings
        or SimpleNamespace(settings_tab=None, file_download_max_retries=1),
        max_concurrent=1,
    )
    t.hash_db = DummyHashDB(str(tmp_path / "other"))
    return t, file_url


def test_fetch_creator_and_post_info_success(monkeypatch, tmp_path):
    settings = SimpleNamespace(settings_tab=None)
    t, file_url = make_thread(tmp_path, settings=settings)
    # Provide domain config used by fetch_creator_and_post_info
    t.domain_config = {"api_base": "https://api.test", "referer": "https://test"}

    profile_resp = SimpleNamespace(
        status_code=200, json=lambda: {"name": "The Creator"}
    )
    post_resp = SimpleNamespace(status_code=200, json=lambda: {"title": "PostTitle"})

    class Sess:
        def get(self, url, headers=None, timeout=None):
            if "profile" in url:
                return profile_resp
            return post_resp

    monkeypatch.setattr(cd, "get_session", lambda st=None: Sess())

    # Run and assert
    t.fetch_creator_and_post_info()
    assert t.creator_name == "The_Creator"
    key = (t.service, t.creator_id, "p1")
    assert t.post_titles_map.get(key) == "PostTitle"


def test_fetch_creator_and_post_info_failure(monkeypatch, tmp_path):
    settings = SimpleNamespace(settings_tab=None)
    t, file_url = make_thread(tmp_path, settings=settings)
    t.domain_config = {"api_base": "https://api.test", "referer": "https://test"}

    # Profile returns 500, post returns 500
    profile_resp = SimpleNamespace(status_code=500)
    post_resp = SimpleNamespace(status_code=500)

    class Sess:
        def get(self, url, headers=None, timeout=None):
            return profile_resp if "profile" in url else post_resp

    monkeypatch.setattr(cd, "get_session", lambda st=None: Sess())

    t.fetch_creator_and_post_info()
    assert t.creator_name == "Unknown_Creator"
    key = (t.service, t.creator_id, "p1")
    assert t.post_titles_map.get(key).startswith("Post_")


def test_download_file_makedirs_failure(monkeypatch, tmp_path):
    t, file_url = make_thread(tmp_path)

    # Make makedirs raise OSError inside creator_downloader module
    def bad_makedirs(*a, **k):
        raise OSError("no perms")

    monkeypatch.setattr(cd.os, "makedirs", bad_makedirs)
    # Capture file_completed emission
    sig = DummySignal()
    t.file_completed = sig

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1))
    assert file_url in t.failed_files
    assert sig.emitted is True


def test_download_file_size_mismatch(monkeypatch, tmp_path):
    t, file_url = make_thread(tmp_path)
    t.settings.file_download_max_retries = 1

    # Ensure target folder can be created
    # Provide a fake session that reports content-length 10 but yields 5 bytes
    class FakeResp:
        status_code = 200

        headers = {"content-length": "10"}

        def raise_for_status(self):
            return None

        def iter_content(self, chunk_size=8192):
            yield b"12345"

        def close(self):
            return None

    class Sess:
        def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(cd, "get_session", lambda st=None: Sess())
    t.hash_db = DummyHashDB(str(tmp_path / "other"))
    sig = DummySignal()
    t.file_completed = sig

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1))
    assert file_url in t.failed_files
    assert sig.emitted is True


def test_download_worker_processes_queue(tmp_path):
    t, file_url = make_thread(tmp_path)
    called = []

    async def fake_download(f_url, folder, idx, total):
        called.append(f_url)
        # stop the worker after one item
        t.is_running = False

    t.download_file = fake_download

    async def main():
        q = asyncio.Queue()
        await q.put((0, file_url))
        await t.download_worker(q, str(tmp_path), 1)

    asyncio.run(main())
    assert called == [file_url]
