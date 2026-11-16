"""Full post preview: image extraction, post fetch, loader, and list dialog."""

import threading
from collections import OrderedDict

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QPixmap
from tests.factories import Signal, make_tab_parent

from kemonodownloader import creator_downloader as cd

CREATOR_URL = "https://pawchive.pw/patreon/user/123"
PAWCHIVE_CONFIG = {
    "domain": "pawchive.pw",
    "base_url": "https://pawchive.pw",
    "api_base": "https://pawchive.pw/api/v1",
    "referer": "https://pawchive.pw/",
    "file_base_url": "https://file.pawchive.pw",
    "thumbnail_base_url": "https://img.pawchive.pw/thumbnail",
}


def _post(**overrides):
    post = {
        "id": "42",
        "title": "A post",
        "published": "2026-01-02T03:04:05",
        "content": "<p>Hello <b>world</b></p>",
        "file": {"name": "main.png", "path": "/data/aa/bb/main.png"},
        "attachments": [
            {"name": "main.png", "path": "/data/aa/bb/main.png"},
            {"name": "one.jpg", "path": "/data/cc/dd/one.jpg"},
        ],
    }
    post.update(overrides)
    return post


def _png_bytes():
    pixmap = QPixmap(2, 2)
    pixmap.fill()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def test_post_image_entries_orders_and_dedupes():
    entries = cd.post_image_entries(_post(), PAWCHIVE_CONFIG)

    assert [entry.name for entry in entries] == ["main.png", "one.jpg"]
    assert entries[0].full_url == "https://file.pawchive.pw/data/aa/bb/main.png"
    assert entries[0].thumbnail_url == (
        "https://img.pawchive.pw/thumbnail/data/aa/bb/main.png"
    )


def test_post_image_entries_includes_content_images_last():
    post = _post(content='<p>text</p><img src="/data/ee/ff/content.png">')

    entries = cd.post_image_entries(post, PAWCHIVE_CONFIG)

    assert [entry.name for entry in entries] == [
        "main.png",
        "one.jpg",
        "content.png",
    ]
    assert entries[-1].thumbnail_url.endswith("/data/ee/ff/content.png")


def test_post_image_entries_skips_non_images():
    post = {
        "file": {"name": "clip.mp4", "path": "/data/v/clip.mp4"},
        "attachments": [{"name": "a.zip", "path": "/data/a.zip"}],
        "content": "",
    }

    assert cd.post_image_entries(post, PAWCHIVE_CONFIG) == []


def test_post_description_strips_media_and_scripts():
    html = cd.post_description_html(
        _post(
            content=(
                "<p>Hello <b>world</b></p>"
                '<img src="/data/x.png">'
                "<script>bad()</script>"
            )
        )
    )

    assert "Hello" in html
    assert "<b>world</b>" in html
    assert "<img" not in html
    assert "<script" not in html


def test_post_description_is_empty_without_text():
    assert cd.post_description_html(_post(content="<img src='x.png'>")) == ""


class _JsonResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def json(self):
        return self._data


class _Session:
    def __init__(self, response):
        self._response = response
        self.urls = []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        return self._response


def test_fetch_post_data_parses_the_wrapped_post(monkeypatch):
    monkeypatch.setattr(cd, "get_domain_config", lambda url: dict(PAWCHIVE_CONFIG))
    session = _Session(_JsonResponse({"post": {"id": "42"}}))
    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: session)

    post, message = cd.fetch_post_data("42", CREATOR_URL)

    assert post == {"id": "42"}
    assert message == ""
    assert session.urls == ["https://pawchive.pw/api/v1/patreon/user/123/post/42"]


def test_fetch_post_data_reports_http_errors(monkeypatch):
    monkeypatch.setattr(cd, "get_domain_config", lambda url: dict(PAWCHIVE_CONFIG))
    session = _Session(_JsonResponse({}, status_code=404))
    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: session)

    post, message = cd.fetch_post_data("42", CREATOR_URL, max_retries=1)

    assert post is None
    assert "404" in message


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class FakeLoader:
    instances = []

    def __init__(self, settings_tab=None, max_workers=4, parent=None, cache=None):
        self.requests = []
        self.stopped = False
        self.cache = cache
        self.image_ready = FakeSignal()
        self.image_failed = FakeSignal()
        FakeLoader.instances.append(self)

    def request(self, url):
        self.requests.append(url)

    def stop(self):
        self.stopped = True

    def deleteLater(self):
        pass


