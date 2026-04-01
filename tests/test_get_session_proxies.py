from types import SimpleNamespace

from kemonodownloader.creator_downloader import get_session


def test_get_session_http_proxy_updates_proxies():
    settings_tab = SimpleNamespace(
        get_proxy_settings=lambda: {
            "http": "http://127.0.0.1:3128",
            "https": "http://127.0.0.1:3128",
        }
    )
    session = get_session(settings_tab)
    assert session is not None
    assert session.proxies.get("http") == "http://127.0.0.1:3128"


def test_get_session_socks_proxy_returns_socks_session():
    settings_tab = SimpleNamespace(
        get_proxy_settings=lambda: {"http": "socks5h://127.0.0.1:9050"}
    )
    session = get_session(settings_tab)
    assert session is not None
    # Socks session should have proxies updated
    assert session.proxies.get("http") == "socks5h://127.0.0.1:9050"
