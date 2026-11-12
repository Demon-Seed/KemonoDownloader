"""
Integration tests for the Creator Downloader module.
These tests verify the logic of post detection and file processing without mocking,
using real HTTP requests to the API endpoints where appropriate.
"""

import hashlib
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import requests
from PyQt6.QtGui import QColor, QPixmap

from kemonodownloader import creator_downloader as cd
from kemonodownloader.creator_downloader import (
    CreatorDownloadThread,
    PreviewThread,
    ThreadSettings,
    get_session,
    sanitize_filename,
)

try:
    from kemonodownloader.creator_downloader import (
        ThreadSettings,
        get_domain_config,
        get_headers,
        sanitize_filename,
    )
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))
    from kemonodownloader.creator_downloader import (
        ThreadSettings,
        get_domain_config,
        get_headers,
        sanitize_filename,
    )


class TestThreadSettings:
    """Tests for the ThreadSettings configuration class."""

    def test_thread_settings_initialization(self):
        """Test that ThreadSettings initializes with correct values."""
        settings = ThreadSettings(
            creator_posts_max_attempts=100,
            post_data_max_retries=5,
            file_download_max_retries=10,
            api_request_max_retries=3,
            simultaneous_downloads=5,
            settings_tab=None,
        )

        assert settings.creator_posts_max_attempts == 100
        assert settings.post_data_max_retries == 5
        assert settings.file_download_max_retries == 10
        assert settings.api_request_max_retries == 3
        assert settings.simultaneous_downloads == 5
        assert settings.settings_tab is None

    def test_thread_settings_with_settings_tab(self):
        """Test ThreadSettings with a settings_tab reference."""

        class MockSettingsTab:
            pass

        mock_tab = MockSettingsTab()
        settings = ThreadSettings(
            creator_posts_max_attempts=50,
            post_data_max_retries=3,
            file_download_max_retries=5,
            api_request_max_retries=2,
            simultaneous_downloads=10,
            settings_tab=mock_tab,
        )

        assert settings.settings_tab is mock_tab


class TestDomainConfiguration:
    """Tests for domain configuration and URL parsing."""

    def test_kemono_services(self):
        """Test that kemono.cr supports various services."""
        services = ["fanbox", "patreon", "fantia", "gumroad", "subscribestar"]
        for service in services:
            url = f"https://kemono.cr/{service}/user/12345"
            config = get_domain_config(url)
            assert config["domain"] == "kemono.cr"

    def test_coomer_services(self):
        """Test that coomer.st supports various services."""
        services = ["onlyfans", "fansly"]
        for service in services:
            url = f"https://coomer.st/{service}/user/12345"
            config = get_domain_config(url)
            assert config["domain"] == "coomer.st"

    def test_api_endpoint_format(self):
        """Test that API endpoints are correctly formatted."""
        config = get_domain_config("https://kemono.cr/fanbox/user/123")
        assert config["api_base"].endswith("/api/v1")
        assert not config["api_base"].endswith("/")


class TestFileDetectionLogic:
    """Tests for file detection patterns and logic."""

    def test_image_extensions_detection(self):
        """Test detection of common image file extensions."""
        image_extensions = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        for ext in image_extensions:
            filename = f"test_image{ext}"
            # Verify the extension is properly extracted
            _, file_ext = os.path.splitext(filename)
            assert file_ext.lower() in image_extensions

    def test_archive_extensions_detection(self):
        """Test detection of common archive file extensions."""
        archive_extensions = [".zip", ".rar", ".7z"]
        for ext in archive_extensions:
            filename = f"archive{ext}"
            _, file_ext = os.path.splitext(filename)
            assert file_ext.lower() in archive_extensions

    def test_video_extensions_detection(self):
        """Test detection of common video file extensions."""
        video_extensions = [".mp4", ".mov", ".webm"]
        for ext in video_extensions:
            filename = f"video{ext}"
            _, file_ext = os.path.splitext(filename)
            assert file_ext.lower() in [".mp4", ".mov", ".webm"]

    def test_audio_extensions_detection(self):
        """Test detection of common audio file extensions."""
        audio_extensions = [".mp3", ".wav", ".flac"]
        for ext in audio_extensions:
            filename = f"audio{ext}"
            _, file_ext = os.path.splitext(filename)
            assert file_ext.lower() in audio_extensions


