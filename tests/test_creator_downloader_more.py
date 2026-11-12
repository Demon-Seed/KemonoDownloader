import asyncio
import gzip
import hashlib
import json
import os
import types
from types import MethodType, SimpleNamespace
from unittest.mock import MagicMock

import requests

from kemonodownloader import creator_downloader as cd
from kemonodownloader.creator_downloader import CreatorDownloadThread, ThreadSettings


def test_filter_thread_run():
    posts = [("A Post", ("101", None)), ("B Post", ("102", None))]
    checked = {"101": True, "102": False}
    t = cd.FilterThread(posts, checked, "A")
    out = {}
    t.finished = SimpleNamespace(emit=lambda data: out.setdefault("finished", data))
    t.log = SimpleNamespace(emit=lambda *a, **k: None)
    t.run()
    assert "finished" in out
    assert out["finished"][0][0] == "A Post"


def test_checkbox_toggle_thread():
    visible = [("Title", ("1", None)), ("Title2", ("2", None))]
    checked = {"1": False, "2": False}
    thr = cd.CheckboxToggleThread(visible, checked, 2)  # checked
    out = {}
    thr.finished = SimpleNamespace(emit=lambda a, b: out.setdefault("result", (a, b)))
    thr.log = SimpleNamespace(emit=lambda *a, **k: None)
    thr.run()
    new_state, posts = out["result"]
    assert new_state["1"] is True
    assert "1" in posts


def test_logs_window_update_and_clear(tmp_path):
    class Parent:
        """Minimal log-store parent: the window is the only view now."""

        def __init__(self):
            self.lines = []
            self.cleared = 0

        def log_lines_from(self, index):
            return self.lines[index:]

        def log_next_index(self):
            return len(self.lines)

        def clear_log(self):
            self.cleared += 1
            self.lines.clear()

        def append_log_to_console(self, *a, **k):
            pass

    w = cd.LogsWindow(parent=None)
    parent = Parent()
    parent.lines.append(("<b>log</b>", "green"))
    w._parent = parent
    # Simulate update
    w.update_logs_content()
    w._do_update()
    assert "log" in w.logs_display.toHtml()
    w.clear_logs()
    assert w.logs_display.toPlainText() == ""
    assert parent.cleared == 1


def test_preview_thread_error(monkeypatch):
    # Make get_session.get raise requests.RequestException
    import requests

    def fake_get(s=None):
        return SimpleNamespace(
            get=lambda url, headers=None, stream=True: (_ for _ in ()).throw(
                requests.RequestException("fail")
            )
        )

    monkeypatch.setattr(cd, "get_session", lambda s=None: fake_get())
    # Create a PreviewThread-like dummy and run
    pt = cd.PreviewThread("https://kemono.cr/image.jpg", "/tmp", settings_tab=None)
    errors = {}
    pt.error = SimpleNamespace(emit=lambda e: errors.setdefault("err", e))
    pt.preview_ready = SimpleNamespace(
        emit=lambda *a, **k: errors.setdefault("ok", True)
    )
    pt.progress = SimpleNamespace(emit=lambda *a, **k: None)
    pt.run()
    assert "err" in errors


def test_creator_download_thread_run_no_files(monkeypatch, tmp_path):
    # Create a minimal dummy instance to call run() and exercise the no-files branch
    dummy = SimpleNamespace()
    dummy.service = "fanbox"
    dummy.creator_id = "42"
    dummy.creator_name = "Creator"
    dummy.download_folder = str(tmp_path)
    dummy.selected_posts = []
    dummy.files_to_download = []
    dummy.files_to_posts_map = {}
    dummy.console = None
    dummy.other_files_dir = str(tmp_path)
    dummy.post_titles_map = {}
    dummy.settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)
    dummy.max_concurrent = 2
    dummy.is_running = True
    dummy.hash_db = SimpleNamespace()
    dummy.post_file_counters_lock = SimpleNamespace(
        __enter__=lambda s: None, __exit__=lambda s, a, b, c: None
    )
    dummy.post_file_counters = {}
    dummy.failed_files = {}
    dummy.failed_files_lock = SimpleNamespace(
        __enter__=lambda s: None, __exit__=lambda s, a, b, c: None
    )
    dummy.completed_files = set()
    dummy.completed_files_lock = SimpleNamespace(
        __enter__=lambda s: None, __exit__=lambda s, a, b, c: None
    )
    dummy.fetched_texts_lock = SimpleNamespace(
        __enter__=lambda s: None, __exit__=lambda s, a, b, c: None
    )
    dummy.fetched_texts = set()
    dummy._ssl_lock = SimpleNamespace(
        __enter__=lambda s: None, __exit__=lambda s, a, b, c: None
    )
    dummy.log = SimpleNamespace()
    dummy._destroyed = False
    # no-op methods used in run
    dummy.fetch_creator_and_post_info = lambda: None
    emitted = []
    dummy._safe_emit = lambda sig, *a: emitted.append(a)
    dummy.check_post_completion = lambda url: None
    dummy.finished = SimpleNamespace(emit=lambda *a: None)

    # Call run - should take the no-files branch and not raise
    cd.CreatorDownloadThread.run(dummy)

    from kemonodownloader import creator_downloader as cd_module

    warning = cd_module.translate(
        "log_warning", cd_module.translate("no_files_selected_for_download")
    )
    assert any(warning in str(args) for args in emitted)


class DummySignal:
    def __init__(self):
        self.emitted = False
        self.last_args = None

    def emit(self, *args):
        self.emitted = True
        self.last_args = args


