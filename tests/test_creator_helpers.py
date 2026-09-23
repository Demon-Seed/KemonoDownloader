import base64
import hashlib
import os
from types import SimpleNamespace

from kemonodownloader.creator_downloader import (
    PreviewThread,
    ThreadSettings,
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

    png_data = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAAWgmWQ0AAAAASUVORK5CYII="
    )
    with open(cache_path, "wb") as f:
        f.write(png_data)

    pt = PreviewThread(url, cache_dir, settings_tab=None)
    # Running should load the cached pixmap and exit without exception
    pt.run()
