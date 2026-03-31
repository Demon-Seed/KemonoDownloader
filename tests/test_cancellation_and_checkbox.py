from kemonodownloader import creator_downloader as cd


def test_checkbox_toggle_thread_checked(qapp):
    visible_posts = [("A", ("pA", None)), ("B", ("pB", None))]
    checked_urls = {"pA": False, "pB": False, "other": True}
    results = []
    thread = cd.CheckboxToggleThread(visible_posts, checked_urls, 2)
    thread.finished.connect(lambda checked, posts: results.append((checked, posts)))
    thread.run()
    assert results
    checked_map, posts = results[0]
    assert checked_map["pA"] is True and checked_map["pB"] is True
    assert "other" in posts


def test_checkbox_toggle_thread_unchecked(qapp):
    visible_posts = [("A", ("pA", None))]
    checked_urls = {"pA": True, "x": True}
    results = []
    thread = cd.CheckboxToggleThread(visible_posts, checked_urls, 0)
    thread.finished.connect(lambda checked, posts: results.append((checked, posts)))
    thread.run()
    assert results
    checked_map, posts = results[0]
    assert checked_map["pA"] is False
    assert "x" in posts


def test_cancellation_thread_terminate(monkeypatch, qapp):
    class Fast:
        def __init__(self):
            self._running = True
            self.stop_called = False

        def stop(self):
            self._running = False
            self.stop_called = True

        def isRunning(self):
            return self._running

    class Stubborn:
        def __init__(self):
            self.terminate_called = False
            self.wait_called = False

        def stop(self):
            pass

        def isRunning(self):
            return True if not self.terminate_called else False

        def terminate(self):
            self.terminate_called = True

        def wait(self):
            self.wait_called = True

    fast = Fast()
    stubborn = Stubborn()
    results = []
    logs = []

    # FastTime ensures the internal wait-loop exits immediately so termination branch runs
    class FastTime:
        def __init__(self):
            self.calls = 0

        def time(self):
            self.calls += 1
            if self.calls == 1:
                return 0.0
            return 1000.0

        def sleep(self, _):
            return None

    monkeypatch.setattr(cd, "time", FastTime())

    cthread = cd.CancellationThread([fast, stubborn])
    cthread.finished.connect(lambda: results.append(True))
    cthread.log.connect(lambda m, lvl: logs.append((m, lvl)))
    cthread.run()

    assert results
    assert hasattr(stubborn, "terminate_called") and stubborn.terminate_called
    assert stubborn.wait_called