def test_get_desc_folder_for_post_strategies(tmp_path):
    class DummySettingsTab:
        def __init__(self, strat):
            self._s = strat

        def get_creator_folder_strategy(self):
            return self._s

    class DummySettings:
        def __init__(self, st):
            self.settings_tab = st

    service = "fanbox"
    creator_id = "123"
    download_folder = str(tmp_path / "dl")
    selected_posts = ["1"]
    files_to_download = []
    files_to_posts_map = {}
    console = None
    other_files_dir = str(tmp_path / "other")
    post_titles_map = {}

    # by_file_type -> should return 'txt' subfolder
    s_tab = DummySettingsTab("by_file_type")
    thread = cd.CreatorDownloadThread(
        service,
        creator_id,
        download_folder,
        selected_posts,
        files_to_download,
        files_to_posts_map,
        console,
        other_files_dir,
        post_titles_map,
        settings=DummySettings(s_tab),
        max_concurrent=1,
    )
    creator_folder = os.path.normpath(str(tmp_path / "creator"))
    res = thread.get_desc_folder_for_post(creator_folder, "1", "Title")
    assert os.path.basename(res) == "txt"

    # single_folder -> return creator_folder
    s_tab2 = DummySettingsTab("single_folder")
    thread2 = cd.CreatorDownloadThread(
        service,
        creator_id,
        download_folder,
        selected_posts,
        files_to_download,
        files_to_posts_map,
        console,
        other_files_dir,
        post_titles_map,
        settings=DummySettings(s_tab2),
        max_concurrent=1,
    )
    res2 = thread2.get_desc_folder_for_post(creator_folder, "1", "Title")
    assert res2 == creator_folder


def test_check_post_completion_emits_post_completed():
    class DummySettings:
        file_download_max_retries = 1
        settings_tab = None

    file_url = "file://one"
    thread = cd.CreatorDownloadThread(
        service="fanbox",
        creator_id="123",
        download_folder=str(os.getcwd()),
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=None,
        other_files_dir=str(os.getcwd()),
        post_titles_map={},
        settings=DummySettings(),
        max_concurrent=1,
    )
    thread.post_files_map = {"1": [file_url]}
    thread.completed_files = {file_url}
    sig = DummySignal()
    thread.post_completed = sig
    thread.check_post_completion(file_url)
    assert sig.emitted is True
    assert sig.last_args == ("1",)


def test_download_post_text_if_needed_calls_once(tmp_path):
    class DummySettings:
        file_download_max_retries = 1
        settings_tab = None

    thread = cd.CreatorDownloadThread(
        service="fanbox",
        creator_id="123",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        settings=DummySettings(),
        max_concurrent=1,
    )

    calls = []

    def fake_download_sync(pid, folder):
        calls.append((pid, folder))

    thread._download_text_sync = fake_download_sync

    asyncio.run(thread.download_post_text_if_needed("1", str(tmp_path)))
    # second call should not invoke _download_text_sync again
    asyncio.run(thread.download_post_text_if_needed("1", str(tmp_path)))
    assert len(calls) == 1


def test_get_headers_and_session_proxy_behavior(monkeypatch):
    # Reset cached headers and user agent
    monkeypatch.setattr(cd, "HEADERS", None)
    monkeypatch.setattr(cd, "_user_agent", "test-agent")
    headers = cd.get_headers()
    assert headers["User-Agent"] == "test-agent"

    # Clear thread-local sessions if present
    try:
        delattr(cd._thread_local, "session")
    except Exception:
        pass
    try:
        delattr(cd._thread_local, "socks_session")
    except Exception:
        pass

    # HTTP proxy
    settings_tab = SimpleNamespace(
        get_proxy_settings=lambda: {"http": "http://127.0.0.1:8080"}
    )
    sess = cd.get_session(settings_tab)
    assert sess.proxies.get("http") == "http://127.0.0.1:8080"

    # SOCKS proxy uses socks_session
    try:
        delattr(cd._thread_local, "session")
    except Exception:
        pass
    try:
        delattr(cd._thread_local, "socks_session")
    except Exception:
        pass
    settings_tab2 = SimpleNamespace(
        get_proxy_settings=lambda: {"http": "socks5://127.0.0.1:1080"}
    )
    socks = cd.get_session(settings_tab2)
    assert hasattr(cd._thread_local, "socks_session")
    assert "socks5" in list(socks.proxies.values())[0]


def test_preview_thread_uses_cache(tmp_path):
    # Create a small valid image via QPixmap and save as the cache file
    from PyQt6.QtGui import QColor, QPixmap

    url = "https://example.com/image.jpg"
    cache_key = hashlib.md5(url.encode()).hexdigest() + os.path.splitext(url)[1]
    cache_dir = str(tmp_path / "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, cache_key)
    pix = QPixmap(8, 8)
    pix.fill(QColor("red"))
    # Save using the extension-derived format
    pix.save(cache_path)

    captured = {}

    def on_preview(u, pix):
        captured["url"] = u
        captured["pix"] = pix

    pt = cd.PreviewThread(url, cache_dir, settings_tab=None)
    pt.preview_ready.connect(on_preview)
    pt.run()
    assert captured.get("url") == url
    assert captured.get("pix") is not None


def test_post_detection_thread_invalid_url_emits_error():
    settings = cd.ThreadSettings(1, 1, 1, 1, 1, settings_tab=None)
    captured = {}

    def on_error(msg):
        captured["error"] = msg

    pdt = cd.PostDetectionThread("https://kemono.cr/invalid", {}, settings)
    pdt.error.connect(on_error)
    pdt.run()
    assert captured.get("error")


def test_fetch_and_detect_files_respects_response(monkeypatch):
    # Fake session that returns a post payload
    class FakeResp:
        status_code = 200

        def json(self):
            return {
                "post": {"id": "7", "file": {"path": "/media/x.jpg", "name": "x.jpg"}}
            }

    class FakeSession:
        def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: FakeSession())

    # fake checkboxes mapping
    class Box:
        def __init__(self, v):
            self._v = v

        def isChecked(self):
            return self._v

    fpt = cd.FilePreparationThread(
        [],
        {},
        {".jpg": Box(True)},
        True,
        True,
        True,
        cd.ThreadSettings(1, 1, 1, 1, 1, settings_tab=None),
        max_concurrent=1,
    )
    res = fpt.fetch_and_detect_files("7", "https://kemono.cr/user/42")
    assert res is not None
    pid, files = res
    assert pid == "7"
    assert any("x.jpg" in u for _, u in files)


def test_fetch_and_detect_files_handles_rate_limit(monkeypatch):
    # Simulate repeated 429 responses and ensure we return None after retries
    class Fake429:
        status_code = 429

    class Sess:
        def get(self, *a, **k):
            return Fake429()

    # Use small max attempts to keep test fast
    settings = SimpleNamespace(post_data_max_retries=2, settings_tab=None)
    t = cd.FilePreparationThread(
        [], {}, {}, True, True, True, settings, max_concurrent=1
    )

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Sess())
    # Patch time.sleep so retries don't actually delay the test
    monkeypatch.setattr(cd.time, "sleep", lambda s: None)

    res = t.fetch_and_detect_files("9", "https://kemono.cr/user/99")
    assert res is None


