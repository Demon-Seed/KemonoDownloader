"""Preview requests against DDoS-Guard fronted file hosts.

Pawchive serves files from ``file.pawchive.<suffix>`` behind DDoS-Guard,
which answers hotlink/bot shaped requests with "Are you a bot or using
download tools?" (403).  The download path already shaped its headers for
that host and warmed it once per session; the double-click preview must do
the same, and must report the URL and the reason when it still fails.
"""

import os
from types import SimpleNamespace

import requests
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QWidget

from kemonodownloader import creator_downloader as cd
from kemonodownloader import post_downloader as pd
from kemonodownloader.domain_config import file_host_headers, warm_file_host

PAWCHIVE_IMAGE = (
    "https://file.pawchive.pw/data/38/b5/"
    "38b57b9e39962a237024f14cc5f9e8d992da4bb937f604b3456c54df04a172b9.png"
)

PAWCHIVE_CONFIG = {
    "domain": "pawchive.pw",
    "base_url": "https://pawchive.pw",
    "api_base": "https://pawchive.pw/api/v1",
    "referer": "https://pawchive.pw/",
    "file_base_url": "https://file.pawchive.pw",
}

KEMONO_CONFIG = {
    "domain": "kemono.cr",
    "base_url": "https://kemono.cr",
    "api_base": "https://kemono.cr/api/v1",
    "referer": "https://kemono.cr/",
    "file_base_url": "https://kemono.cr",
}


def png_bytes():
    """A tiny valid PNG so QPixmap.loadFromData succeeds."""
    from PyQt6.QtCore import QBuffer, QIODevice

    pixmap = QPixmap(1, 1)
    pixmap.fill()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


class FakeResponse:
    def __init__(self, status_code=200, chunks=()):
        self.status_code = status_code
        self.headers = {"content-length": str(sum(len(c) for c in chunks))}
        self._chunks = list(chunks)
        self.closed = False

    def iter_content(self, chunk_size=8192):
        for chunk in self._chunks:
            yield chunk

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("%d Client Error" % self.status_code)

    def close(self):
        self.closed = True


