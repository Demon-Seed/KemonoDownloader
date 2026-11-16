from types import SimpleNamespace

from kemonodownloader.creator_downloader import (
    PreviewThread,
    get_domain_config,
    get_headers,
    get_session,
)


def test_get_domain_config_variants():
    c = get_domain_config("https://coomer.st/user/1")
    assert c["domain"] == "coomer.st"
    k = get_domain_config("https://kemono.cr/user/1")
    assert k["domain"] == "kemono.cr"


def test_get_headers_contains_keys():
    headers = get_headers()
    assert "User-Agent" in headers
    assert "Accept-Language" in headers


def test_get_session_with_http_and_socks(tmp_path):
    # HTTP proxy
    settings_tab = SimpleNamespace(
        get_proxy_settings=lambda: {"http": "http://1.2.3.4:8080"}
    )
    sess = get_session(settings_tab)
    assert "http" in sess.proxies

    # SOCKS proxy should return a socks_session (different object)
    settings_tab2 = SimpleNamespace(
        get_proxy_settings=lambda: {"http": "socks5://127.0.0.1:9050"}
    )
    sess2 = get_session(settings_tab2)
    assert sess2 is not None


def test_preview_thread_decodes_an_image(monkeypatch):
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QImage

    url = "https://example.com/img/1.png"
    image = QImage(1, 1, QImage.Format.Format_ARGB32)
    image.fill(0xFF0000FF)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.ReadWrite)
    image.save(buffer, "PNG")
    payload = bytes(buffer.data())
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader._download_image_bytes",
        lambda *a, **k: payload,
    )

    pt = PreviewThread(url, settings_tab=None)
    ready = []
    pt.preview_ready = SimpleNamespace(emit=lambda u, pm: ready.append((u, pm)))
    pt.run()

    assert ready, "a decoded preview must be emitted"
    assert ready[0][0] == url
    assert ready[0][1] is not None and not ready[0][1].isNull()