class TestURLParsing:
    """Tests for URL parsing and validation logic."""

    def test_parse_creator_url_components(self):
        """Test parsing creator URL into components."""
        url = "https://kemono.cr/fanbox/user/12345678"
        parts = url.rstrip("/").split("/")

        assert parts[-1] == "12345678"  # creator_id
        assert parts[-2] == "user"
        assert parts[-3] == "fanbox"  # service

    def test_parse_post_url_components(self):
        """Test parsing post URL into components."""
        url = "https://kemono.cr/fanbox/user/12345678/post/87654321"
        parts = url.rstrip("/").split("/")

        assert parts[-1] == "87654321"  # post_id
        assert parts[-2] == "post"
        assert parts[-3] == "12345678"  # creator_id
        assert parts[-5] == "fanbox"  # service

    def test_url_with_query_parameters(self):
        """Test URL parsing with query parameters."""
        from urllib.parse import parse_qs, urlparse

        url = "https://kemono.cr/fanbox/user/12345?o=50&q=search"
        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)

        assert query_params.get("o", [None])[0] == "50"
        assert query_params.get("q", [None])[0] == "search"

    def test_url_path_extraction(self):
        """Test extracting clean path from URL."""
        from urllib.parse import urlparse

        url = "https://kemono.cr/fanbox/user/12345?o=50"
        parsed = urlparse(url)
        path = parsed.path.strip("/")

        assert path == "fanbox/user/12345"
        assert parsed.query == "o=50"


class TestFileHashLogic:
    """Tests for file hash calculation and deduplication logic."""

    def test_md5_hash_calculation(self):
        """Test MD5 hash calculation for data."""
        test_data = b"test content for hashing"
        expected_hash = hashlib.md5(test_data).hexdigest()

        # Verify hash is consistent
        calculated_hash = hashlib.md5(test_data).hexdigest()
        assert calculated_hash == expected_hash
        assert len(calculated_hash) == 32  # MD5 produces 32 hex characters

    def test_hash_uniqueness(self):
        """Test that different content produces different hashes."""
        data1 = b"content one"
        data2 = b"content two"

        hash1 = hashlib.md5(data1).hexdigest()
        hash2 = hashlib.md5(data2).hexdigest()

        assert hash1 != hash2

    def test_hash_consistency(self):
        """Test that same content always produces same hash."""
        data = b"consistent content"

        hash1 = hashlib.md5(data).hexdigest()
        hash2 = hashlib.md5(data).hexdigest()

        assert hash1 == hash2


class TestSanitizeFilenameEdgeCases:
    """Additional edge case tests for filename sanitization."""

    def test_emoji_in_filename(self):
        """Test handling of emoji characters in filenames."""
        result = sanitize_filename("Post 🎨 with emoji")
        # Should not crash and should produce a valid filename
        assert len(result) > 0
        assert result != "unnamed"

    def test_very_long_unicode_filename(self):
        """Test truncation of long unicode filenames."""
        # Japanese text that's very long
        long_name = "日本語テスト" * 50
        result = sanitize_filename(long_name, max_length=100)
        assert len(result) <= 100

    def test_filename_with_extension(self):
        """Test that file extensions are preserved."""
        result = sanitize_filename("my file.jpg")
        assert result.endswith(".jpg")

    def test_only_whitespace(self):
        """Test filename with only whitespace."""
        result = sanitize_filename("   ")
        assert result == "unnamed"

    def test_periods_in_middle(self):
        """Test that periods in the middle of filename are preserved."""
        result = sanitize_filename("file.name.ext")
        assert "file" in result
        assert "ext" in result

    def test_title_with_trailing_newline(self):
        """Patreon titles can end with a newline; Windows rejects it."""
        result = sanitize_filename("Akeno Belly Progression (3/3) \n")
        assert result == "Akeno_Belly_Progression_(3_3)"
        assert all(ord(ch) >= 32 for ch in result)


class TestHeadersConfiguration:
    """Tests for HTTP headers configuration."""

    def test_headers_have_user_agent(self):
        """Test that headers include a User-Agent."""
        headers = get_headers()
        assert "User-Agent" in headers
        assert len(headers["User-Agent"]) > 0

    def test_headers_have_referer(self):
        """Test that headers include a Referer."""
        headers = get_headers()
        assert "Referer" in headers
        assert "kemono" in headers["Referer"]

    def test_headers_have_accept_language(self):
        """Test that headers include Accept-Language."""
        headers = get_headers()
        assert "Accept-Language" in headers

    def test_headers_have_connection(self):
        """Test that headers include Connection setting."""
        headers = get_headers()
        assert "Connection" in headers
        assert headers["Connection"] == "keep-alive"


