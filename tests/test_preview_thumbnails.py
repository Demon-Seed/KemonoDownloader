"""Thumbnail-first previews: URL mapping, the modal flow, and no thumbnail cache."""

import os

import pytest
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage, QImageReader, QPixmap
from PyQt6.QtWidgets import QMessageBox

from kemonodownloader import (
    creator_downloader as cd,
    domain_config as dc,
    preview_cache as pc,
)
from kemonodownloader.kd_language import translate

PAWCHIVE_URL = (
    "https://file.pawchive.pw/data/59/97/"
    "599724125fe7e925620a2138882753a90ab9f4ae56713bd859f0f90b613b345a.png"
)
PAWCHIVE_THUMB = PAWCHIVE_URL.replace(
    "https://file.pawchive.pw/data/", "https://img.pawchive.pw/thumbnail/data/"
)
KEMONO_URL = "https://kemono.cr/data/ab/cd/photo.png"

PAWCHIVE_CONFIG = {
    "domain": "pawchive.pw",
    "base_url": "https://pawchive.pw",
    "api_base": "https://pawchive.pw/api/v1",
    "referer": "https://pawchive.pw/",
    "file_base_url": "https://file.pawchive.pw",
    "thumbnail_base_url": "https://img.pawchive.pw/thumbnail",
}


def test_pawchive_config_gets_a_thumbnail_host(monkeypatch):
    monkeypatch.setattr(
        dc, "get_domains", lambda: ["kemono.cr", "coomer.st", "pawchive.pw"]
    )

    assert dc.get_domain_config(PAWCHIVE_URL)["thumbnail_base_url"] == (
        "https://img.pawchive.pw/thumbnail"
    )
    assert dc.get_domain_config(KEMONO_URL)["thumbnail_base_url"] == ""


def test_preview_thumbnail_url_reuses_the_file_path():
    thumbnail = dc.preview_thumbnail_url(PAWCHIVE_URL, PAWCHIVE_CONFIG)

    assert thumbnail == PAWCHIVE_THUMB


def test_preview_thumbnail_url_is_empty_without_a_thumbnail_host():
    config = dict(PAWCHIVE_CONFIG)
    config["thumbnail_base_url"] = ""

    assert dc.preview_thumbnail_url(PAWCHIVE_URL, config) == ""
    assert dc.preview_thumbnail_url(KEMONO_URL, {"domain": "kemono.cr"}) == ""


def test_preview_thumbnail_url_requires_a_data_path():
    assert (
        dc.preview_thumbnail_url(
            "https://file.pawchive.pw/59/97/photo.png", PAWCHIVE_CONFIG
        )
        == ""
    )


def test_load_full_image_strings_are_translated():
    assert translate("load_full_image") == "Load Full Image"
    assert translate("loading_full_image") == "Loading Full Image..."


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class FakePreviewThread:
    """A PreviewThread that starts nothing so the test drives its signals."""

    instances = []

    def __init__(self, url, cache_dir, settings_tab=None, cache=True):
        self.url = url
        self.cache_dir = cache_dir
        self.settings_tab = settings_tab
        self.cache = cache
        self.preview_ready = FakeSignal()
        self.progress = FakeSignal()
        self.error = FakeSignal()
        self.finished = FakeSignal()
        FakePreviewThread.instances.append(self)

    def start(self):
        self.started = True

    def deleteLater(self):
        pass


@pytest.fixture()
def fake_preview(monkeypatch):
    FakePreviewThread.instances = []
    monkeypatch.setattr(cd, "PreviewThread", FakePreviewThread)
    monkeypatch.setattr(
        cd,
        "preview_thumbnail_url",
        lambda url: PAWCHIVE_THUMB if "pawchive" in url else "",
    )
    monkeypatch.setattr(cd, "has_cached_preview", lambda url, cache_dir: False)
    return FakePreviewThread


def _pixmap():
    pixmap = QPixmap(4, 4)
    pixmap.fill()
    return pixmap