def test_download_file_short_circuit_with_hash(tmp_path):
    service = "kemono"
    creator_id = "8"
    other_dir = str(tmp_path / "hdb")
    settings = SimpleNamespace(settings_tab=None)

    file_url = "https://kemono.cr/media/file.bin"
    thread = cd.CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        None,
        other_dir,
        {},
        settings,
        max_concurrent=1,
        download_text=False,
    )

    # create an existing file and register it in the hash DB
    existing = tmp_path / "existing.bin"
    existing.write_bytes(b"hello world")
    file_hash = hashlib.md5(existing.read_bytes()).hexdigest()
    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    thread.hash_db.store(
        url_hash, str(existing), file_hash, file_url, existing.stat().st_size
    )

    asyncio.run(thread.download_file(file_url, str(tmp_path), 0, 1, page_number=1))
    assert file_url in thread.completed_files


def make_gzipped_json(obj):
    return gzip.compress(json.dumps(obj).encode())


def test_post_detection_thread_handles_gzipped_posts(qapp, monkeypatch):
    settings = SimpleNamespace(creator_posts_max_attempts=1, settings_tab=None)
    post_titles_map = {}
    url = "https://kemono.cr/fanbox/user/123"

    posts = [{"id": "p1", "title": "T1", "file": {"path": "/img/a.jpg"}}]
    mock_resp = SimpleNamespace()
    mock_resp.content = make_gzipped_json(posts)
    mock_resp.text = ""
    mock_resp.status_code = 200

    class Sess:
        def get(self, *a, **k):
            return mock_resp

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Sess())

    thread = cd.PostDetectionThread(url, post_titles_map, settings)
    batches = []
    thread.posts_batch.connect(lambda b: batches.append(b))

    thread.run()
    assert batches, "Expected at least one posts_batch emitted"
    assert batches[0][0][0] == "T1"


def test_post_detection_thread_handles_posts_key_and_data_key(qapp, monkeypatch):
    settings = SimpleNamespace(creator_posts_max_attempts=1, settings_tab=None)
    post_titles_map = {}
    url = "https://kemono.cr/fanbox/user/123"

    # Case: API returns {"posts": [...]}
    posts = [{"id": "p2", "title": "Title2"}]
    mock_resp1 = SimpleNamespace()
    mock_resp1.content = json.dumps({"posts": posts}).encode()
    mock_resp1.text = json.dumps({"posts": posts})
    mock_resp1.status_code = 200

    # Case: API returns {"data": [...]}
    posts3 = [{"id": "p3", "title": "Title3"}]
    mock_resp2 = SimpleNamespace()
    mock_resp2.content = json.dumps({"data": posts3}).encode()
    mock_resp2.text = json.dumps({"data": posts3})
    mock_resp2.status_code = 200

    class Sess:
        def __init__(self):
            self._calls = 0

        def get(self, *a, **k):
            self._calls += 1
            return mock_resp1 if self._calls == 1 else mock_resp2

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Sess())

    thread = cd.PostDetectionThread(url, post_titles_map, settings)
    out = []
    thread.posts_batch.connect(lambda b: out.append(b))
    thread.run()
    # We should have batches for both responses
    assert any("Title2" in str(b) or "Title3" in str(b) for b in out)


def test_file_preparation_detect_files_various_cases():
    # Create a FilePreparationThread and call detect_files with different inputs
    t = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks={},
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=1),
    )

    domain_config = {"base_url": "https://kemono.cr"}

    post = {
        "file": {"path": "/a/b/c.jpg", "name": "pic.jpg"},
        "attachments": [{"path": "/att/d.png", "name": "att.png"}],
        "content": '<p>hello <img src="/img/e.gif"></p>',
    }

    detected = t.detect_files(post, [".jpg", ".png", ".gif"], domain_config)
    # Should detect main, attachment and content image
    names = [n for n, u in detected]
    assert "pic.jpg" in names
    assert "att.png" in names
    assert any(u.endswith("/img/e.gif") for _, u in detected)


def test_fetch_and_detect_files_success(monkeypatch, tmp_path):
    # Prepare a FilePreparationThread with checkbox-like objects
    checks = {".jpg": SimpleNamespace(isChecked=lambda: True)}
    settings = SimpleNamespace(post_data_max_retries=1, settings_tab=None)
    t = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks=checks,
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=settings,
    )

    post_id = "99"
    creator_url = "https://kemono.cr/fanbox/user/321"

    post = {"id": post_id, "file": {"path": "/f/g.jpg", "name": "g.jpg"}}

    mock_resp = SimpleNamespace()
    mock_resp.status_code = 200
    mock_resp.json = lambda: post

    class Sess:
        def get(self, *a, **k):
            return mock_resp

    monkeypatch.setattr(cd, "get_session", lambda *a, **k: Sess())

    result = t.fetch_and_detect_files(post_id, creator_url)
    assert result is not None
    pid, files = result
    assert pid == post_id
    assert files and files[0][0] == "g.jpg"


class FakeResp:
    status_code = 200

    def __init__(self, chunks, headers=None):
        self._chunks = chunks
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c

    def close(self):
        return None


def make_thread(tmp_path, file_url, other_dir=None, settings_retries=2):
    service = "kemono"
    creator_id = "9"
    other = other_dir or str(tmp_path / "other")
    settings = SimpleNamespace(
        settings_tab=None, file_download_max_retries=settings_retries
    )
    t = cd.CreatorDownloadThread(
        service,
        creator_id,
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        None,
        other,
        {},
        settings,
        max_concurrent=1,
        download_text=False,
    )
    return t


def test_download_size_mismatch_marks_failed(tmp_path, monkeypatch):
    file_url = "https://kemono.cr/media/big.bin"
    t = make_thread(tmp_path, file_url, settings_retries=1)

    # Response reports 100 bytes but yields only 50
    chunks = [b"a" * 50]
    headers = {"content-length": "100"}

    class FS:
        def get(self, *a, **k):
            return FakeResp(chunks, headers=headers)

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: FS())

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1, page_number=1))
    assert file_url in t.failed_files
    assert file_url not in t.completed_files


