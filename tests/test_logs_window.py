import os

from PyQt6.QtWidgets import QTextEdit

from kemonodownloader.creator_downloader import LogsWindow


def test_logs_window_download_and_clear(qtbot, tmp_path, monkeypatch):
    from PyQt6.QtWidgets import QWidget

    parent = QWidget()
    parent.creator_console = QTextEdit()
    parent.creator_console.setPlainText("line1\nline2")
    recorded = []
    parent.append_log_to_console = lambda msg, lvl=None: recorded.append((msg, lvl))

    lw = LogsWindow(parent)

    # Ensure logs_display has current content
    lw.logs_display.setPlainText(parent.creator_console.toPlainText())

    save_path = str(tmp_path / "out_logs.txt")

    # Monkeypatch the QFileDialog.getSaveFileName used inside download_logs
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QFileDialog.getSaveFileName", lambda *a, **k: (save_path, None)
    )

    lw.download_logs()

    assert os.path.exists(save_path)
    with open(save_path, "r", encoding="utf-8") as fh:
        content = fh.read()
    assert "line1" in content

    # Test clear_logs clears both window and parent console
    lw.logs_display.setPlainText("some")
    parent.creator_console.setPlainText("some")
    lw.clear_logs()
    assert lw.logs_display.toPlainText() == ""
    assert parent.creator_console.toPlainText() == ""
