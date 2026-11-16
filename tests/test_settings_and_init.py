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
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    hidden = []
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: hidden.append(True))
    widget = QWidget()
    widget.setToolTip("Hover help")
    # Stand in for a tooltip that is currently on screen.
    event_filter._owner = widget
    event_filter._shown = True

    event_filter.eventFilter(widget, QEvent(QEvent.Type.MouseButtonPress))

    assert hidden == [True]


def test_tooltip_lifetime_filter_skips_idle_interactions(qapp):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QToolTip

    from kemonodownloader import app as app_module

    QToolTip.hideText()  # a previous test may have left a tip up
    hidden = []
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: hidden.append(True))

    # Nothing shown and nothing pending: a keypress elsewhere should not walk
    # the top-level widgets or call QToolTip.hideText().
    event_filter.eventFilter(None, QEvent(QEvent.Type.MouseButtonPress))

    assert hidden == []


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


def test_tooltip_lifetime_filter_shows_after_the_fixed_delay(qapp, monkeypatch):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    shown = []
    monkeypatch.setattr(
        app_module.QToolTip,
        "showText",
        lambda pos, text, widget=None: shown.append(text),
    )
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)
    widget = QWidget()
    widget.setToolTip("Hover help")

    # Hovering starts our own timer at a fixed, shorter delay; nothing is
    # shown until it fires.
    event_filter.eventFilter(widget, QEvent(QEvent.Type.Enter))
    assert event_filter._timer.interval() == app_module.TOOLTIP_HOVER_DELAY
    assert app_module.TOOLTIP_HOVER_DELAY < 700
    assert shown == []

    event_filter._timer.timeout.emit()
    assert shown == ["Hover help"]
    assert widget.toolTipDuration() == app_module.TOOLTIP_HOVER_TIME

    # Qt's own ToolTip event for the same widget would double up, so it is
    # swallowed; the owner still hides on Leave.
    assert event_filter.eventFilter(widget, QEvent(QEvent.Type.ToolTip)) is True


def test_tooltip_lifetime_filter_ignores_disabled_widgets(qapp):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)
    widget = QWidget()
    widget.setToolTip("Hover help")
    widget.setEnabled(False)

    event_filter.eventFilter(widget, QEvent(QEvent.Type.Enter))

    assert event_filter._timer.isActive() is False
    assert event_filter._owner is None


def test_tooltip_lifetime_filter_ignores_qt_early_tooltip_events(qapp, monkeypatch):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    shown = []
    monkeypatch.setattr(
        app_module.QToolTip,
        "showText",
        lambda pos, text, widget=None: shown.append(text),
    )
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)
    widget = QWidget()
    widget.setToolTip("Hover help")

    event_filter.eventFilter(widget, QEvent(QEvent.Type.Enter))
    # Qt sometimes sends this ~20 ms after Enter (its tip is "awake"), other
    # times ~700 ms. Either way it must not shorten the fixed delay.
    assert event_filter.eventFilter(widget, QEvent(QEvent.Type.ToolTip)) is True
    assert shown == []
    assert event_filter._timer.isActive() is True

    event_filter._timer.timeout.emit()
    assert shown == ["Hover help"]


def test_tooltip_lifetime_filter_stays_quiet_after_a_click(qapp, monkeypatch):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    shown = []
    monkeypatch.setattr(
        app_module.QToolTip,
        "showText",
        lambda pos, text, widget=None: shown.append(text),
    )
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)
    widget = QWidget()
    widget.setToolTip("Hover help")

    event_filter.eventFilter(widget, QEvent(QEvent.Type.Enter))
    event_filter.eventFilter(widget, QEvent(QEvent.Type.MouseButtonPress))

    # The pointer never left, so the tip stays hidden.
    assert event_filter.eventFilter(widget, QEvent(QEvent.Type.ToolTip)) is True
    assert event_filter._timer.isActive() is False
    assert shown == []

    # A click can make Qt re-enter the same widget; that must not re-arm it.
    event_filter.eventFilter(widget, QEvent(QEvent.Type.Enter))
    assert event_filter._timer.isActive() is False

    # Leaving re-arms the tip for the next hover.
    event_filter.eventFilter(widget, QEvent(QEvent.Type.Leave))
    event_filter.eventFilter(widget, QEvent(QEvent.Type.Enter))
    assert event_filter._timer.isActive() is True