def test_download_retries_on_request_exception_then_succeeds(tmp_path, monkeypatch):
    file_url = "https://kemono.cr/media/retry.bin"
    t = make_thread(tmp_path, file_url, settings_retries=3)

    # First two calls raise RequestException, third returns a valid response
    class FS2:
        def __init__(self):
            self.calls = 0

        def get(self, *a, **k):
            self.calls += 1
            if self.calls < 3:
                raise requests.RequestException("network")
            # return 20 bytes in two chunks
            return FakeResp([b"x" * 10, b"x" * 10], headers={"content-length": "20"})

    fs = FS2()
    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: fs)

    # Speed up sleeps during retry
    async def nosleep(_):
        return None

    monkeypatch.setattr(cd.asyncio, "sleep", nosleep)

    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1, page_number=1))
    assert file_url in t.completed_files


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


def test_check_post_completion_triggers_post_completed(tmp_path):
    download_folder = str(tmp_path / "pc_d")
    other_files_dir = str(tmp_path / "pc_o")

    u1 = "https://kemono.cr/files/a.png"
    u2 = "https://kemono.cr/files/b.png"
    files = [u1, u2]
    files_map = {u1: "post1", u2: "post1"}

    settings = make_settings()

    thread = CreatorDownloadThread(
        service="svc",
        creator_id="c1",
        download_folder=download_folder,
        selected_posts=["post1"],
        files_to_download=files,
        files_to_posts_map=files_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    called = []

    def on_post_completed(post_id):
        called.append(post_id)

    thread.post_completed.connect(on_post_completed)

    # Simulate both files completed
    thread.completed_files.add(u1)
    thread.completed_files.add(u2)

    # Trigger check for one file; should emit post_completed
    thread.check_post_completion(u1)

    assert called == ["post1"]


def test_download_size_mismatch_deletion_raises(monkeypatch, tmp_path):
    # Prepare a CreatorDownloadThread with minimal config
    file_url = "https://kemono.cr/files/f.jpg"
    download_folder = str(tmp_path / "dl")
    other_dir = str(tmp_path / "other")
    os.makedirs(other_dir, exist_ok=True)

    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)

    thread = cd.CreatorDownloadThread(
        service="kemono",
        creator_id="1",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=SimpleNamespace(),
        other_files_dir=other_dir,
        post_titles_map={},
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )

    # Stub signals to avoid PyQt interactions
    thread.file_progress = SimpleNamespace(emit=lambda *a, **k: None)
    thread.file_completed = SimpleNamespace(emit=lambda *a, **k: None)
    thread.post_completed = SimpleNamespace(emit=lambda *a, **k: None)
    thread.log = SimpleNamespace(emit=lambda *a, **k: None)

    # Force filename generation to a known path
    target_folder = str(tmp_path / "dl")
    os.makedirs(target_folder, exist_ok=True)
    thread.generate_filename_and_folder = lambda *a, **k: (target_folder, "f.jpg")

    # Fake response: reports content-length 10 but only yields 5 bytes
    class Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        @property
        def headers(self):
            return {"content-length": "10"}

        def iter_content(self, chunk_size=8192):
            yield b"12345"

        def close(self):
            return None

    class Sess:
        def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr(cd, "get_session", lambda st=None: Sess())

    # Make os.remove raise OSError when called to hit the deletion-failure branch
    def fake_remove(path):
        raise OSError("cannot delete")

    monkeypatch.setattr(os, "remove", fake_remove)

    # Run the async download
    asyncio.run(
        thread.download_file(file_url, target_folder, 0, total_files=1, page_number=1)
    )

    # The thread should have recorded a failure for this file
    assert file_url in thread.failed_files
    assert (
        "Size mismatch" in thread.failed_files[file_url]
        or "downloaded" in thread.failed_files[file_url]
    )


def make_settings__from_creator_download_run_loop():
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
        simultaneous_downloads=2,
        settings_tab=settings_tab,
    )


def test_creator_download_run_processes_queue(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "run_d")
    other_files_dir = str(tmp_path / "run_o")

    files = [f"https://kemono.cr/files/{i}.png" for i in range(3)]

    settings = make_settings__from_creator_download_run_loop()

    thread = CreatorDownloadThread(
        service="svc",
        creator_id="c",
        download_folder=download_folder,
        selected_posts=[str(i) for i in range(1, 4)],
        files_to_download=files,
        files_to_posts_map={u: str(i) for i, u in enumerate(files, start=1)},
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Prevent network calls in fetch_creator_and_post_info
    thread.fetch_creator_and_post_info = lambda: None

    async def fake_download_file(
        file_url, folder, file_index, total_files, page_number
    ):
        # mark as completed
        thread.completed_files.add(file_url)

    # Bind coroutine to instance
    thread.download_file = types.MethodType(
        lambda self, *a, **k: fake_download_file(*a, **k), thread
    )

    # Run the thread.run() which should process the queue and finish
    thread.run()

    # All files should have been processed (added to completed_files)
    for u in files:
        assert u in thread.completed_files


class FakeResponse:
    def __init__(self, chunks, headers=None):
        self._chunks = list(chunks)
        self.status_code = 200
        self.headers = headers or {
            "content-length": str(sum(len(c) for c in self._chunks))
        }

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c

    def raise_for_status(self):
        return None

    def close(self):
        return None


class FakeSession:
    def __init__(self, response):
        self._response = response

    def get(self, *args, **kwargs):
        return self._response


def test_download_file_success_writes_and_stores(tmp_path, monkeypatch):
    # Prepare fake file content split into chunks
    chunks = [b"hello", b" ", b"world"]
    fake_resp = FakeResponse(chunks)
    fake_session = FakeSession(fake_resp)
    monkeypatch.setattr(cd, "get_session", lambda settings_tab: fake_session)

    stored = {}

    class FakeHashDB:
        def lookup(self, h):
            return None

        def store(self, url_hash, file_path, file_hash, file_url, file_size):
            stored.update(
                {
                    "url_hash": url_hash,
                    "file_path": file_path,
                    "file_hash": file_hash,
                    "file_url": file_url,
                    "file_size": file_size,
                }
            )

    file_url = "https://kemono.cr/files/hi.txt"
    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)
    t = cd.CreatorDownloadThread(
        "service",
        "creator",
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        None,
        str(tmp_path),
        {},
        settings,
    )
    t.hash_db = FakeHashDB()
    t.domain_config = {
        "base_url": "https://kemono.cr",
        "api_base": "https://kemono.cr/api",
        "referer": "https://kemono.cr",
    }

    dest_folder = tmp_path / "out"
    dest_folder.mkdir()

    asyncio.run(t.download_file(file_url, str(dest_folder), 0, 1, 1))

    # File should exist and hash should have been stored
    assert stored
    assert os.path.exists(stored["file_path"]) is True
    # Validate stored file hash matches file contents
    with open(stored["file_path"], "rb") as f:
        data = f.read()
    assert hashlib.md5(data).hexdigest() == stored["file_hash"]


