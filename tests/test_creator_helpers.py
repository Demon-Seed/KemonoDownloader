import hashlib
import os
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


def test_preview_thread_loads_cached_image(tmp_path):
    # Create a tiny valid PNG (1x1) in cache with expected cache key
    url = "https://example.com/img/1.png"
    cache_key = hashlib.md5(url.encode()).hexdigest() + os.path.splitext(url)[1]
    cache_dir = str(tmp_path / "cache")
    os.makedirs(cache_dir, exist_ok=True)
    cache_path = os.path.join(cache_dir, cache_key)

    # A real PNG: the previous hard-coded bytes failed libpng's CRC check, so
    # QPixmap.load() never ran and the test could not fail.
    from PyQt6.QtGui import QImage

    image = QImage(1, 1, QImage.Format.Format_ARGB32)
    image.fill(0xFF0000FF)
    assert image.save(cache_path, "PNG")

    pt = PreviewThread(url, cache_dir, settings_tab=None)
    ready = []
    pt.preview_ready = SimpleNamespace(emit=lambda u, pm: ready.append((u, pm)))
    # Running should load the cached pixmap and emit it without a request
    pt.run()

    assert ready, "a cached preview must be emitted"
    assert ready[0][0] == url
    assert ready[0][1] is not None and not ready[0][1].isNull()