def test_tooltip_lifetime_filter_does_not_show_before_the_delay_without_enter(
    qapp, monkeypatch
):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    shown = []
    monkeypatch.setattr(
        app_module.QToolTip,
        "showText",
        lambda pos, text, widget=None: shown.append(text),
    )
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)
    widget = QWidget()
    widget.setToolTip("Hover help")
    widget.underMouse = lambda: True

    # Qt's own event can arrive before Enter. It must only arm the fixed-delay
    # timer, never show instantly on Qt's platform-dependent schedule.
    assert event_filter.eventFilter(widget, QEvent(QEvent.Type.ToolTip)) is True
    assert event_filter._timer.isActive() is True
    assert shown == []

    event_filter._timer.timeout.emit()
    assert shown == ["Hover help"]


def test_tooltip_lifetime_filter_waits_for_the_pointer_to_rest(qapp, monkeypatch):
    from PyQt6.QtCore import QEvent, QPoint
    from PyQt6.QtGui import QCursor
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    shown = []
    monkeypatch.setattr(
        app_module.QToolTip,
        "showText",
        lambda pos, text, widget=None: shown.append(text),
    )
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)
    widget = QWidget()
    widget.setToolTip("Hover help")

    event_filter.eventFilter(widget, QEvent(QEvent.Type.Enter))
    event_filter._timer.stop()
    # Tiny jitter within the movement threshold does not restart the clock...
    event_filter._arm_pos = QCursor.pos()
    event_filter.eventFilter(widget, QEvent(QEvent.Type.HoverMove))
    assert event_filter._timer.isActive() is False

    # ...but a real move does.
    event_filter._arm_pos = QCursor.pos() - QPoint(5, 0)
    event_filter.eventFilter(widget, QEvent(QEvent.Type.HoverMove))
    assert event_filter._timer.isActive() is True

    event_filter._timer.timeout.emit()
    event_filter._timer.stop()  # a real timeout stops a single-shot timer
    assert shown == ["Hover help"]

    # Moving while the tip is up must not hide and re-show it.
    event_filter.eventFilter(widget, QEvent(QEvent.Type.HoverMove))
    assert event_filter._timer.isActive() is False
    assert shown == ["Hover help"]


def test_tooltip_lifetime_filter_only_suppresses_after_a_click(qapp, monkeypatch):
    from PyQt6.QtCore import QEvent
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    monkeypatch.setattr(
        app_module.QToolTip, "showText", lambda pos, text, widget=None: None
    )
    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)
    widget = QWidget()
    widget.setToolTip("Hover help")

    event_filter.eventFilter(widget, QEvent(QEvent.Type.Enter))
    event_filter._timer.timeout.emit()
    # A scroll hides the tip but leaves the hover armed: a small move brings
    # it back on the same 350 ms schedule instead of a long wake-up.
    event_filter.eventFilter(widget, QEvent(QEvent.Type.Wheel))
    assert event_filter._suppressed is None
    event_filter.eventFilter(widget, QEvent(QEvent.Type.HoverMove))
    assert event_filter._timer.isActive() is True

    # A click is different: the tip stays down until the pointer leaves.
    event_filter.eventFilter(widget, QEvent(QEvent.Type.MouseButtonPress))
    assert event_filter._suppressed is widget
    event_filter.eventFilter(widget, QEvent(QEvent.Type.HoverMove))
    assert event_filter._timer.isActive() is False


def test_tooltip_lifetime_filter_tracks_hover_after_polish(qapp):
    from PyQt6.QtCore import QEvent, Qt
    from PyQt6.QtWidgets import QWidget

    from kemonodownloader import app as app_module

    event_filter = app_module._TooltipLifetimeFilter(hide=lambda: None)
    widget = QWidget()

    event_filter.eventFilter(widget, QEvent(QEvent.Type.Polish))

    assert widget.testAttribute(Qt.WidgetAttribute.WA_Hover) is True


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