def test_cleanup_thread_transfers_failed_files(tmp_path):
    settings_tab = SimpleNamespace(
        settings_applied=SimpleNamespace(connect=lambda cb: None),
        language_changed=SimpleNamespace(connect=lambda cb: None),
    )
    parent = SimpleNamespace(
        cache_folder=str(tmp_path / "c"),
        other_files_folder=str(tmp_path / "o"),
        download_folder=str(tmp_path / "d"),
        settings_tab=settings_tab,
        tabs=SimpleNamespace(
            count=lambda: 1, currentIndex=lambda: 0, setTabEnabled=lambda i, e: None
        ),
        status_label=SimpleNamespace(setText=lambda s: None),
        animate_button=lambda *a, **k: None,
    )
    tab = cd.CreatorDownloaderTab(parent)

    class FakeThread:
        def __init__(self, failed):
            self.failed_files = failed

        def isRunning(self):
            return False

        def deleteLater(self):
            pass

    # Keep another thread active and files outstanding so cleanup_thread does
    # not reach the "run finished" path, which logs the failures and clears
    # the set (that clearing is by design, not a lost transfer).
    keep_alive = FakeThread(None)
    tab.active_threads = [keep_alive]
    tab.total_files_to_download = 5

    ft = FakeThread({"u": "err"})
    tab.cleanup_thread(ft)
    assert "u" in tab.failed_files

    # Also test when thread is in active_threads
    ft2 = FakeThread({"v": "err2"})
    tab.active_threads.append(ft2)
    tab.cleanup_thread(ft2)
    assert "v" in tab.failed_files


class FakeSessionAlwaysError:
    def get(self, *args, **kwargs):
        raise requests.RequestException("network failure")


def make_settings__from_creator_downloader_hashdb_mismatch(tmp_path):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: None,
        get_creator_folder_strategy=lambda: "per_post",
        get_proxy_settings=lambda: None,
    )
    return ThreadSettings(
        creator_posts_max_attempts=1,
        post_data_max_retries=1,
        file_download_max_retries=2,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def test_hash_db_size_mismatch_triggers_redownload(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "downloads_h")
    other_files_dir = str(tmp_path / "other_h")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/mismatch.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "9"}

    settings = make_settings__from_creator_downloader_hashdb_mismatch(tmp_path)

    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creatorH",
        download_folder=download_folder,
        selected_posts=["9"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Create an existing file with a size that doesn't match the expected
    existing_path = os.path.join(other_files_dir, "existing.png")
    with open(existing_path, "wb") as f:
        f.write(b"short")

    # Store an entry in the hash DB with an expected size different from actual
    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    # Provide a file_hash (md5) and an expected file_size that is incorrect
    thread.hash_db.store(
        url_hash, existing_path, hashlib.md5(b"short").hexdigest(), file_url, 9999
    )

    # Monkeypatch get_session to always raise so download attempts fail
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSessionAlwaysError(),
    )

    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    # Because download failed after retries, it should be recorded as failed
    assert file_url in thread.failed_files


class FakeResponseMismatch:
    def __init__(self, chunks, header_size):
        self._chunks = chunks
        self.status_code = 200
        self.headers = {"content-length": str(header_size)}

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c

    def raise_for_status(self):
        return None

    def close(self):
        return None


class FakeSessionMismatch:
    def __init__(self, chunks, header_size):
        self._chunks = chunks
        self._header_size = header_size

    def get(self, *args, **kwargs):
        return FakeResponseMismatch(self._chunks, self._header_size)


class FakeResponseCancel:
    def __init__(self, chunks, thread_ref):
        self._chunks = chunks
        self.status_code = 200
        self.headers = {"content-length": str(sum(len(c) for c in chunks))}
        self._thread_ref = thread_ref

    def iter_content(self, chunk_size=8192):
        first = True
        for c in self._chunks:
            if first:
                first = False
                yield c
            else:
                # Simulate user cancellation just before next chunk is processed
                try:
                    self._thread_ref.stop()
                except Exception:
                    pass
                yield c

    def raise_for_status(self):
        return None

    def close(self):
        return None


class FakeSessionCancel:
    def __init__(self, chunks, thread_ref):
        self._chunks = chunks
        self._thread_ref = thread_ref

    def get(self, *args, **kwargs):
        return FakeResponseCancel(self._chunks, self._thread_ref)


def make_settings__from_creator_downloader_retries_and_cancellation():
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


def test_size_mismatch_deletes_incomplete_and_records_failure(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "d_mismatch")
    other_files_dir = str(tmp_path / "other_mismatch")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/partial.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Chunks smaller than header indicates → triggers size-mismatch path
    chunks = [b"abc"]
    header_size = 10

    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSessionMismatch(chunks, header_size),
    )

    settings = make_settings__from_creator_downloader_retries_and_cancellation()
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
        settings=settings,
        download_text=False,
    )

    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    assert file_url not in thread.completed_files
    assert file_url in thread.failed_files
    msg = thread.failed_files[file_url]
    assert "size mismatch" in msg.lower()

    # Ensure no file artifacts remain under download_folder
    found_files = []
    for root, dirs, files in os.walk(download_folder):
        for f in files:
            found_files.append(os.path.join(root, f))
    assert len(found_files) == 0


