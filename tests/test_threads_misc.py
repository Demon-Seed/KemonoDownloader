from types import SimpleNamespace

from kemonodownloader.creator_downloader import (
    CheckboxToggleThread,
    FilterThread,
    PostPopulationThread,
    ValidationThread,
)


class FakeResponse:
    def __init__(self, status_code=200, text="kemono site content"):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, response):
        self._response = response

    def get(self, *args, **kwargs):
        return self._response


def test_post_population_thread_emits_map():
    detected = [("T1", ("1", "http://img")), ("T2", ("2", None))]
    thread = PostPopulationThread(detected)
    results = {}

    def cb(mapping, posts):
        results["map"] = mapping
        results["posts"] = posts

    thread.finished.connect(cb)
    thread.run()

    assert "map" in results
    assert len(results["map"]) == 2


def test_filter_thread_filters_by_search_and_checked():
    all_detected = [("Alpha Post", ("a", None)), ("Beta Post", ("b", None))]
    checked = {"a": True, "b": False}
    thread = FilterThread(all_detected, checked, search_text="Alpha")
    results = {}

    def cb(filtered):
        results["filtered"] = filtered

    thread.finished.connect(cb)
    thread.run()

    assert "filtered" in results
    assert any(item[0].startswith("Alpha") for item in results["filtered"])


def test_validation_thread_success(monkeypatch):
    # Provide a fake session whose response text contains the domain check
    fake_resp = FakeResponse(status_code=200, text="Welcome to kemono")
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSession(fake_resp),
    )

    settings = SimpleNamespace(api_request_max_retries=1, settings_tab=None)
    thread = ValidationThread("https://kemono.cr/fanbox/user/1", settings)
    out = {}

    def cb(result):
        out["result"] = result

    thread.result.connect(cb)
    thread.run()

    assert out.get("result") is True


def test_checkbox_toggle_thread_updates_checked_state():
    visible = [("P1", ("1", None)), ("P2", ("2", None))]
    checked = {"1": False, "2": False}
    # 2 represents Qt.CheckState.Checked
    thread = CheckboxToggleThread(visible, checked, check_all_state=2)
    out = {}

    def cb(new_checked, posts_to_download):
        out["checked"] = new_checked
        out["posts"] = posts_to_download

    thread.finished.connect(cb)
    thread.run()

    assert out["checked"]["1"] is True
    assert 1 in out["posts"] or "1" in out["posts"]
