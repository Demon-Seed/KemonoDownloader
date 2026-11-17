import gc
import os
import sys
from pathlib import Path

import pytest

# Add the src directory to the python path
src_path = Path(__file__).parent.parent / "src"
sys.path.append(str(src_path))

# Hold a strong reference so the QApplication is not garbage-collected.
_qapp_instance = None


def pytest_configure(config):
    """Create a QApplication early so modules that import Qt at import-time can succeed.

    This runs before collection, preventing ImportError during test collection on headless CI.
    The offscreen platform is set via pyproject.toml [tool.pytest.ini_options]
    qt_qpa_platform = "offscreen", but we also apply it here as a safety net.
    """
    global _qapp_instance
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        import faulthandler

        from PyQt6.QtWidgets import QApplication

        # Enable faulthandler to get native tracebacks on crashes (useful for C-level faults)
        try:
            faulthandler.enable()
        except Exception:
            pass

        if QApplication.instance() is None:
            _qapp_instance = QApplication([])
    except Exception:
        # If PyQt is not available, allow tests to fail later rather than crash here.
        pass


# NOTE: No custom ``qapp`` fixture here.  pytest-qt provides a session-scoped
# ``qapp`` fixture that correctly manages the QApplication lifecycle.  Defining
# a function-scoped override previously shadowed it and could return None when
# the early QApplication created above was garbage-collected.


@pytest.fixture(autouse=True)
def work_in_tmp_path(tmp_path, monkeypatch):
    """Run every test from its own temporary directory.

    A mock or a stray relative path then writes under ``tmp_path`` instead of
    the repository root (that is how the nested ``MagicMock/`` tree got there).
    """
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture(autouse=True)
def isolate_qsettings(tmp_path, monkeypatch):
    """Redirect every QSettings created by kd_settings to a temp INI.

    ``SettingsTab.__init__`` opens ``QSettings("VoxDroid", "KemonoDownloader")``,
    which on Windows is the user's real registry key. Tests exercise
    ``confirm_and_apply_settings()`` / ``save_settings()``, so without this
    redirection every suite run overwrites the real application settings.
    Monkeypatching the class keeps the whole suite hermetic.

    The instance-level ``isolated_settings`` fixture below is superseded by
    this one; new tests should simply rely on the autouse isolation.
    """
    from PyQt6.QtCore import QSettings as RealQSettings

    from kemonodownloader import kd_settings as kd_settings_mod

    ini_path = str(tmp_path / "kd_settings.ini")

    def factory(*args, **kwargs):
        return RealQSettings(ini_path, RealQSettings.Format.IniFormat)

    monkeypatch.setattr(kd_settings_mod, "QSettings", factory)
    yield ini_path


@pytest.fixture(autouse=True)
def isolate_program_data(tmp_path, monkeypatch):
    """Keep the suite out of the real per-user data folder.

    ``kd_paths`` resolves Cache/ and Other Files/ from the Data Directory, which
    defaults to the user's AppData. Every path lookup reads this override, so
    tests can never create or touch the real one.
    """
    from kemonodownloader import kd_paths

    monkeypatch.setenv(kd_paths.DATA_DIR_ENV, str(tmp_path / "program_data"))
    yield


@pytest.fixture()
def isolated_hash_dir(tmp_path):
    """Return a temp directory suitable for HashDB tests."""
    return str(tmp_path / "hash_store")


@pytest.fixture(autouse=True)
def offline_domain_list(monkeypatch):
    """Pin domain discovery to the bundled list.

    ``get_domains()`` otherwise fetches the list from GitHub once per process,
    which makes tests depend on the network and on the remote file's order.
    """
    from kemonodownloader import domain_config

    monkeypatch.setattr(
        domain_config,
        "_domains_cache",
        list(domain_config._FALLBACK_DOMAINS),
        raising=False,
    )


@pytest.fixture(autouse=True)
def reset_pawchive_request_gate():
    """Clear the download gate's spacing between tests.

    The gate is process-wide by design (it paces real runs), so without this
    a test that downloads several Pawchive files would wait 250 ms per file
    for no reason.
    """
    from kemonodownloader import download_utils

    download_utils.reset_pawchive_gate()
    download_utils.clear_direct_urls()
    yield
    download_utils.reset_pawchive_gate()
    download_utils.clear_direct_urls()


@pytest.fixture(autouse=True)
def offline_creator_name_lookups(monkeypatch):
    """Keep the queue's decorative profile lookups off the network in tests.

    Adding a creator asks the API for that creator's display name. Tests build
    tabs constantly, so the worker is replaced with a no-op here; the worker
    itself is exercised directly with a fake session where it matters.
    """
    from PyQt6.QtCore import QObject, pyqtSignal

    from kemonodownloader import creator_downloader as cd

    class OfflineCreatorNameLookup(QObject):
        found = pyqtSignal(str, str)
        finished = pyqtSignal()

        def __init__(self, creator_url, settings):
            super().__init__()
            self.creator_url = creator_url
            self.settings = settings

        def start(self):
            pass

        def isRunning(self):
            return False

        def stop(self):
            pass

        def wait(self, _timeout=0):
            return True

        def deleteLater(self):
            pass

    monkeypatch.setattr(cd, "CreatorNameLookupThread", OfflineCreatorNameLookup)


@pytest.fixture(autouse=True)
def cleanup_qt_threads_after_test():
    """Best-effort cleanup for leaked QThreads.

    Some tests intentionally exercise cancellation/error paths and may leave
    thread objects alive briefly. On Linux CI, a surviving running QThread can
    trigger a native abort ("QThread: Destroyed while thread is still running").
    This fixture aggressively stops and joins any running QThread wrappers
    after each test to keep the process stable.
    """
    yield

    try:
        from PyQt6.QtCore import QCoreApplication, QThread
    except Exception:
        return

    app = QCoreApplication.instance()
    if app is not None:
        try:
            app.processEvents()
        except Exception:
            pass

    for obj in list(gc.get_objects()):
        try:
            if not isinstance(obj, QThread):
                continue
            if not obj.isRunning():
                continue

            # Cooperatively request shutdown first.
            try:
                if hasattr(obj, "stop"):
                    obj.stop()
            except Exception:
                pass
            try:
                obj.requestInterruption()
            except Exception:
                pass
            try:
                obj.quit()
            except Exception:
                pass
            try:
                obj.wait(2000)
            except Exception:
                pass

            # Last resort: terminate stubborn workers.
            try:
                if obj.isRunning():
                    obj.terminate()
                    obj.wait(1000)
            except Exception:
                pass
        except Exception:
            # Ignore invalid/deleted sip wrappers during GC traversal.
            pass

    if app is not None:
        try:
            app.processEvents()
        except Exception:
            pass
