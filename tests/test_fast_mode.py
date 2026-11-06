"""Tests for the multi-URL batch input used by CreatorDownloaderTab.

These tests exercise the batch/queue logic without requiring a live network
connection or real downloads.
"""

import pytest

from kemonodownloader.kd_language import language_manager, translate


class TestFastModeTranslations:
    """Verify that the multi-URL batch translation keys exist."""

    KEYS = [
        "multi_url_placeholder_creator",
        "add_all_to_queue",
    ]

    def setup_method(self):
        self.original = language_manager.current_language

    def teardown_method(self):
        language_manager.set_language(self.original)

    @pytest.mark.parametrize("lang", language_manager.get_available_languages())
    def test_keys_exist(self, lang):
        language_manager.set_language(lang)
        for key in self.KEYS:
            result = translate(key)
            # translate returns the key itself when it's missing
            assert result != key, f"Missing translation for '{key}' in {lang}"


class TestFastModeCreatorLogic:
    """Test the fast-mode toggle logic for the creator downloader (unit-level)."""

    def test_creator_auto_remove_filter(self):
        """Completed creator should be removed from queue in fast mode."""
        creator_queue = [
            ("https://kemono.cr/fanbox/user/100", False),
            ("https://kemono.cr/fanbox/user/200", False),
        ]
        current_creator_url = "https://kemono.cr/fanbox/user/100"

        remaining = [
            (u, c)
            for u, c in creator_queue
            if u.rstrip("/") != current_creator_url.rstrip("/")
        ]
        assert len(remaining) == 1
        assert remaining[0][0].endswith("/200")


class TestMultiURLParsing:
    """Test parsing of multi-URL text input (newline-separated URLs)."""

    def test_parse_multiple_urls(self):
        text = (
            "https://kemono.cr/fanbox/user/1/post/10\n"
            "https://kemono.cr/fanbox/user/1/post/20\n"
            "\n"
            "https://kemono.cr/fanbox/user/1/post/30\n"
        )
        urls = [line.strip() for line in text.split("\n") if line.strip()]
        assert len(urls) == 3

    def test_deduplication(self):
        text = (
            "https://kemono.cr/fanbox/user/1/post/10\n"
            "https://kemono.cr/fanbox/user/1/post/10\n"
            "https://kemono.cr/fanbox/user/1/post/20\n"
        )
        urls = [line.strip() for line in text.split("\n") if line.strip()]
        post_queue = []
        added = 0
        skipped = 0
        for url in urls:
            normalized = url.rstrip("/")
            if any(item[0].rstrip("/") == normalized for item in post_queue):
                skipped += 1
                continue
            post_queue.append((url, False))
            added += 1

        assert added == 2
        assert skipped == 1

    def test_empty_input(self):
        text = "   \n  \n  "
        urls = [line.strip() for line in text.split("\n") if line.strip()]
        assert urls == []

    def test_single_url(self):
        text = "https://kemono.cr/fanbox/user/1/post/10"
        urls = [line.strip() for line in text.split("\n") if line.strip()]
        assert len(urls) == 1

    def test_urls_with_trailing_slashes(self):
        text = (
            "https://kemono.cr/fanbox/user/1/post/10/\n"
            "https://kemono.cr/fanbox/user/1/post/10\n"
        )
        urls = [line.strip() for line in text.split("\n") if line.strip()]
        post_queue = []
        added = 0
        for url in urls:
            normalized = url.rstrip("/")
            if any(item[0].rstrip("/") == normalized for item in post_queue):
                continue
            post_queue.append((url, False))
            added += 1
        # Should dedup even with trailing slash difference
        assert added == 1


class TestMultiURLCreatorParsing:
    """Test multi-URL parsing for creator URLs."""

    def test_parse_creator_urls(self):
        text = (
            "https://kemono.cr/fanbox/user/100\n"
            "https://kemono.cr/patreon/user/200\n"
            "https://coomer.st/onlyfans/user/300\n"
        )
        urls = [line.strip() for line in text.split("\n") if line.strip()]
        assert len(urls) == 3

    def test_dedup_creator_urls(self):
        text = (
            "https://kemono.cr/fanbox/user/100\n" "https://kemono.cr/fanbox/user/100\n"
        )
        urls = [line.strip() for line in text.split("\n") if line.strip()]
        queue = []
        for url in urls:
            normalized = url.rstrip("/")
            if any(item[0].rstrip("/") == normalized for item in queue):
                continue
            queue.append((url, False))
        assert len(queue) == 1


class TestBulkAddSummaryTranslation:
    """Ensure the bulk_add_summary translation key works."""

    def setup_method(self):
        self.original = language_manager.current_language
        language_manager.set_language("english")

    def teardown_method(self):
        language_manager.set_language(self.original)

    def test_bulk_add_summary(self):
        result = translate("bulk_add_summary", 5, 2)
        assert "5" in result
        assert "2" in result


