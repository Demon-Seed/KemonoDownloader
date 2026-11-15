"""The Settings tab can empty the disposable preview cache."""

from PyQt6.QtWidgets import QMessageBox

from kemonodownloader import kd_paths, kd_settings as ks
from kemonodownloader.kd_language import translate


class _Parent:
    def __init__(self, tmp_path):
        self.base_folder = str(tmp_path / "base")
        self.download_folder = str(tmp_path / "base" / "Downloads")
        self.cache_folder = str(tmp_path / "cache")
        self.other_files_folder = str(tmp_path / "other")

    def log(self, message):
        pass

    def ensure_folders_exist(self):
        pass


def _make_settings(qapp, tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(kd_paths, "cache_dir", lambda configured=None: str(cache_dir))
    return ks.SettingsTab(_Parent(tmp_path)), cache_dir


def test_clear_cache_asks_then_removes_the_entries(qapp, tmp_path, monkeypatch):
    asked = []
    shown = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: (
            asked.append((args[1], args[2])),
            QMessageBox.StandardButton.Yes,
        )[1],
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: shown.append((args[1], args[2])),
    )

    tab, cache_dir = _make_settings(qapp, tmp_path, monkeypatch)
    entry = cache_dir / ("a" * 32 + ".png")
    entry.write_bytes(b"x" * 10)

    try:
        tab.clear_cache_button.click()

        assert not entry.exists()
        assert asked == [
            (
                translate("confirm_clear_cache_title"),
                translate("confirm_clear_cache_message"),
            )
        ]
        assert shown == [
            (
                translate("cache_cleared_title"),
                translate("cache_cleared_text", 1, "10 B"),
            )
        ]
    finally:
        tab.deleteLater()


def test_clear_cache_no_keeps_every_entry(qapp, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *args, **kwargs: shown.append(args)
    )

    tab, cache_dir = _make_settings(qapp, tmp_path, monkeypatch)
    entry = cache_dir / ("b" * 32 + ".jpg")
    entry.write_bytes(b"keep")

    try:
        tab.clear_cache_button.click()

        assert entry.exists()
        assert shown == []
    finally:
        tab.deleteLater()


def test_clear_cache_reports_an_already_empty_folder(qapp, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args, **kwargs: shown.append((args[1], args[2])),
    )

    tab, _cache_dir = _make_settings(qapp, tmp_path, monkeypatch)

    try:
        tab.clear_cache_button.click()

        assert shown == [
            (translate("cache_cleared_title"), translate("cache_empty_text"))
        ]
    finally:
        tab.deleteLater()


def test_clear_cache_failure_is_reported(qapp, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append((args[1], args[2])),
    )

    def boom(cache_dir):
        raise OSError("locked")

    monkeypatch.setattr(ks, "clear_preview_cache", boom)

    tab, _cache_dir = _make_settings(qapp, tmp_path, monkeypatch)

    try:
        tab.clear_cache_button.click()

        assert warnings == [
            (
                translate("cache_clear_failed_title"),
                translate("cache_clear_failed", "locked"),
            )
        ]
    finally:
        tab.deleteLater()


def test_clear_cache_button_is_labelled(qapp, tmp_path, monkeypatch):
    tab, _cache_dir = _make_settings(qapp, tmp_path, monkeypatch)
    try:
        assert tab.clear_cache_button.text() == translate("clear_cache")
        assert tab.clear_cache_button.toolTip() == translate("clear_cache_tooltip")
    finally:
        tab.deleteLater()
