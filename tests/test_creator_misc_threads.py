from types import SimpleNamespace

from kemonodownloader.creator_downloader import (
    CheckboxToggleThread,
    FilterThread,
    PostPopulationThread,
    sanitize_filename,
)


def test_sanitize_filename_basic():
    assert sanitize_filename("") == "unnamed"
    s = sanitize_filename(' bad<>:"/\\|?*name.. ')
    # No invalid characters should remain
    for ch in '<>:"/\\|?*':
        assert ch not in s
    assert s == s.strip("_")


def test_post_population_thread_emits_map():
    detected = [("Title A", ("1", "u1")), ("Title B", ("2", "u2"))]
    thread = PostPopulationThread(detected)
    captured = []
    thread.log = SimpleNamespace(emit=lambda *a, **k: None)
    thread.finished = SimpleNamespace(emit=lambda m, lst: captured.append((m, lst)))
    thread.run()
    assert captured
    post_map, posts = captured[0]
    assert any("Title A (ID: 1)" in k for k in post_map.keys())


def test_filter_thread_filters_and_emits():
    all_detected = [("Title One", ("1", "u1")), ("Other", ("2", "u2"))]
    checked = {"1": True, "2": False}
    thread = FilterThread(all_detected, checked, search_text="Title")
    captured = []
    thread.log = SimpleNamespace(emit=lambda *a, **k: None)
    thread.finished = SimpleNamespace(emit=lambda items: captured.append(items))
    thread.run()
    assert captured
    filtered = captured[0]
    assert any(item[1] == "1" for item in filtered)


def test_checkbox_toggle_thread_updates_states():
    visible = [("Title", ("1", "u1"))]
    checked = {"1": False, "2": True}
    thread = CheckboxToggleThread(visible, checked, check_all_state=2)
    captured = []
    thread.log = SimpleNamespace(emit=lambda *a, **k: None)
    thread.finished = SimpleNamespace(
        emit=lambda new_checked, posts: captured.append((new_checked, posts))
    )
    thread.run()
    assert captured
    new_checked, posts = captured[0]
    assert new_checked["1"] is True
    assert set(posts) == {"1", "2"}