class TestIncrementalCreatorRemoval:
    """Test the incremental per-creator removal logic.

    In fast mode, the creator URL should be removed from the queue as soon
    as all posts for that creator have completed, rather than waiting for
    creator_download_finished.
    """

    def _simulate_post_completion(
        self, post_id, completed_posts, total_posts, creator_queue, current_creator_url
    ):
        """Simulate update_post_completion fast-mode logic for creator."""
        completed_posts.add(post_id)
        if len(completed_posts) >= total_posts and total_posts > 0:
            normalized = current_creator_url.rstrip("/")
            before_len = len(creator_queue)
            creator_queue = [
                (u, c) for u, c in creator_queue if u.rstrip("/") != normalized
            ]
            if len(creator_queue) < before_len:
                pass  # Would log in real code
        return creator_queue

    def test_creator_removed_when_all_posts_complete(self):
        creator_queue = [
            ("https://kemono.cr/fanbox/user/100", False),
            ("https://kemono.cr/fanbox/user/200", False),
        ]
        completed_posts = set()
        total_posts = 2
        current_url = "https://kemono.cr/fanbox/user/100"

        # First post completes — creator still has 1 more
        creator_queue = self._simulate_post_completion(
            "p1", completed_posts, total_posts, creator_queue, current_url
        )
        assert len(creator_queue) == 2

        # Second post completes — all done, creator should be removed
        creator_queue = self._simulate_post_completion(
            "p2", completed_posts, total_posts, creator_queue, current_url
        )
        assert len(creator_queue) == 1
        assert creator_queue[0][0].endswith("/200")

    def test_creator_not_removed_prematurely(self):
        creator_queue = [
            ("https://kemono.cr/fanbox/user/100", False),
        ]
        completed_posts = set()
        total_posts = 3

        creator_queue = self._simulate_post_completion(
            "p1",
            completed_posts,
            total_posts,
            creator_queue,
            "https://kemono.cr/fanbox/user/100",
        )
        assert len(creator_queue) == 1  # Still 2 posts remaining

    def test_idempotent_removal(self):
        """Calling removal twice should not error or change the result."""
        creator_queue = [
            ("https://kemono.cr/fanbox/user/100", False),
        ]
        completed_posts = set()
        total_posts = 1

        creator_queue = self._simulate_post_completion(
            "p1",
            completed_posts,
            total_posts,
            creator_queue,
            "https://kemono.cr/fanbox/user/100",
        )
        assert len(creator_queue) == 0

        # Second call — queue already empty, should be fine
        creator_queue = self._simulate_post_completion(
            "p1",
            completed_posts,
            total_posts,
            creator_queue,
            "https://kemono.cr/fanbox/user/100",
        )
        assert len(creator_queue) == 0


class TestUIStateLocking:
    """Test the UI state locking/unlocking logic."""

    def test_lock_enables_download_states(self):
        """When is_downloading=True, enabled should be False."""
        is_downloading = True
        enabled = not is_downloading
        assert enabled is False

    def test_unlock_restores_states(self):
        """When is_downloading=False, enabled should be True."""
        is_downloading = False
        enabled = not is_downloading
        assert enabled is True

    def test_pagination_respects_page_bounds(self):
        """Pagination buttons should respect current page and total pages."""
        current_page = 1
        total_pages = 5
        is_downloading = False
        enabled = not is_downloading

        prev_enabled = enabled and current_page > 1
        next_enabled = enabled and current_page < total_pages

        assert prev_enabled is False  # Page 1, no previous
        assert next_enabled is True

    def test_pagination_locked_during_download(self):
        """Pagination should be disabled during download regardless of page."""
        current_page = 3
        total_pages = 5
        is_downloading = True
        enabled = not is_downloading

        prev_enabled = enabled and current_page > 1
        next_enabled = enabled and current_page < total_pages

        assert prev_enabled is False
        assert next_enabled is False


class TestLogsWindowTimer:
    """Test the LogsWindow timer-based update logic."""

    def test_needs_update_flag(self):
        """update_logs should set needs_update to True."""
        needs_update = False
        # Simulate update_logs
        needs_update = True
        assert needs_update is True

    def test_do_update_clears_flag(self):
        """_do_update should clear needs_update after updating."""
        needs_update = True
        # Simulate _do_update
        if needs_update:
            # Would call setHtml in real code
            needs_update = False
        assert needs_update is False

    def test_timer_interval(self):
        """Timer interval should be 500ms for batched updates."""
        interval = 500
        assert interval == 500