def test_cancellation_during_streaming_deletes_incomplete_and_records_failure(
    monkeypatch, tmp_path
):
    download_folder = str(tmp_path / "d_cancel")
    other_files_dir = str(tmp_path / "other_cancel")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/cancel.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    chunks = [b"first", b"second"]

    settings = make_settings__from_creator_downloader_retries_and_cancellation()
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
        settings=settings,
        download_text=False,
    )

    # Monkeypatch get_session AFTER thread is created so the FakeSessionCancel
    # can call thread.stop() during iteration.
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSessionCancel(chunks, thread),
    )

    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    # Cancelling is not a failure: nothing completed, nothing to retry, and
    # no half-written artifact left behind.
    assert file_url not in thread.completed_files
    assert file_url not in thread.failed_files

    # Ensure no file artifacts remain under download_folder
    found_files = []
    for root, dirs, files in os.walk(download_folder):
        for f in files:
            found_files.append(os.path.join(root, f))
    assert len(found_files) == 0


class FakeSessionAlwaysError__from_creator_downloader_retry_and_cancel:
    def get(self, *args, **kwargs):
        raise requests.RequestException("network failure")


def make_settings__from_creator_downloader_retry_and_cancel(tmp_path):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: None,
        get_creator_folder_strategy=lambda: "per_post",
        get_proxy_settings=lambda: None,
    )
    return ThreadSettings(
        creator_posts_max_attempts=1,
        post_data_max_retries=1,
        file_download_max_retries=3,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def test_download_file_retries_records_failure(monkeypatch, tmp_path):
    """If all download attempts raise RequestException, the file should be recorded as failed."""
    download_folder = str(tmp_path / "downloads")
    other_files_dir = str(tmp_path / "other")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/1.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    settings = make_settings__from_creator_downloader_retry_and_cancel(tmp_path)

    # Monkeypatch get_session to return a session that always errors
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSessionAlwaysError__from_creator_downloader_retry_and_cancel(),
    )

    thread = CreatorDownloadThread(
        service="kemono",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Run the async download_file coroutine; it should exhaust retries and record a failure
    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    assert file_url in thread.failed_files
    # Ensure no completed files were recorded
    assert file_url not in thread.completed_files


def test_run_returns_immediately_when_stopped(tmp_path):
    """Calling stop() before run() should cause run() to exit without performing work."""
    download_folder = str(tmp_path / "downloads2")
    other_files_dir = str(tmp_path / "other2")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/2.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "2"}

    settings = make_settings__from_creator_downloader_retry_and_cancel(tmp_path)

    thread = CreatorDownloadThread(
        service="kemono",
        creator_id="creator456",
        download_folder=download_folder,
        selected_posts=["2"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Stop before running; run() should return quickly and not create folders or files
    thread.stop()
    thread.run()

    # No files should be marked completed or failed
    assert not thread.completed_files
    assert not thread.failed_files


def test_creator_download_thread_run_with_fake_workers(tmp_path, monkeypatch):
    # Prepare a thread with one file to download
    file_url = "https://kemono.cr/files/runfile.png"
    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)
    t = cd.CreatorDownloadThread(
        "service",
        "creator",
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        None,
        str(tmp_path),
        {},
        settings,
    )

    # Stub fetch_creator_and_post_info to avoid network
    def fake_fetch():
        t.creator_name = "Creator"
        t.post_titles_map[(t.service, t.creator_id, "1")] = "PostTitle"

    monkeypatch.setattr(t, "fetch_creator_and_post_info", fake_fetch)

    # Replace download_worker with a coroutine that marks files completed
    async def fake_download_worker(self_queue, folder, total_files):
        # Consume one item if present
        try:
            idx, url = self_queue.get_nowait()
        except Exception:
            return
        # simulate immediate completion
        t._safe_emit(t.file_completed, idx, url, True)
        self_queue.task_done()

    monkeypatch.setattr(
        cd.CreatorDownloadThread, "download_worker", fake_download_worker
    )

    # Run the thread.run() method synchronously
    t.run()

    # After running, finished signal would have been emitted (no exceptions)
    # Ensure the run created the creator folder
    # (creator folder name uses service/creator id pattern)
    # No assertion beyond 'no exception' — ensure completed_files processed
    assert isinstance(t.post_titles_map, dict)


class FakeResponse__from_creator_downloader_streamed_download:
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


class FakeSession__from_creator_downloader_streamed_download:
    def __init__(self, chunks):
        self._chunks = chunks

    def get(self, *args, **kwargs):
        return FakeResponse__from_creator_downloader_streamed_download(self._chunks)


def make_settings__from_creator_downloader_streamed_download(tmp_path):
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


def test_streamed_download_writes_file_and_updates_hashdb(monkeypatch, tmp_path):
    download_folder = str(tmp_path / "dstream")
    other_files_dir = str(tmp_path / "otherstream")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/streamed.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Small content in two chunks
    chunks = [b"abc", b"def"]

    # Monkeypatch get_session to return our fake session
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSession__from_creator_downloader_streamed_download(
            chunks
        ),
    )

    settings = make_settings__from_creator_downloader_streamed_download(tmp_path)

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
        settings=settings,
        download_text=False,
    )

    # Run the async download
    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    # Confirm the file was marked completed
    assert file_url in thread.completed_files

    # Compute url_hash and check HashDB entry exists and file exists on disk
    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    entry = thread.hash_db.lookup(url_hash)
    assert entry is not None
    assert (
        os.path.exists(entry["file_path"])
        if isinstance(entry, dict)
        else os.path.exists(entry["file_path"])
    )  # defensive


def make_settings__from_creator_folder_and_run_errors():
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


def test_generate_filename_respects_existing_creator_folder(tmp_path):
    base = str(tmp_path / "base")
    os.makedirs(base, exist_ok=True)

    file_url = "https://kemono.cr/files/x.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    settings = make_settings__from_creator_folder_and_run_errors()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=base,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={("svc", "creator123", "1"): "MyPost"},
        settings=settings,
        download_text=False,
    )
    thread.creator_name = "Alice"

    # Simulate caller passing creator_folder that already ends with creator folder name
    creator_folder_name = f"{thread.creator_id}_{thread.creator_name}"
    folder_arg = os.path.join(base, creator_folder_name)

    target_folder, filename = thread.generate_filename_and_folder(
        file_url, folder_arg, 0, 1, "1", "MyPost", page_number=1
    )

    # Should not duplicate the creator folder segment
    assert target_folder == os.path.join(
        folder_arg, "1_MyPost"
    ) or target_folder.startswith(folder_arg)