def _make_dialog(qtbot, monkeypatch, post=None):
    FakeLoader.instances = []
    monkeypatch.setattr(cd, "PostImagesLoader", FakeLoader)
    monkeypatch.setattr(cd, "get_domain_config", lambda url: dict(PAWCHIVE_CONFIG))
    dialog = cd.PostPreviewDialog(
        "42", CREATOR_URL, settings_tab=None, post_data=post or _post()
    )
    qtbot.addWidget(dialog)
    return dialog


def test_post_preview_populates_description_and_rows(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)

    assert dialog._title_label.text() == "A post"
    assert len(dialog._rows) == 2
    assert dialog._description.isHidden() is False
    assert "Hello" in dialog._description.toPlainText()
    loader = FakeLoader.instances[0]
    assert loader.requests == [entry.thumbnail_url for entry in dialog._entries]
    dialog.close()


def test_post_preview_description_is_short_and_resizable(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    dialog.show()
    qtbot.wait(30)

    assert dialog._splitter.count() == 2
    assert dialog._splitter.orientation() == Qt.Orientation.Vertical
    assert dialog._description.isVisible() is True
    assert dialog._splitter.sizes()[0] <= 120
    assert dialog._description.maximumHeight() > 120

    dialog._splitter.setSizes([200, 300])
    assert dialog._splitter.sizes()[0] > 120
    dialog.close()


def test_post_preview_without_images_says_so(qtbot, monkeypatch):
    dialog = _make_dialog(
        qtbot,
        monkeypatch,
        post={
            "title": "Empty",
            "file": {},
            "attachments": [],
            "content": "",
        },
    )

    assert dialog._rows == []
    assert dialog._status_label.text() == cd.translate("post_preview_no_images")
    dialog.close()


def test_post_preview_image_ready_fills_the_row(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    image.fill(0)
    loader = FakeLoader.instances[0]

    loader.image_ready.emit(dialog._entries[0].thumbnail_url, image)
    loader.image_ready.emit(dialog._entries[1].thumbnail_url, image)

    row = dialog._row_by_url[dialog._entries[0].thumbnail_url]
    assert row.has_image is True
    assert row._image_label._pixmap is not None
    assert row._image_label._pixmap.isNull() is False
    assert dialog._status_label.text() == cd.translate("post_preview_images_count", 2)
    dialog.close()


def test_post_preview_click_opens_the_image_modal(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    opened = []

    class FakeModal:
        def __init__(self, url, parent=None, settings_tab=None, initial_image=None):
            opened.append((url, initial_image))

        def exec(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(cd, "ImageModal", FakeModal)
    entry = dialog._entries[1]
    image = QImage(4, 4, QImage.Format.Format_RGB32)
    dialog._row_by_url[entry.thumbnail_url].set_image(image)

    dialog._open_image(entry)

    assert opened == [(entry.thumbnail_url, image)]
    dialog.close()


def test_post_preview_lazy_loads_large_posts(qtbot, monkeypatch):
    attachments = [
        {"name": f"{index}.png", "path": f"/data/aa/{index}.png"} for index in range(30)
    ]
    post = _post(file={}, attachments=attachments, content="")
    dialog = _make_dialog(qtbot, monkeypatch, post=post)
    dialog.show()
    qtbot.wait(30)

    requests = FakeLoader.instances[0].requests
    assert 0 < len(requests) < 30
    dialog.close()


def test_post_preview_fetch_error_shows_a_retry(qtbot, monkeypatch):
    class FakeFetch:
        def __init__(self, *args, **kwargs):
            self.fetched = FakeSignal()
            self.error = FakeSignal()
            self.finished = FakeSignal()

        def isRunning(self):
            return False

        def start(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(cd, "PostPreviewFetchThread", FakeFetch)
    dialog = cd.PostPreviewDialog("42", CREATOR_URL, settings_tab=None)
    qtbot.addWidget(dialog)

    dialog._on_post_error("42", "boom")

    assert dialog._error_label.isHidden() is False
    assert "boom" in dialog._error_label.text()
    assert dialog._retry_btn.isHidden() is False
    dialog.close()


def test_post_images_loader_dedupes_and_reuses_bytes(qtbot, monkeypatch):
    url = "https://img.pawchive.pw/thumbnail/data/aa/bb/main.png"
    payload = _png_bytes()
    downloads = []

    def fake_download(target, settings_tab=None, on_progress=None):
        downloads.append(target)
        return payload

    monkeypatch.setattr(cd, "_download_image_bytes", fake_download)
    loader = cd.PostImagesLoader(max_workers=2)
    ready = []
    loader.image_ready.connect(lambda ready_url, image: ready.append(ready_url))

    loader.request(url)
    loader.request(url)
    qtbot.waitUntil(lambda: len(ready) == 1, timeout=5000)
    assert downloads == [url]

    # The bytes are cached, so a later request decodes them again without
    # another network call.
    loader.request(url)
    qtbot.waitUntil(lambda: len(ready) == 2, timeout=5000)
    assert downloads == [url]
    loader.stop()


def test_post_images_loader_reports_failures(qtbot, monkeypatch):
    def fail(target, settings_tab=None, on_progress=None):
        raise RuntimeError("no route")

    monkeypatch.setattr(cd, "_download_image_bytes", fail)
    loader = cd.PostImagesLoader(max_workers=1)
    failures = []
    loader.image_failed.connect(lambda url, message: failures.append((url, message)))

    loader.request("https://img.pawchive.pw/thumbnail/data/x.png")
    qtbot.waitUntil(lambda: bool(failures), timeout=5000)

    assert failures[0][0].endswith("/data/x.png")
    assert "no route" in failures[0][1]
    loader.stop()


def test_post_preview_fetch_thread_is_registered_until_finished(qtbot, monkeypatch):
    class FakeFetch:
        instances = []

        def __init__(self, *args, **kwargs):
            self.fetched = FakeSignal()
            self.error = FakeSignal()
            self.finished = FakeSignal()
            FakeFetch.instances.append(self)

        def isRunning(self):
            return False

        def start(self):
            pass

        def deleteLater(self):
            pass

    monkeypatch.setattr(cd, "PostPreviewFetchThread", FakeFetch)
    registry = []
    dialog = cd.PostPreviewDialog(
        "42", CREATOR_URL, settings_tab=None, thread_registry=registry
    )
    qtbot.addWidget(dialog)

    assert registry == [FakeFetch.instances[0]]
    FakeFetch.instances[0].finished.emit()
    assert registry == []
    dialog.close()


def test_post_images_loader_evicts_the_oldest_bytes(qtbot, monkeypatch):
    payload = _png_bytes()
    downloads = []

    def fake_download(target, settings_tab=None, on_progress=None):
        downloads.append(target)
        return payload

    monkeypatch.setattr(cd, "_download_image_bytes", fake_download)
    loader = cd.PostImagesLoader(max_workers=1, cache_bytes=len(payload) + 1)
    ready = []
    loader.image_ready.connect(lambda ready_url, image: ready.append(ready_url))
    first = "https://img.pawchive.pw/thumbnail/data/aa/first.png"
    second = "https://img.pawchive.pw/thumbnail/data/bb/second.png"

    loader.request(first)
    qtbot.waitUntil(lambda: len(ready) == 1, timeout=5000)
    loader.request(second)
    qtbot.waitUntil(lambda: len(ready) == 2, timeout=5000)

    assert loader.cached_urls == (second,)

    loader.request(first)
    qtbot.waitUntil(lambda: len(ready) == 3, timeout=5000)
    assert downloads == [first, second, first]
    loader.stop()


def test_post_images_loader_stop_clears_private_cache(qtbot, monkeypatch):
    payload = _png_bytes()
    monkeypatch.setattr(cd, "_download_image_bytes", lambda *args, **kwargs: payload)
    loader = cd.PostImagesLoader(max_workers=1)
    ready = []
    loader.image_ready.connect(lambda ready_url, image: ready.append(ready_url))
    loader.request("https://img.pawchive.pw/thumbnail/data/aa/stop.png")
    qtbot.waitUntil(lambda: len(ready) == 1, timeout=5000)
    assert loader.cached_bytes == len(payload)

    loader.stop()

    assert loader.cached_bytes == 0
    assert loader.cached_urls == ()


def test_shared_preview_cache_survives_dialog_close(qtbot, monkeypatch):
    payload = _png_bytes()
    downloads = []

    def fake_download(target, settings_tab=None, on_progress=None):
        downloads.append(target)
        return payload

    monkeypatch.setattr(cd, "_download_image_bytes", fake_download)
    cache = cd.PreviewImageCache()
    url = "https://img.pawchive.pw/thumbnail/data/cc/shared.png"

    first = cd.PostImagesLoader(max_workers=1, cache=cache)
    first_ready = []
    first.image_ready.connect(lambda ready_url, image: first_ready.append(ready_url))
    first.request(url)
    qtbot.waitUntil(lambda: len(first_ready) == 1, timeout=5000)
    first.stop()

    # The loader is gone, but the Creator tab's session cache is not.
    assert cache.cached_bytes == len(payload)

    second = cd.PostImagesLoader(max_workers=1, cache=cache)
    second_ready = []
    second.image_ready.connect(lambda ready_url, image: second_ready.append(ready_url))
    second.request(url)
    qtbot.waitUntil(lambda: len(second_ready) == 1, timeout=5000)

    assert downloads == [url]
    second.stop()
    assert cache.cached_bytes == len(payload)


def test_stopped_loader_does_not_cache_a_late_result(qtbot, monkeypatch):
    payload = _png_bytes()
    started = threading.Event()
    release = threading.Event()

    def slow_download(target, settings_tab=None, on_progress=None):
        started.set()
        release.wait(5)
        return payload

    monkeypatch.setattr(cd, "_download_image_bytes", slow_download)
    loader = cd.PostImagesLoader(max_workers=1)
    loader.request("https://img.pawchive.pw/thumbnail/data/dd/late.png")
    assert started.wait(5)

    loader.stop()
    release.set()
    loader._executor.shutdown(wait=True)

    assert loader.cached_bytes == 0


def test_post_preview_close_releases_rows_and_stops_loader(qtbot, monkeypatch):
    dialog = _make_dialog(qtbot, monkeypatch)
    image = QImage(20, 10, QImage.Format.Format_RGB32)
    image.fill(0)
    loader = FakeLoader.instances[0]
    url = dialog._entries[0].thumbnail_url
    loader.image_ready.emit(url, image)
    row = dialog._row_by_url[url]
    assert row.has_image is True

    dialog.close()

    assert loader.stopped is True
    assert dialog._loader is None
    assert dialog._rows == []
    assert row.has_image is False


def test_post_preview_cache_is_bounded_and_hits_move_to_the_end():
    tab = cd.CreatorDownloaderTab.__new__(cd.CreatorDownloaderTab)
    tab._post_preview_cache = OrderedDict()
    tab.current_creator_url = CREATOR_URL
    for index in range(cd.POST_PREVIEW_CACHE_LIMIT):
        tab._remember_post_preview_data(str(index), {"id": str(index)})

    assert len(tab._post_preview_cache) == cd.POST_PREVIEW_CACHE_LIMIT
    assert tab._cached_post_preview_data(CREATOR_URL, "0") == {"id": "0"}

    tab._remember_post_preview_data("new", {"id": "new"})

    assert len(tab._post_preview_cache) == cd.POST_PREVIEW_CACHE_LIMIT
    assert tab._preview_cache_key(CREATOR_URL, "0") in tab._post_preview_cache
    assert tab._preview_cache_key(CREATOR_URL, "1") not in tab._post_preview_cache
    assert tab._preview_cache_key(CREATOR_URL, "new") in tab._post_preview_cache


def test_preview_cache_key_ignores_a_trailing_slash():
    assert cd.CreatorDownloaderTab._preview_cache_key(
        CREATOR_URL + "/", "7"
    ) == cd.CreatorDownloaderTab._preview_cache_key(CREATOR_URL, "7")


def test_switching_creator_clears_preview_caches(qtbot, tmp_path, monkeypatch):
    parent = make_tab_parent(tmp_path)
    tab = cd.CreatorDownloaderTab(parent)
    qtbot.addWidget(tab)
    tab.current_creator_url = "https://kemono.cr/patreon/user/1"
    tab._post_preview_cache[tab._preview_cache_key(tab.current_creator_url, "42")] = {
        "id": "42"
    }
    tab._preview_image_cache.store("https://img.example/a.png", b"data")

    class FakeDetection:
        def __init__(self, *args, **kwargs):
            self.finished = Signal()
            self.posts_batch = Signal()
            self.log = Signal()
            self.error = Signal()

        def isRunning(self):
            return False

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(cd, "PostDetectionThread", FakeDetection)
    for name in ("information", "critical"):
        monkeypatch.setattr(cd.QMessageBox, name, lambda *args, **kwargs: None)
    monkeypatch.setattr(
        cd.QMessageBox,
        "question",
        lambda *args, **kwargs: cd.QMessageBox.StandardButton.Yes,
    )

    tab.check_creator_from_queue("https://kemono.cr/patreon/user/2")

    assert len(tab._post_preview_cache) == 0
    assert tab._preview_image_cache.cached_bytes == 0


def test_post_preview_dialog_passes_the_shared_cache_to_its_loader(qtbot, monkeypatch):
    cache = cd.PreviewImageCache()
    FakeLoader.instances = []
    monkeypatch.setattr(cd, "PostImagesLoader", FakeLoader)
    monkeypatch.setattr(cd, "get_domain_config", lambda url: dict(PAWCHIVE_CONFIG))

    dialog = cd.PostPreviewDialog(
        "42",
        CREATOR_URL,
        settings_tab=None,
        post_data=_post(),
        image_cache=cache,
    )
    qtbot.addWidget(dialog)

    assert FakeLoader.instances[0].cache is cache
    dialog.close()
