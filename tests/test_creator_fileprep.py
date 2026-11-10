from types import SimpleNamespace

import kemonodownloader.creator_downloader as cd


def _mk_checkbox(checked=True):
    return SimpleNamespace(isChecked=lambda: checked)


def test_detect_files_main_attachment_content(qapp):
    thread = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks={},
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=1, settings_tab=None),
    )

    post = {
        "id": "p1",
        "title": "Title",
        "file": {"path": "/media/1.png", "name": "img1.png"},
        "attachments": [{"path": "/att/2.zip", "name": "file2.zip"}],
        "content": "<p><img src='/content/3.jpg'/></p>",
    }
    domain_config = {
        "base_url": "https://kemono.cr",
        "referer": "https://kemono.cr/",
        "api_base": "https://kemono.cr/api/v1",
        "domain": "kemono.cr",
    }

    allowed = [".png", ".jpg", ".zip"]
    files = thread.detect_files(post, allowed, domain_config)

    assert ("img1.png", "https://kemono.cr/media/1.png?f=img1.png") in files
    assert ("file2.zip", "https://kemono.cr/att/2.zip?f=file2.zip") in files
    assert ("3.jpg", "https://kemono.cr/content/3.jpg") in files


def test_detect_files_counts_skips_per_keyword(qapp):
    thread = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks={},
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=1, settings_tab=None),
        file_skip_keywords=["JP", "ZH"],
    )
    post = {
        "id": "p1",
        "file": {"path": "/m/1_JP.png", "name": "1_JP.png"},
        "attachments": [
            {"path": "/a/2_JP.jpg", "name": "2_JP.jpg"},
            {"path": "/a/3_ZH.jpg", "name": "3_ZH.jpg"},
        ],
        "content": "<p><img src='/c/4_JP.gif'/></p>",
    }
    domain_config = {
        "base_url": "https://kemono.cr",
        "referer": "https://kemono.cr/",
        "api_base": "https://kemono.cr/api/v1",
        "domain": "kemono.cr",
    }

    files = thread.detect_files(post, [".png", ".jpg", ".gif"], domain_config)

    assert files == []
    assert thread._files_skipped_count == 4
    assert thread._file_skip_counts == {"JP": 3, "ZH": 1}


def test_fetch_and_detect_files_success(monkeypatch, qapp):
    # Create a FilePreparationThread with a single extension enabled
    creator_ext_checks = {".png": _mk_checkbox(True)}
    thread = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks=creator_ext_checks,
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=1, settings_tab=None),
    )

    # Mock session responses
    class Resp:
        status_code = 200

        def json(self):
            return {
                "id": "p1",
                "title": "T",
                "file": {"path": "/media/1.png", "name": "img1.png"},
            }

    class S:
        def get(self, url, headers=None, **kwargs):
            return Resp()

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    result = thread.fetch_and_detect_files("p1", "https://kemono.cr/artist/user/10")
    assert result is not None
    pid, files = result
    assert pid == "p1"
    assert any("img1.png" in fn for fn, _ in files)


def test_fetch_and_detect_files_429_retry(monkeypatch, qapp):
    # Ensure we don't actually sleep during retries
    monkeypatch.setattr(cd, "time", SimpleNamespace(sleep=lambda *_: None))

    creator_ext_checks = {".png": _mk_checkbox(True)}
    thread = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks=creator_ext_checks,
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=2, settings_tab=None),
    )

    # First response 429, then 200
    class Resp429:
        status_code = 429

    class Resp200:
        status_code = 200

        def json(self):
            return {"id": "p1", "file": {"path": "/media/1.png", "name": "img1.png"}}

    calls = {"i": 0}

    class S:
        def get(self, url, headers=None, **kwargs):
            calls["i"] += 1
            return Resp429() if calls["i"] == 1 else Resp200()

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    res = thread.fetch_and_detect_files("p1", "https://kemono.cr/artist/user/10")
    assert res is not None and res[0] == "p1"


def test_fetch_and_detect_files_retries_a_server_error(monkeypatch, qapp):
    """A 5xx is transient, so it gets the retry budget a 4xx does not."""
    monkeypatch.setattr(cd, "time", SimpleNamespace(sleep=lambda *_: None))

    thread = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks={".png": _mk_checkbox(True)},
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=2, settings_tab=None),
    )

    class Resp503:
        status_code = 503

    class Resp200:
        status_code = 200

        def json(self):
            return {"id": "p1", "file": {"path": "/media/1.png", "name": "img1.png"}}

    calls = {"i": 0}
    seen_kwargs = {}

    class S:
        def get(self, url, headers=None, **kwargs):
            calls["i"] += 1
            seen_kwargs.update(kwargs)
            return Resp503() if calls["i"] == 1 else Resp200()

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    res = thread.fetch_and_detect_files("p1", "https://kemono.cr/artist/user/10")

    assert calls["i"] == 2
    assert res is not None and res[0] == "p1"
    # A stalled connection used to hang the worker until the deadline.
    assert seen_kwargs.get("timeout") == (15, 30)


def test_fetch_and_detect_files_does_not_retry_a_404(monkeypatch, qapp):
    monkeypatch.setattr(cd, "time", SimpleNamespace(sleep=lambda *_: None))

    thread = cd.FilePreparationThread(
        post_ids=[],
        all_files_map={},
        creator_ext_checks={".png": _mk_checkbox(True)},
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=3, settings_tab=None),
    )

    class Resp404:
        status_code = 404

    calls = {"i": 0}

    class S:
        def get(self, url, headers=None, **kwargs):
            calls["i"] += 1
            return Resp404()

    monkeypatch.setattr(cd, "get_session", lambda st: S())

    assert (
        thread.fetch_and_detect_files("p1", "https://kemono.cr/artist/user/10") is None
    )
    assert calls["i"] == 1


def test_preparation_warns_when_the_deadline_drops_work(monkeypatch, qapp):
    """Files a straggler was about to queue used to vanish without a word."""
    import itertools
    import threading

    release = threading.Event()
    creator_url = "https://kemono.cr/artist/user/1"
    thread = cd.FilePreparationThread(
        ["1"],
        {creator_url: [("T", ("1", None))]},
        {".png": _mk_checkbox(True)},
        creator_main_check=True,
        creator_attachments_check=True,
        creator_content_check=True,
        settings=SimpleNamespace(post_data_max_retries=1, settings_tab=None),
    )
    thread.fetch_and_detect_files = lambda pid, curl: release.wait(5) or (
        pid,
        [("a.png", "https://n1.kemono.cr/a.png")],
    )
    logs = []
    thread.log = SimpleNamespace(
        emit=lambda message, level: logs.append((message, level))
    )
    thread.finished = SimpleNamespace(emit=lambda *a, **k: None)
    thread.progress = SimpleNamespace(emit=lambda *a, **k: None)

    # Walk the clock past the 30 s deadline without waiting for it.
    ticks = itertools.count(0, 100)
    monkeypatch.setattr(
        cd,
        "time",
        SimpleNamespace(monotonic=lambda: next(ticks), sleep=lambda *_: None),
    )

    try:
        thread.run()
    finally:
        release.set()

    assert any(
        level == "WARNING" and "timed out" in message.lower() for message, level in logs
    )
