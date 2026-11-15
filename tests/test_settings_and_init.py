import importlib
import importlib.util
import runpy
import sys
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd, kd_settings as ks


def test___main_calls_app_main(monkeypatch):
    called = []

    def fake_main():
        called.append(True)

    monkeypatch.setattr("kemonodownloader.app.main", fake_main)
    # Execute package as __main__ which should call our patched main
    runpy.run_module("kemonodownloader", run_name="__main__")
    assert called


def test_disable_ui_effects_turns_off_popup_and_tooltip_animations(qapp):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from kemonodownloader import app as app_module

    app_module.disable_ui_effects()

    for effect in (
        Qt.UIEffect.UI_AnimateCombo,
        Qt.UIEffect.UI_AnimateTooltip,
        Qt.UIEffect.UI_FadeTooltip,
    ):
        assert QApplication.isEffectEnabled(effect) is False


def test_tooltip_lifetime_filter_stretches_the_widget_display_time(qapp):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)
    widget = QWidget()
    widget.setToolTip("Hover help")

    assert event_filter.eventFilter(widget, QEvent(QEvent.Type.ToolTip)) is False

    # Qt would otherwise expire the tip after 10 s plus 40 ms per character;
    # stretching the widget's own display time keeps it up while hovered.
    assert widget.toolTipDuration() == app_module.TOOLTIP_HOVER_TIME
    assert app_module.TOOLTIP_HOVER_TIME > 10_000


def test_tooltip_lifetime_filter_ignores_tooltip_events_from_non_widgets(qapp):
    from PyQt6.QtCore import QEvent, QObject

    from kemonodownloader import app as app_module

    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)

    assert event_filter.eventFilter(QObject(), QEvent(QEvent.Type.ToolTip)) is False
    assert event_filter._owner is None


def test_tooltip_lifetime_filter_hides_on_interaction(qapp):
    from PyQt6.QtCore import QEvent

    from kemonodownloader import app as app_module

    hidden = []
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: hidden.append(True))
    event_filter.eventFilter(None, QEvent(QEvent.Type.ToolTip))

    event_filter.eventFilter(None, QEvent(QEvent.Type.MouseButtonPress))

    assert hidden == [True]


def test_tooltip_lifetime_filter_hides_when_the_owner_is_hidden(qapp):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    hidden = []
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: hidden.append(True))
    owner = QWidget()

    event_filter.eventFilter(owner, QEvent(QEvent.Type.ToolTip))
    assert hidden == []

    event_filter.eventFilter(owner, QEvent(QEvent.Type.Hide))
    assert hidden == [True]


def test_tooltip_lifetime_filter_hides_when_the_owner_is_left(qapp):
    from PyQt6.QtCore import QEvent, QObject
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    hidden = []
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: hidden.append(True))
    owner = QWidget()
    other = QObject()

    event_filter.eventFilter(owner, QEvent(QEvent.Type.ToolTip))
    event_filter.eventFilter(other, QEvent(QEvent.Type.Leave))
    assert hidden == []

    event_filter.eventFilter(owner, QEvent(QEvent.Type.Leave))
    assert hidden == [True]


def test_install_tooltip_lifetime_attaches_to_the_app(qapp):
    from kemonodownloader import app as app_module

    event_filter = app_module.install_tooltip_lifetime(qapp)

    assert qapp._tooltip_lifetime_filter is event_filter


def test_get_default_base_directory_various_platforms(monkeypatch):
    # Windows-like
    monkeypatch.setattr(sys, "platform", "win32")
    p = ks.SettingsTab.get_default_base_directory(None)
    assert "Kemono Downloader" in p

    # macOS-like
    monkeypatch.setattr(sys, "platform", "darwin")
    p = ks.SettingsTab.get_default_base_directory(None)
    assert "Library/Application Support" in p or "Kemono Downloader" in p

    # Linux-like
    monkeypatch.setattr(sys, "platform", "linux")
    p = ks.SettingsTab.get_default_base_directory(None)
    assert "Kemono Downloader" in p


def test_get_proxy_settings_custom_and_tor(monkeypatch, tmp_path):
    # Custom proxy (using settings dict)
    fake_self = SimpleNamespace()
    fake_self.settings = {
        "use_proxy": True,
        "proxy_type": "custom",
        "custom_proxy_url": "http://1.2.3.4:8080",
    }
    fake_self.temp_settings = {}
    fake_self.tor_process = None

    res = ks.SettingsTab.get_proxy_settings(fake_self)
    assert res == {"http": "http://1.2.3.4:8080", "https": "http://1.2.3.4:8080"}

    # Tor proxy: simulate running tor process and presence of socks
    class FakeProc:
        def state(self):
            return ks.QProcess.ProcessState.Running

    fake_self2 = SimpleNamespace()
    fake_self2.settings = {"use_proxy": True, "proxy_type": "tor"}
    fake_self2.temp_settings = {"use_proxy": True, "proxy_type": "tor", "tor_path": ""}
    fake_self2.tor_process = FakeProc()

    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: object() if name == "socks" else None
    )
    res2 = ks.SettingsTab.get_proxy_settings(fake_self2)
    assert res2 is not None
    assert res2["http"].startswith("socks5h://") or res2["http"].startswith("http://")


def test_get_domain_config_coomer_and_default():
    co = cd.get_domain_config("https://coomer.st/some/path")
    assert co["domain"] == "coomer.st"
    km = cd.get_domain_config("https://kemono.cr/some/path")
    assert km["domain"] == "kemono.cr"