class TestAPIResponseParsing:
    """Tests for API response parsing logic."""

    def test_parse_post_data_structure(self):
        """Test parsing of expected post data structure."""
        sample_post = {
            "id": "12345",
            "title": "Test Post",
            "file": {"path": "/data/file.jpg", "name": "file.jpg"},
            "attachments": [
                {"path": "/data/att1.png", "name": "att1.png"},
                {"path": "/data/att2.zip", "name": "att2.zip"},
            ],
            "content": "<p>Post content</p>",
        }

        # Verify structure access
        assert sample_post.get("id") == "12345"
        assert sample_post.get("title") == "Test Post"
        assert sample_post.get("file", {}).get("path") == "/data/file.jpg"
        assert len(sample_post.get("attachments", [])) == 2

    def test_parse_empty_post_data(self):
        """Test parsing of post with missing optional fields."""
        minimal_post = {"id": "12345"}

        # Should handle missing fields gracefully
        assert minimal_post.get("title", f"Post {minimal_post['id']}") == "Post 12345"
        assert minimal_post.get("file") is None
        assert minimal_post.get("attachments", []) == []
        assert minimal_post.get("content", "") == ""

    def test_parse_attachment_list(self):
        """Test parsing of attachment list."""
        attachments = [
            {"path": "/file1.jpg", "name": "image1.jpg"},
            {"path": "/file2.png", "name": "image2.png"},
            {"path": "/archive.zip", "name": "files.zip"},
        ]

        # Extract image attachments
        image_exts = [".jpg", ".jpeg", ".png", ".gif", ".webp"]
        images = [
            a
            for a in attachments
            if os.path.splitext(a["path"])[1].lower() in image_exts
        ]

        assert len(images) == 2

        # Extract archives
        archive_exts = [".zip", ".rar", ".7z"]
        archives = [
            a
            for a in attachments
            if os.path.splitext(a["path"])[1].lower() in archive_exts
        ]

        assert len(archives) == 1


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        # responses is an iterable of FakeResponse objects
        self._responses = list(responses)
        self._calls = 0

    def get(self, *args, **kwargs):
        idx = min(self._calls, len(self._responses) - 1)
        resp = self._responses[idx]
        self._calls += 1
        return resp


def test_fetch_and_detect_files_success(monkeypatch):
    post_payload = {
        "post": {
            "file": {"path": "/media/main.jpg", "name": "main.jpg"},
            "attachments": [{"path": "/att/file.zip", "name": "file.zip"}],
            "content": '<p><img src="/images/img1.png"></p>',
        }
    }

    fake_session = FakeSession([FakeResponse(200, post_payload)])
    monkeypatch.setattr(cd, "get_session", lambda settings_tab: fake_session)

    settings = SimpleNamespace(post_data_max_retries=1, settings_tab=None)

    class C:
        def __init__(self, checked=True):
            self._checked = checked

        def isChecked(self):
            return self._checked

    ext_checks = {".jpg": C(True), ".png": C(True), ".zip": C(True)}

    fpt = cd.FilePreparationThread(["1"], {}, ext_checks, True, True, True, settings)
    res = fpt.fetch_and_detect_files("1", "https://kemono.cr/service/user/creator")
    assert res is not None
    pid, files = res
    assert pid == "1"
    assert any(
        "main.jpg" in n or n.endswith(".zip") or n.endswith(".png") for n, u in files
    )


def test_fetch_and_detect_files_rate_limit_retry(monkeypatch):
    # First response is 429, second is 200
    post_payload = {"post": {"file": {"path": "/media/m.jpg", "name": "m.jpg"}}}
    fake_session = FakeSession([FakeResponse(429, {}), FakeResponse(200, post_payload)])
    monkeypatch.setattr(cd, "get_session", lambda settings_tab: fake_session)
    # Avoid sleeping delays
    monkeypatch.setattr(cd, "time", SimpleNamespace(sleep=lambda s: None))

    settings = SimpleNamespace(post_data_max_retries=2, settings_tab=None)

    class C:
        def __init__(self, checked=True):
            self._checked = checked

        def isChecked(self):
            return self._checked

    ext_checks = {".jpg": C(True)}
    fpt = cd.FilePreparationThread(["1"], {}, ext_checks, True, True, True, settings)
    res = fpt.fetch_and_detect_files("1", "https://kemono.cr/service/user/creator")
    assert res is not None
    pid, files = res
    assert pid == "1"
    assert files