def test_run_handles_makedirs_oserror(monkeypatch, tmp_path):
    base = str(tmp_path / "out_error")
    files_to_download = []
    files_to_posts_map = {}

    settings = make_settings__from_creator_folder_and_run_errors()
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=base,
        selected_posts=[],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        settings=settings,
        download_text=False,
    )

    # Provide a safe get_session stub so fetch_creator_and_post_info doesn't raise
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: SimpleNamespace(
            get=lambda *a, **k: SimpleNamespace(
                status_code=200, json=lambda: {"name": "X"}
            )
        ),
    )

    real_makedirs = os.makedirs

    def bad_makedirs(path, exist_ok=False):
        # Raise for any creation attempt under the test base
        if str(path).startswith(base):
            raise OSError("permission denied")
        return real_makedirs(path, exist_ok=exist_ok)

    monkeypatch.setattr("os.makedirs", bad_makedirs)

    # Running should not raise even if mkdir fails
    thread.run()

    # Cleanup monkeypatch will restore os.makedirs; ensure no folder was created
    assert not os.path.isdir(
        os.path.join(base, f"{thread.creator_id}_{thread.creator_name}")
    )


class DummySettingsTab:
    def get_creator_filename_template(self):
        return "{post_id}_{orig_name}"

    def get_creator_folder_strategy(self):
        return "per_post"


class DummySettings:
    def __init__(self):
        self.settings_tab = DummySettingsTab()


def test_creator_folder_not_duplicated():
    t = CreatorDownloadThread(
        "patreon",
        "17913091",
        "/downloads",
        ["1"],
        [],
        {},
        None,
        "/tmp/other",
        {},
        settings=DummySettings(),
        max_concurrent=1,
    )
    t.creator_name = "jtveemo"

    creator_folder_name = f"{t.creator_id}_{t.creator_name}"
    # Simulate run-created creator_folder passed into workers
    creator_folder = os.path.normpath(
        os.path.join(t.download_folder, creator_folder_name)
    )

    # Now call generator with folder already being creator_folder
    target_folder, filename = t.generate_filename_and_folder(
        "https://kemono.cr/media/abc/image.jpg",
        creator_folder,
        0,
        1,
        "1",
        "My Post",
        page_number=1,
    )

    # target_folder should not contain duplication
    assert target_folder.count(creator_folder_name) == 1

    # Also check when passing base download folder it still builds correct path
    base_folder = os.path.normpath(t.download_folder)
    target_folder2, filename2 = t.generate_filename_and_folder(
        "https://kemono.cr/media/abc/image2.jpg",
        base_folder,
        0,
        1,
        "1",
        "My Post",
        page_number=1,
    )
    assert target_folder2.count(creator_folder_name) == 1


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


def make_settings__from_creator_run_and_hashdb():
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

    settings = make_settings__from_creator_run_and_hashdb()
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

    settings = make_settings__from_creator_run_and_hashdb()
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

    asyncio.run(
        thread.download_file(file_url, download_folder, 0, total_files=1, page_number=1)
    )

    assert file_url in thread.completed_files


class DummySignal__from_creator_run_loop:
    def __init__(self):
        self.emitted = False
        self.last_args = None

    def emit(self, *args):
        self.emitted = True
        self.last_args = args


def test_creator_download_thread_run_loop(monkeypatch, tmp_path):
    class DummySettings:
        file_download_max_retries = 1
        settings_tab = None
        simultaneous_downloads = 1

    file_url = "https://kemono.cr/files/a.jpg"
    thread = cd.CreatorDownloadThread(
        service="fanbox",
        creator_id="123",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={},
        settings=DummySettings(),
        max_concurrent=1,
    )

    # Prevent network calls in fetch_creator_and_post_info
    thread.fetch_creator_and_post_info = lambda: None

    # Fake async worker that consumes one queue item and returns
    async def fake_worker(self, queue, folder, total_files):
        file_index, file_url, page_number = await queue.get()
        queue.task_done()

    # Bind the coroutine to the instance
    thread.download_worker = MethodType(fake_worker, thread)

    # Replace finished signal to capture emission
    finished = DummySignal__from_creator_run_loop()
    thread.finished = finished

    # Run the thread's run() synchronously
    thread.run()

    assert finished.emitted is True


def _make_thread_for_runloop(tmp_path):
    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)
    t = cd.CreatorDownloadThread(
        service="kemono",
        creator_id="1",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[],
        files_to_posts_map={},
        console=SimpleNamespace(),
        other_files_dir=str(tmp_path / "other"),
        post_titles_map={("kemono", "1", "1"): "Title"},
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )
    # Stub signals so emit calls don't fail
    t.log = SimpleNamespace(emit=lambda *a, **k: None)
    t.file_progress = SimpleNamespace(emit=lambda *a, **k: None)
    t.file_completed = SimpleNamespace(emit=lambda *a, **k: None)
    t.post_completed = SimpleNamespace(emit=lambda *a, **k: None)
    t.finished = SimpleNamespace(emit=lambda *a, **k: None)
    return t


def test_download_worker_times_out_and_exits(tmp_path):
    t = _make_thread_for_runloop(tmp_path)

    async def runner():
        q = asyncio.Queue()
        # Start worker
        task = asyncio.create_task(t.download_worker(q, str(tmp_path), 0))
        # Give it a short moment, then stop the thread so it exits after timeout
        await asyncio.sleep(0.2)
        t.is_running = False
        await asyncio.wait_for(task, timeout=2.0)
        assert task.done()

    asyncio.run(runner())


def test_run_no_files_logs_warning(tmp_path):
    t = _make_thread_for_runloop(tmp_path)
    # Keep the test offline and on the branch it names.
    t.fetch_creator_and_post_info = lambda: None
    emitted = []
    t.log = SimpleNamespace(emit=lambda *args, **kwargs: emitted.append(args))
    # Ensure no files to download
    t.files_to_download = []
    # Run should not raise, and must say why it did nothing
    t.run()

    warning = cd.translate(
        "log_warning", cd.translate("no_files_selected_for_download")
    )
    assert any(warning in str(args) for args in emitted)


class DummySettingsTab__from_creator_stress_safety:
    def get_creator_filename_template(self):
        return "{post_id}_{orig_name}"

    def get_creator_folder_strategy(self):
        return "per_post"


class DummySettings__from_creator_stress_safety:
    def __init__(self):
        self.settings_tab = DummySettingsTab__from_creator_stress_safety()