def _make_modal(qtbot, tmp_path):
    modal = cd.ImageModal(
        PAWCHIVE_URL, str(tmp_path), parent=None, settings_tab=object()
    )
    qtbot.addWidget(modal)
    return modal


def test_pawchive_preview_loads_the_thumbnail_first(qtbot, tmp_path, fake_preview):
    modal = _make_modal(qtbot, tmp_path)

    assert fake_preview.instances[0].url == PAWCHIVE_THUMB
    assert fake_preview.instances[0].cache is False
    assert modal._load_full_btn.isHidden() is True
    modal.close()


def test_thumbnail_ready_reveals_the_load_full_button(qtbot, tmp_path, fake_preview):
    modal = _make_modal(qtbot, tmp_path)
    thread = fake_preview.instances[0]

    thread.preview_ready.emit(PAWCHIVE_THUMB, _pixmap())

    assert modal._load_full_btn.text() == translate("load_full_image")
    assert modal._load_full_btn.isHidden() is False
    assert modal._load_full_btn.isEnabled() is True
    modal.close()


def test_load_full_image_requests_the_full_url(qtbot, tmp_path, fake_preview):
    modal = _make_modal(qtbot, tmp_path)
    fake_preview.instances[0].preview_ready.emit(PAWCHIVE_THUMB, _pixmap())

    modal._load_full_btn.click()

    full_thread = fake_preview.instances[-1]
    assert full_thread.url == PAWCHIVE_URL
    assert full_thread.cache is True
    assert modal._load_full_btn.isEnabled() is False

    full_thread.preview_ready.emit(PAWCHIVE_URL, _pixmap())
    assert modal._load_full_btn.isHidden() is True
    modal.close()


def test_thumbnail_error_falls_back_to_the_full_url(
    qtbot, tmp_path, fake_preview, monkeypatch
):
    errors = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args, **kwargs: errors.append(args)
    )
    modal = _make_modal(qtbot, tmp_path)

    fake_preview.instances[0].error.emit("thumbnail unavailable")

    assert fake_preview.instances[-1].url == PAWCHIVE_URL
    assert fake_preview.instances[-1].cache is True
    assert errors == []
    modal.close()


def test_full_error_keeps_the_thumbnail_and_re_enables_the_button(
    qtbot, tmp_path, fake_preview, monkeypatch
):
    errors = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args, **kwargs: errors.append(args)
    )
    modal = _make_modal(qtbot, tmp_path)
    fake_preview.instances[0].preview_ready.emit(PAWCHIVE_THUMB, _pixmap())
    modal._load_full_btn.click()

    fake_preview.instances[-1].error.emit("full image unavailable")

    assert errors
    assert modal._label.pixmap().isNull() is False
    assert modal._load_full_btn.isHidden() is False
    assert modal._load_full_btn.isEnabled() is True
    assert modal._load_full_btn.text() == translate("load_full_image")
    modal.close()


def test_cached_full_render_skips_the_thumbnail_stage(
    qtbot, tmp_path, fake_preview, monkeypatch
):
    monkeypatch.setattr(cd, "has_cached_preview", lambda url, cache_dir: True)

    modal = _make_modal(qtbot, tmp_path)

    assert [thread.url for thread in fake_preview.instances] == [PAWCHIVE_URL]
    assert modal._load_full_btn.isHidden() is True
    modal.close()


def test_non_pawchive_preview_has_no_thumbnail_stage(qtbot, tmp_path, fake_preview):
    modal = cd.ImageModal(KEMONO_URL, str(tmp_path), parent=None, settings_tab=object())
    qtbot.addWidget(modal)

    assert [thread.url for thread in fake_preview.instances] == [KEMONO_URL]
    assert modal._load_full_btn.isHidden() is True
    modal.close()


def test_progress_does_not_clear_a_shown_thumbnail(qtbot, tmp_path, fake_preview):
    modal = _make_modal(qtbot, tmp_path)
    fake_preview.instances[0].preview_ready.emit(PAWCHIVE_THUMB, _pixmap())

    modal.update_progress(75)

    assert modal._progress_bar.value() == 75
    assert modal._label.text() == ""
    assert modal._label.pixmap().isNull() is False
    modal.close()