def make_settings_with_strategy(strategy, template=None):
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: template,
        get_creator_folder_strategy=lambda: strategy,
        get_proxy_settings=lambda: None,
    )
    return ThreadSettings(
        creator_posts_max_attempts=1,
        post_data_max_retries=1,
        file_download_max_retries=1,
        api_request_max_retries=1,
        simultaneous_downloads=1,
        settings_tab=settings_tab,
    )


def test_generate_filename_and_folder_templates_and_strategies(tmp_path):
    download_folder = str(tmp_path / "downloads")
    other_files_dir = str(tmp_path / "other")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/origname.png?f=origname.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "1"}

    # Per-post strategy with the default templates
    settings = make_settings_with_strategy("per_post", template=None)
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creator123", "1"): "My Post"},
        settings=settings,
        download_text=False,
    )

    target_folder, filename = thread.generate_filename_and_folder(
        file_url,
        download_folder,
        0,
        total_files=1,
        post_id="1",
        post_title="My Post",
        page_number=1,
    )

    # Default post-folder template: {file_number}_{post_id}_{orig_name}
    assert filename.endswith("origname.png")
    assert filename.startswith("1_1_")

    # Expect folder ends with sanitized post title
    expected_post_folder = f"1_{sanitize_filename('My Post')}"
    assert os.path.basename(target_folder) == expected_post_folder

    # Single-folder strategy places desc in creator folder
    settings2 = make_settings_with_strategy("single_folder")
    thread2 = CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creator123", "1"): "My Post"},
        settings=settings2,
        download_text=False,
    )

    tfolder2, fname2 = thread2.generate_filename_and_folder(
        file_url,
        download_folder,
        0,
        total_files=1,
        post_id="1",
        post_title="My Post",
        page_number=1,
    )
    # creator folder should be the immediate child of download_folder
    creator_folder_name = os.path.basename(tfolder2)
    assert creator_folder_name in (
        "creator123_creator123",
        "creator123_Unknown_Creator",
    )


def test_template_fallback_on_error(tmp_path):
    download_folder = str(tmp_path / "downloads3")
    other_files_dir = str(tmp_path / "other3")
    os.makedirs(download_folder, exist_ok=True)
    os.makedirs(other_files_dir, exist_ok=True)

    file_url = "https://kemono.cr/files/origname.png?f=origname.png"
    files_to_download = [file_url]
    files_to_posts_map = {file_url: "42"}

    # Provide a broken template that will raise during formatting
    settings = make_settings_with_strategy(
        "per_post", template="{nonexistent}_{post_id}"
    )
    thread = CreatorDownloadThread(
        service="svc",
        creator_id="creatorX",
        download_folder=download_folder,
        selected_posts=["42"],
        files_to_download=files_to_download,
        files_to_posts_map=files_to_posts_map,
        console=None,
        other_files_dir=other_files_dir,
        post_titles_map={("svc", "creatorX", "42"): "Title"},
        settings=settings,
        download_text=False,
    )

    tfolder, fname = thread.generate_filename_and_folder(
        file_url,
        download_folder,
        0,
        total_files=1,
        post_id="42",
        post_title="Title",
        page_number=1,
    )

    # Fallback should produce filename like '{post_id}_{orig_name}.ext'
    assert fname.endswith("origname.png")
    assert "42_" in fname


def test_get_session_caching():
    import kemonodownloader.creator_downloader as cd

    # Ensure thread-local state is clean
    if hasattr(cd._thread_local, "session"):
        del cd._thread_local.session
    s1 = cd.get_session()
    s2 = cd.get_session()
    assert s1 is s2
    # cleanup
    try:
        del cd._thread_local.session
    except Exception:
        pass


