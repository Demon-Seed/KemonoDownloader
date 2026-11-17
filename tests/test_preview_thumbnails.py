"""Thumbnail-only image previews: URL mapping, decoding, and the modal flow."""

import os

import pytest
from PyQt6.QtCore import QBuffer, QIODevice
from PyQt6.QtGui import QImage, QImageReader, QPixmap
from PyQt6.QtWidgets import QMessageBox

from kemonodownloader import creator_downloader as cd, domain_config as dc
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
    assert dc.preview_thumbnail_url(PAWCHIVE_URL, PAWCHIVE_CONFIG) == PAWCHIVE_THUMB


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

    def __init__(self, url, settings_tab=None):
        self.url = url
        self.settings_tab = settings_tab
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
    return FakePreviewThread


def _pixmap():
    pixmap = QPixmap(4, 4)
    pixmap.fill()
    return pixmap


def _make_modal(qtbot):
    modal = cd.ImageModal(PAWCHIVE_URL, parent=None, settings_tab=object())
    qtbot.addWidget(modal)
    return modal


def test_pawchive_preview_loads_the_thumbnail(qtbot, fake_preview):
    modal = _make_modal(qtbot)

    assert fake_preview.instances[0].url == PAWCHIVE_THUMB
    assert fake_preview.instances[0].settings_tab is modal._settings_tab
    modal.close()


def test_non_pawchive_preview_uses_the_original_url(qtbot, fake_preview):
    modal = cd.ImageModal(KEMONO_URL, parent=None, settings_tab=object())
    qtbot.addWidget(modal)

    assert [thread.url for thread in fake_preview.instances] == [KEMONO_URL]
    modal.close()


def test_preview_ready_displays_the_image(qtbot, fake_preview):
    modal = _make_modal(qtbot)

    fake_preview.instances[0].preview_ready.emit(PAWCHIVE_THUMB, _pixmap())

    assert modal._progress_bar.isHidden()
    assert modal._label.pixmap().isNull() is False
    assert modal._image_shown is True
    modal.close()


def test_initial_image_skips_the_network(qtbot, fake_preview):
    modal = cd.ImageModal(
        PAWCHIVE_URL,
        parent=None,
        settings_tab=object(),
        initial_image=_pixmap().toImage(),
    )
    qtbot.addWidget(modal)

    assert fake_preview.instances == []
    assert modal._label.pixmap().isNull() is False
    modal.close()


def test_preview_error_shows_a_message(qtbot, fake_preview, monkeypatch):
    errors = []
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *args, **kwargs: errors.append(args)
    )
    modal = _make_modal(qtbot)

    fake_preview.instances[0].error.emit("thumbnail unavailable")

    assert errors
    assert modal._label.text() == translate("error_loading_image")
    modal.close()


def test_progress_does_not_clear_a_shown_image(qtbot, fake_preview):
    modal = _make_modal(qtbot)
    fake_preview.instances[0].preview_ready.emit(PAWCHIVE_THUMB, _pixmap())

    modal.update_progress(75)

    assert modal._progress_bar.value() == 75
    assert modal._label.text() == ""
    assert modal._label.pixmap().isNull() is False
    modal.close()


def test_close_releases_the_shown_pixmap(qtbot, fake_preview):
    modal = _make_modal(qtbot)
    fake_preview.instances[0].preview_ready.emit(PAWCHIVE_THUMB, _pixmap())
    assert modal._label.pixmap().isNull() is False

    modal.close()

    assert modal._label.pixmap().isNull() is True


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

    def get(self, url, headers=None, stream=None, timeout=None):
        self.urls.append(url)
        return _Response(_png_bytes())


def test_preview_thread_fetches_without_writing_any_files(
    qtbot, tmp_path, monkeypatch
):
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
    thread = cd.PreviewThread(PAWCHIVE_THUMB, settings_tab=None)
    thread.preview_ready.connect(lambda url, pixmap: previews.append((url, pixmap)))
    thread.error.connect(errors.append)

    thread.run()

    assert session.urls == [PAWCHIVE_THUMB]
    assert errors == []
    assert previews and previews[0][0] == PAWCHIVE_THUMB
    assert isinstance(previews[0][1], QPixmap)
    assert os.listdir(str(tmp_path)) == []
