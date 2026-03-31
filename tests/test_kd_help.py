from unittest.mock import MagicMock

from PyQt6.QtWidgets import QLabel

from kemonodownloader.kd_help import HelpTab


def test_help_tab_renders_and_updates(qapp, monkeypatch):
    # Make translations predictable (patch the name imported into the module)
    monkeypatch.setattr("kemonodownloader.kd_help.translate", lambda s, *a: f"tr:{s}")

    class MockSettings:
        language_changed = MagicMock()
        font_changed = MagicMock()

        def get_font(self):
            return "Arial"

    class MockParent:
        def __init__(self):
            self.settings_tab = MockSettings()

    parent = MockParent()
    tab = HelpTab(parent)
    try:
        labels = tab.findChildren(QLabel)
        assert any("tr:help_title" in lbl.text() for lbl in labels)

        # Trigger a font change handler and refresh UI
        tab._on_font_changed("Courier")
        tab.refresh_ui()

        labels_after = tab.findChildren(QLabel)
        assert any("tr:help_title" in lbl.text() for lbl in labels_after)
    finally:
        tab.deleteLater()