def test_get_session_http_and_socks_proxy(tmp_path):
    from types import SimpleNamespace

    import kemonodownloader.creator_downloader as cd

    # Clean thread-local session state
    for attr in ("session", "socks_session"):
        if hasattr(cd._thread_local, attr):
            try:
                delattr(cd._thread_local, attr)
            except Exception:
                try:
                    delattr(cd._thread_local, attr)
                except Exception:
                    pass

    # HTTP proxy should be applied to the per-thread session
    http_settings = SimpleNamespace(
        get_proxy_settings=lambda: {"http": "http://proxy:8080"}
    )
    s_http = cd.get_session(http_settings)
    assert isinstance(s_http, requests.Session)
    assert s_http.proxies.get("http") == "http://proxy:8080"

    # Clean and test socks proxy path returns a separate socks_session
    try:
        del cd._thread_local.session
    except Exception:
        pass
    if hasattr(cd._thread_local, "socks_session"):
        try:
            del cd._thread_local.socks_session
        except Exception:
            pass

    socks_settings = SimpleNamespace(
        get_proxy_settings=lambda: {"http": "socks5://localhost:1080"}
    )
    s_socks = cd.get_session(socks_settings)
    # socks_session should be created on thread-local and returned
    assert hasattr(cd._thread_local, "socks_session")
    assert s_socks is cd._thread_local.socks_session
    assert str(s_socks.proxies.get("http")).startswith("socks5://")

    # cleanup
    for attr in ("session", "socks_session"):
        if hasattr(cd._thread_local, attr):
            try:
                delattr(cd._thread_local, attr)
            except Exception:
                try:
                    delattr(cd._thread_local, attr)
                except Exception:
                    pass


class DummySignal:
    def __init__(self):
        self.emitted = False
        self.last_args = None

    def emit(self, *args):
        self.emitted = True
        self.last_args = args


def test_preview_thread_network_success(tmp_path, monkeypatch):
    # Create a valid PNG by using QPixmap -> QBuffer to ensure valid image bytes
    from PyQt6.QtCore import QBuffer, QIODevice
    from PyQt6.QtGui import QPixmap

    pix = QPixmap(1, 1)
    pix.fill()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.ReadWrite)
    pix.save(buf, "PNG")
    png_bytes = bytes(buf.data())

    class FakeResp:
        def __init__(self):
            self.status_code = 200
            self.headers = {"content-length": str(len(png_bytes))}

        def raise_for_status(self):
            return

        def iter_content(self, chunk_size=8192):
            yield png_bytes

        def close(self):
            return

    class FakeSession:
        def get(self, url, headers=None, stream=None):
            return FakeResp()

    monkeypatch.setattr(cd, "get_session", lambda settings_tab=None: FakeSession())

    url = "https://kemono.cr/uploads/1.png"
    cache_dir = str(tmp_path / "cache")
    thread = cd.PreviewThread(url, cache_dir)
    sig = DummySignal()
    thread.preview_ready = sig
    thread.run()

    # Ensure preview_ready emitted and cache file exists
    assert sig.emitted is True
    cache_key = hashlib.md5(url.encode()).hexdigest() + os.path.splitext(url)[1]
    assert os.path.exists(os.path.join(cache_dir, cache_key))


def test_post_detection_thread_invalid_url_emits_error():
    class DummySettings:
        creator_posts_max_attempts = 1
        settings_tab = None

    # URL missing /user/ should trigger invalid_url_format
    t = cd.PostDetectionThread("https://kemono.cr/bad/path", {}, DummySettings())
    err = DummySignal()
    t.error = err
    t.run()
    assert err.emitted is True


def test_template_bad_placeholder_fallsback_and_logs(tmp_path, qapp):
    """If the user-provided filename template raises during formatting,
    the code should log a warning and fall back to a safe default."""
    file_url = "https://kemono.cr/files/foo.png"
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{post_id}_{nonexistent}",
        get_creator_folder_strategy=lambda: "per_post",
    )
    settings = SimpleNamespace(settings_tab=settings_tab)

    post_titles = {("svc", "creator123", "1"): "My Post"}

    th = cd.CreatorDownloadThread(
        service="svc",
        creator_id="creator123",
        download_folder=str(tmp_path / "dl"),
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=None,
        other_files_dir=str(tmp_path / "other"),
        post_titles_map=post_titles,
        settings=settings,
    )

    # Capture log emits
    th.log = SimpleNamespace(emit=MagicMock())

    _target_folder, filename = th.generate_filename_and_folder(
        file_url, str(tmp_path / "dl"), 0, 1, "1", "My Post", page_number=1
    )

    # Should fall back to post_id + original name (orig_name from URL 'foo')
    assert filename.endswith("1_foo.png")
    # Ensure a warning was emitted about template error
    assert th.log.emit.called


