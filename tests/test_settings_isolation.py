"""Guard that the test suite never writes to the real application settings.

``SettingsTab.__init__`` opens ``QSettings("VoxDroid", "KemonoDownloader")``,
which on Windows is the live registry key. ``tests/conftest.py`` redirects
that class to a temp INI (``isolate_qsettings``); this test is the canary
that fails if the redirection is ever removed, so a test run can never
overwrite the user's Settings page again.
"""

import ast
import pathlib


def test_settings_tab_uses_the_isolated_store(qapp):
    from kemonodownloader.kd_settings import SettingsTab

    st = SettingsTab(None)
    try:
        file_name = st.qsettings.fileName()
        assert "kd_settings.ini" in file_name
        assert "VoxDroid" not in file_name

        st.qsettings.setValue("isolation_sentinel", 1)
        assert st.qsettings.value("isolation_sentinel", type=int) == 1
    finally:
        st.deleteLater()


def _real_settings_call_lines(path):
    """Return the line numbers where *path* builds the real settings store."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name != "QSettings":
            continue
        first_args = [
            arg.value for arg in node.args[:2] if isinstance(arg, ast.Constant)
        ]
        if first_args == ["VoxDroid", "KemonoDownloader"]:
            hits.append(node.lineno)
    return hits


def test_no_test_module_constructs_the_real_settings_store():
    """Fail if any test binds the real QSettings class directly.

    A module-level ``from PyQt6.QtCore import QSettings`` resolved at import
    time bypasses the ``isolate_qsettings`` fixture, which is exactly how
    earlier suite runs emptied the user's Settings page.
    """
    offenders = {}
    for path in pathlib.Path(__file__).resolve().parent.glob("test_*.py"):
        hits = _real_settings_call_lines(path)
        if hits:
            offenders[path.name] = hits
    assert offenders == {}