class ScriptedSession:
    """Hands out the scripted responses in order, recording each request."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests = []

    def get(self, url, headers=None, stream=None, timeout=None):
        self.requests.append((url, headers))
        if not self._responses:
            raise AssertionError("unexpected extra request for " + url)
        return self._responses.pop(0)

    @property
    def urls(self):
        return [url for url, _headers in self.requests]


def test_file_host_headers_target_the_file_host():
    headers, file_base_url = file_host_headers(
        PAWCHIVE_IMAGE,
        {
            "User-Agent": "ua",
            "Referer": "https://kemono.cr/",
            "Accept": "text/css",
        },
        PAWCHIVE_CONFIG,
    )

    assert file_base_url == "https://file.pawchive.pw"
    assert headers["Referer"] == "https://file.pawchive.pw/"
    assert headers["Origin"] == "https://pawchive.pw"
    assert headers["Accept"] == "*/*"
    assert headers["Sec-Fetch-Dest"] == "empty"
    assert headers["Sec-Fetch-Mode"] == "cors"
    assert headers["Sec-Fetch-Site"] == "same-site"
    assert headers["User-Agent"] == "ua"


def test_file_host_headers_do_not_mutate_the_base_headers():
    base = {"User-Agent": "ua", "Referer": "https://kemono.cr/"}

    file_host_headers(PAWCHIVE_IMAGE, base, PAWCHIVE_CONFIG)

    assert base == {"User-Agent": "ua", "Referer": "https://kemono.cr/"}


def test_file_host_headers_keep_kemono_on_its_own_host():
    headers, file_base_url = file_host_headers(
        "https://kemono.cr/data/ab/cd/photo.png", {"User-Agent": "ua"}, KEMONO_CONFIG
    )

    assert file_base_url == "https://kemono.cr"
    assert headers["Referer"] == "https://kemono.cr/"
    assert headers["Accept"] == "*/*"


def test_warm_file_host_requests_the_host_root():
    session = ScriptedSession(FakeResponse(404))

    warmed = warm_file_host(
        session, "https://file.pawchive.pw/", "ua", "https://pawchive.pw/"
    )

    assert warmed is True
    assert session.urls == ["https://file.pawchive.pw/"]
    _url, headers = session.requests[0]
    assert headers["User-Agent"] == "ua"
    assert headers["Referer"] == "https://pawchive.pw/"


def test_warm_file_host_is_best_effort():
    class BrokenSession:
        def get(self, *args, **kwargs):
            raise requests.RequestException("no route to host")

    assert warm_file_host(BrokenSession(), "https://file.pawchive.pw", "ua") is False
    assert warm_file_host(ScriptedSession(), "", "ua") is False


def test_creator_preview_retries_after_ddos_guard_challenge(qtbot, tmp_path, monkeypatch):
    session = ScriptedSession(
        FakeResponse(403),
        FakeResponse(404),
        FakeResponse(200, [png_bytes()]),
    )
    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: session)
    monkeypatch.setattr(cd, "get_domain_config", lambda url: dict(PAWCHIVE_CONFIG))

    previews = []
    errors = []
    cache_dir = os.path.join(str(tmp_path), "cache")
    thread = cd.PreviewThread(PAWCHIVE_IMAGE, cache_dir, settings_tab=None)
    thread.preview_ready.connect(lambda url, pixmap: previews.append((url, pixmap)))
    thread.error.connect(errors.append)

    thread.run()

    assert session.urls == [
        PAWCHIVE_IMAGE,
        "https://file.pawchive.pw/",
        PAWCHIVE_IMAGE,
    ]
    assert errors == []
    assert previews and previews[0][0] == PAWCHIVE_IMAGE
    assert isinstance(previews[0][1], QPixmap)
    file_headers = session.requests[0][1]
    assert file_headers["Referer"] == "https://file.pawchive.pw/"
    assert file_headers["Accept"] == "*/*"


def test_creator_preview_reports_the_url_and_reason(qtbot, tmp_path, monkeypatch):
    class FailingSession:
        def get(self, *args, **kwargs):
            raise requests.RequestException("403 Client Error: Forbidden")

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: FailingSession())
    monkeypatch.setattr(cd, "get_domain_config", lambda url: dict(PAWCHIVE_CONFIG))

    errors = []
    thread = cd.PreviewThread(
        PAWCHIVE_IMAGE, os.path.join(str(tmp_path), "cache"), settings_tab=None
    )
    thread.error.connect(errors.append)

    thread.run()

    assert len(errors) == 1
    assert PAWCHIVE_IMAGE in errors[0]
    assert "Forbidden" in errors[0]


def test_kemono_preview_still_makes_a_single_request(qtbot, tmp_path, monkeypatch):
    url = "https://kemono.cr/data/ab/cd/photo.png"
    session = ScriptedSession(FakeResponse(200, [png_bytes()]))
    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: session)
    monkeypatch.setattr(cd, "get_domain_config", lambda url: dict(KEMONO_CONFIG))

    thread = cd.PreviewThread(url, os.path.join(str(tmp_path), "cache"), settings_tab=None)
    thread.run()

    assert session.urls == [url]
    assert session.requests[0][1]["Referer"] == "https://kemono.cr/"


def test_post_preview_retries_after_ddos_guard_challenge(qtbot, tmp_path, monkeypatch):
    session = ScriptedSession(
        FakeResponse(403),
        FakeResponse(404),
        FakeResponse(200, [png_bytes()]),
    )
    monkeypatch.setattr(pd, "get_session", lambda settings_tab=None: session)
    monkeypatch.setattr(pd, "get_domain_config", lambda url: dict(PAWCHIVE_CONFIG))

    previews = []
    thread = pd.PreviewThread(
        PAWCHIVE_IMAGE, os.path.join(str(tmp_path), "cache"), settings_tab=None
    )
    thread.preview_ready.connect(lambda url, pixmap: previews.append(pixmap))

    thread.run()

    assert session.urls == [
        PAWCHIVE_IMAGE,
        "https://file.pawchive.pw/",
        PAWCHIVE_IMAGE,
    ]
    assert previews


def test_image_modal_uses_the_tabs_settings_tab(qtbot, tmp_path, monkeypatch):
    captured = {}

    class FakeSignal:
        def connect(self, slot):
            return None

    class FakePreviewThread:
        def __init__(self, url, cache_dir, settings_tab=None):
            captured["settings_tab"] = settings_tab
            self.preview_ready = FakeSignal()
            self.progress = FakeSignal()
            self.error = FakeSignal()
            self.finished = FakeSignal()

        def start(self):
            captured["started"] = True

        def deleteLater(self):
            return None

    monkeypatch.setattr(cd, "PreviewThread", FakePreviewThread)

    settings_tab = object()
    owner = SimpleNamespace(settings_tab=settings_tab)
    tab = QWidget()
    tab._parent = owner

    cd.ImageModal("https://kemono.cr/data/ab/cd/photo.png", str(tmp_path), tab)

    assert captured["settings_tab"] is settings_tab
    assert captured["started"] is True