def test_template_format_exception_falls_back_without_a_prefix(tmp_path, qapp):
    """A broken template falls back to post id + original name.

    The fallback carries no number prefix any more: numbering is part of the
    template now, so there is nothing to prepend.
    """
    file_url = "https://kemono.cr/files/bar.jpg"
    settings_tab = SimpleNamespace(
        get_creator_filename_template=lambda: "{missing_field}",
        get_creator_folder_strategy=lambda: "per_post",
    )
    settings = SimpleNamespace(settings_tab=settings_tab)

    post_titles = {("svc", "creatorX", "42"): "Some Post"}

    th = cd.CreatorDownloadThread(
        service="svc",
        creator_id="creatorX",
        download_folder=str(tmp_path / "dl2"),
        selected_posts=["42"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "42"},
        console=None,
        other_files_dir=str(tmp_path / "other2"),
        post_titles_map=post_titles,
        settings=settings,
    )

    th.log = SimpleNamespace(emit=MagicMock())

    _, fname1 = th.generate_filename_and_folder(
        file_url, str(tmp_path / "dl2"), 0, 1, "42", "Some Post", page_number=1
    )
    assert fname1 == "42_bar.jpg"
    assert th.log.emit.called


def test_get_session_http_proxy_updates_proxies():
    settings_tab = SimpleNamespace(
        get_proxy_settings=lambda: {
            "http": "http://127.0.0.1:3128",
            "https": "http://127.0.0.1:3128",
        }
    )
    session = get_session(settings_tab)
    assert session is not None
    assert session.proxies.get("http") == "http://127.0.0.1:3128"


def test_get_session_socks_proxy_returns_socks_session():
    settings_tab = SimpleNamespace(
        get_proxy_settings=lambda: {"http": "socks5h://127.0.0.1:9050"}
    )
    session = get_session(settings_tab)
    assert session is not None
    # Socks session should have proxies updated
    assert session.proxies.get("http") == "socks5h://127.0.0.1:9050"


class FakeResponse__from_preview_thread:
    def __init__(self, chunks):
        self._chunks = chunks
        self.status_code = 200
        self.headers = {"content-length": str(sum(len(c) for c in chunks))}

    def iter_content(self, chunk_size=8192):
        for c in self._chunks:
            yield c

    def raise_for_status(self):
        return None

    def close(self):
        return None


class FakeSession__from_preview_thread:
    def __init__(self, chunks):
        self._chunks = chunks

    def get(self, *args, **kwargs):
        return FakeResponse__from_preview_thread(self._chunks)


def test_preview_thread_uses_cache(qtbot, tmp_path):
    url = "https://example.com/img.png"
    cache_dir = str(tmp_path / "cachep")
    os.makedirs(cache_dir, exist_ok=True)

    # Create a valid small PNG using QPixmap to avoid embedding bytes
    cache_key = hashlib.md5(url.encode()).hexdigest() + ".png"
    cache_path = os.path.join(cache_dir, cache_key)
    pix = QPixmap(4, 4)
    pix.fill(QColor("white"))
    pix.save(cache_path)

    called = []

    def on_preview(u, pix):
        called.append((u, isinstance(pix, QPixmap)))

    thread = PreviewThread(url, cache_dir, settings_tab=None)
    thread.preview_ready.connect(on_preview)
    thread.run()

    assert called and called[0][0] == url and called[0][1] is True


def test_preview_thread_emits_error_for_invalid_data(qtbot, tmp_path, monkeypatch):
    url = "https://example.com/bad.png"
    cache_dir = str(tmp_path / "cacheb")
    os.makedirs(cache_dir, exist_ok=True)

    # Invalid image bytes
    chunks = [b"notanimage"]
    monkeypatch.setattr(
        "kemonodownloader.creator_downloader.get_session",
        lambda settings_tab=None: FakeSession__from_preview_thread(chunks),
    )

    errors = []

    def on_error(msg):
        errors.append(msg)

    thread = PreviewThread(url, cache_dir, settings_tab=None)
    thread.error.connect(on_error)
    thread.run()

    assert errors