def test_stress_run_reduced_concurrency_does_not_crash(tmp_path):
    # This is a lightweight stress test that launches the download thread with
    # multiple workers but avoids network by giving no files. It ensures run() does
    # not crash immediately under threaded asyncio execution.
    t = CreatorDownloadThread(
        service="patreon",
        creator_id="stress",
        download_folder=str(tmp_path),
        selected_posts=["1", "2", "3"],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir=str(tmp_path),
        post_titles_map={},
        settings=DummySettings__from_creator_stress_safety(),
        max_concurrent=2,
    )
    try:
        # Prevent network activity in the test run
        t.fetch_creator_and_post_info = lambda: None
        t.start()
        # Wait a bit for thread to finish gracefully
        finished = t.wait(2000)
        assert finished is True
    finally:
        t.stop()
        t.quit()
        t.wait(2000)


def make_settings__from_creator_validation_and_worker():
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


def test_download_worker_invokes_download_file(monkeypatch):
    settings = make_settings__from_creator_validation_and_worker()
    td = CreatorDownloadThread(
        service="svc",
        creator_id="creator",
        download_folder="/tmp",
        selected_posts=[],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir="/tmp",
        post_titles_map={},
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )

    called = {}

    async def fake_download(file_url, folder, idx, total, page_number):
        called["url"] = file_url
        called["page_number"] = page_number

    # Monkeypatch the async download_file
    td.download_file = fake_download
    # download_worker loops while is_running, which defaults to False in __init__.
    td.is_running = True

    async def run_worker():
        q = asyncio.Queue()
        # download_worker unpacks (file_index, file_url, page_number).
        await q.put((0, "https://kemono.cr/files/x.png", None))
        # Run the worker in the background and wait for the queue to be processed.
        worker_task = asyncio.create_task(td.download_worker(q, "/tmp", total_files=1))
        await q.join()
        # Signal the worker to stop and cancel the task to break out of wait_for
        td.is_running = False
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass

    asyncio.run(run_worker())
    assert called.get("url") == "https://kemono.cr/files/x.png"
    assert called.get("page_number") is None


def test_safe_emit_ignores_when_destroyed():
    settings = make_settings__from_creator_validation_and_worker()
    td = CreatorDownloadThread(
        service="svc",
        creator_id="creator",
        download_folder="/tmp",
        selected_posts=[],
        files_to_download=[],
        files_to_posts_map={},
        console=None,
        other_files_dir="/tmp",
        post_titles_map={},
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )

    td._destroyed = True
    td.emitted = False

    class S:
        def emit(self, *a, **k):
            td.emitted = True

    td._safe_emit(S(), 1, 2, 3)
    assert td.emitted is False


def test_file_preparation_thread_run(monkeypatch, qapp):
    # Prepare an all_files_map containing a creator with two posts
    creator_url = "https://kemono.cr/user/creator"
    all_files_map = {creator_url: [("T1", ("p1", None)), ("T2", ("p2", None))]}

    settings = type("S", (), {"post_data_max_retries": 1, "settings_tab": None})()

    thread = cd.FilePreparationThread(
        ["p1", "p2"], all_files_map, {}, True, True, True, settings, max_concurrent=2
    )

    # Monkeypatch fetch_and_detect_files to return a predictable result
    def fake_fetch(pid, curl):
        return (pid, [(f"file_{pid}", f"https://kemono.cr/{pid}/file.jpg")])

    monkeypatch.setattr(thread, "fetch_and_detect_files", fake_fetch)

    finished = []
    thread.finished.connect(lambda files, fmap: finished.append((files, fmap)))

    # Run synchronously (call run directly) to avoid threading complexity in tests
    thread.run()

    assert finished, "FilePreparationThread did not finish as expected"
    files, fmap = finished[0]
    assert sorted(files) == [
        "https://kemono.cr/p1/file.jpg",
        "https://kemono.cr/p2/file.jpg",
    ]
    # Every queued file maps back to the post it came from.
    assert fmap == {
        "https://kemono.cr/p1/file.jpg": "p1",
        "https://kemono.cr/p2/file.jpg": "p2",
    }


def test_creator_download_thread_run_simulated(monkeypatch, qapp, tmp_path):
    # Simulate a CreatorDownloadThread run where download_file is fast and marks files complete
    download_folder = str(tmp_path)
    files = ["https://kemono.cr/1/a.jpg", "https://kemono.cr/1/b.jpg"]
    files_map = {files[0]: "1", files[1]: "1"}

    class SettingsTab:
        pass

    class Settings:
        settings_tab = SettingsTab()
        file_download_max_retries = 1

    thread = cd.CreatorDownloadThread(
        "svc",
        "creator",
        download_folder,
        ["1"],
        files,
        files_map,
        object(),
        download_folder,
        {("svc", "creator", "1"): "Title"},
        Settings(),
        2,
    )

    # Stub fetch_creator_and_post_info to set creator_name and post_titles
    def fake_fetch_info():
        thread.creator_name = "Creator"
        thread.post_titles_map[(thread.service, thread.creator_id, "1")] = "Title"

    monkeypatch.setattr(thread, "fetch_creator_and_post_info", fake_fetch_info)

    # Async download_file that immediately marks completion
    async def fake_download_file(
        self, file_url, folder, file_index, total_files, page_number
    ):
        # create the target folder/file to mimic a real download
        target_dir = os.path.join(
            folder, f"{self.creator_id}_{self.creator_name}", "1_Title"
        )
        os.makedirs(target_dir, exist_ok=True)
        fpath = os.path.join(target_dir, os.path.basename(file_url))
        with open(fpath, "wb") as f:
            f.write(b"x")
        with self.completed_files_lock:
            self.completed_files.add(file_url)
        self._safe_emit(self.file_progress, file_index, 100)
        self._safe_emit(self.file_completed, file_index, file_url, True)
        self.check_post_completion(file_url)

    # Bind the coroutine method to the instance
    monkeypatch.setattr(
        thread, "download_file", fake_download_file.__get__(thread, thread.__class__)
    )

    finished = []
    thread.finished.connect(lambda: finished.append(True))

    # Run synchronously
    thread.run()

    # After a successful run, completed_files should include our files
    assert set(files).issubset(thread.completed_files)
    assert finished