def test_preview_decode_survives_qts_allocation_limit(qapp):
    """A huge JPEG still previews even though Qt rejects the full bitmap."""
    image = QImage(2000, 3000, QImage.Format.Format_RGB32)
    image.fill(0)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    assert image.save(buffer, "JPEG")
    payload = bytes(buffer.data())

    previous_limit = QImageReader.allocationLimit()
    try:
        # The full 2000x3000 bitmap needs ~24 MB; the scaled 533x800 one does not.
        QImageReader.setAllocationLimit(4)
        assert QPixmap().loadFromData(payload) is False

        pixmap = cd._decode_preview_image(payload)

        assert pixmap is not None
        assert pixmap.size().width() == 533
        assert pixmap.size().height() == 800
    finally:
        QImageReader.setAllocationLimit(previous_limit)


def test_preview_decode_rejects_non_image_bytes(qapp):
    assert cd._decode_preview_image(b"not an image") is None


def _png_bytes():
    pixmap = QPixmap(2, 2)
    pixmap.fill()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


class _Response:
    def __init__(self, payload):
        self.status_code = 200
        self.headers = {"content-length": str(len(payload))}
        self._payload = payload

    def iter_content(self, chunk_size=8192):
        yield self._payload

    def raise_for_status(self):
        return None

    def close(self):
        return None


class _Session:
    def __init__(self):
        self.urls = []

    def get(self, url, headers=None, stream=None):
        self.urls.append(url)
        return _Response(_png_bytes())


def _run_thread(qtbot, tmp_path, monkeypatch, cache):
    session = _Session()
    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: session)
    # A fixed header set keeps this test from caching a Pawchive referer in
    # creator_downloader.HEADERS, which later header tests would inherit.
    monkeypatch.setattr(
        cd,
        "get_headers",
        lambda: {
            "User-Agent": "test-agent",
            "Referer": "https://pawchive.pw/",
        },
    )
    monkeypatch.setattr(cd, "get_domain_config", lambda url: dict(PAWCHIVE_CONFIG))
    previews = []
    errors = []
    thread = cd.PreviewThread(
        PAWCHIVE_THUMB, str(tmp_path), settings_tab=None, cache=cache
    )
    thread.preview_ready.connect(lambda url, pixmap: previews.append(url))
    thread.error.connect(errors.append)
    thread.run()
    return session, previews, errors


def test_preview_thread_can_skip_the_cache(qtbot, tmp_path, monkeypatch):
    session, previews, errors = _run_thread(qtbot, tmp_path, monkeypatch, cache=False)

    assert session.urls == [PAWCHIVE_THUMB]
    assert previews == [PAWCHIVE_THUMB]
    assert errors == []
    assert os.listdir(str(tmp_path)) == []


def test_preview_thread_without_cache_ignores_an_existing_entry(
    qtbot, tmp_path, monkeypatch
):
    cached = pc.preview_cache_path(PAWCHIVE_THUMB, str(tmp_path))
    with open(cached, "wb") as handle:
        handle.write(_png_bytes())

    session, previews, errors = _run_thread(qtbot, tmp_path, monkeypatch, cache=False)

    assert session.urls == [PAWCHIVE_THUMB]
    assert previews == [PAWCHIVE_THUMB]
    assert errors == []


def test_preview_thread_still_caches_by_default(qtbot, tmp_path, monkeypatch):
    session, previews, errors = _run_thread(qtbot, tmp_path, monkeypatch, cache=True)

    assert session.urls == [PAWCHIVE_THUMB]
    assert previews == [PAWCHIVE_THUMB]
    assert errors == []
    assert os.listdir(str(tmp_path)) == [
        os.path.basename(pc.preview_cache_path(PAWCHIVE_THUMB, str(tmp_path)))
    ]
