"""Tests for the global exception hook in :mod:`kd_errors`."""

import sys
from types import SimpleNamespace

from kemonodownloader import kd_errors


class _FakeApplication:
    @staticmethod
    def instance():
        return object()


class _FakeMessageBox:
    class Icon:
        Critical = "critical"

    def __init__(self, parent=None):
        self.parent = parent

    def setIcon(self, icon):
        self.icon = icon

    def setWindowTitle(self, title):
        self.title = title

    def setText(self, text):
        self.text = text

    def setInformativeText(self, text):
        self.informative = text

    def setDetailedText(self, text):
        self.details = text

    def exec(self):
        return 0


def _crash(error):
    try:
        raise error
    except type(error):
        return sys.exc_info()


def test_handle_exception_prints_and_reports(monkeypatch, capsys):
    reports = []
    reporter = SimpleNamespace(
        report=SimpleNamespace(
            emit=lambda summary, details: reports.append((summary, details))
        )
    )
    monkeypatch.setattr(kd_errors, "_reporter", reporter)
    monkeypatch.setattr(kd_errors, "QApplication", _FakeApplication)

    kd_errors.handle_exception(*_crash(ValueError("boom")))

    assert "ValueError: boom" in capsys.readouterr().err
    assert len(reports) == 1
    summary, details = reports[0]
    assert summary == "ValueError: boom"
    assert "Traceback (most recent call last)" in details


def test_keyboard_interrupt_keeps_the_default_behaviour(monkeypatch):
    calls = []
    emitted = []
    monkeypatch.setattr(sys, "__excepthook__", lambda *args: calls.append(args))
    monkeypatch.setattr(
        kd_errors,
        "_reporter",
        SimpleNamespace(report=SimpleNamespace(emit=lambda *a: emitted.append(a))),
    )

    kd_errors.handle_exception(*_crash(KeyboardInterrupt()))

    assert len(calls) == 1
    assert emitted == []


def test_windowed_build_without_stderr_does_not_raise(monkeypatch):
    monkeypatch.setattr(kd_errors, "_reporter", None)
    monkeypatch.setattr(kd_errors.sys, "stderr", None)

    # Must not raise: a windowed build has no console.
    kd_errors.handle_exception(*_crash(RuntimeError("silent")))


def test_install_is_idempotent_and_sets_the_hook(monkeypatch, qapp):
    original_hook = sys.excepthook
    monkeypatch.setattr(kd_errors, "_reporter", None)
    try:
        kd_errors.install_exception_hook()
        first = kd_errors._reporter
        kd_errors.install_exception_hook()

        assert sys.excepthook is kd_errors.handle_exception
        assert kd_errors._reporter is first
    finally:
        sys.excepthook = original_hook
        kd_errors._reporter = None


def test_only_one_dialog_is_shown_at_a_time(qapp, monkeypatch):
    shown = []

    class ReentrantMessageBox(_FakeMessageBox):
        def exec(self):
            shown.append(self.text)
            # An error raised while the dialog is open must not stack dialogs.
            reporter._show("second", "second details")
            return 0

    class FakeApplication:
        @staticmethod
        def activeWindow():
            return None

    monkeypatch.setattr(kd_errors, "QMessageBox", ReentrantMessageBox)
    monkeypatch.setattr(kd_errors, "QApplication", FakeApplication)

    reporter = kd_errors._ErrorReporter()
    reporter._show("first", "first details")

    assert len(shown) == 1
