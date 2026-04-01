import asyncio
import hashlib
from types import SimpleNamespace

from kemonodownloader import creator_downloader as cd


def test_download_file_skips_existing_hash(tmp_path):
    # Create a fake existing file and a fake HashDB entry pointing at it
    file_content = b"hello world"
    existing = tmp_path / "existing.bin"
    existing.write_bytes(file_content)

    file_url = "https://kemono.cr/files/existing.bin"

    url_hash = hashlib.md5(file_url.encode()).hexdigest()
    entry = {
        "file_path": str(existing),
        "file_hash": hashlib.md5(file_content).hexdigest(),
        "file_size": len(file_content),
    }

    class FakeHashDB:
        def __init__(self, e):
            self._e = e

        def lookup(self, h):
            return self._e if h == url_hash else None

        def store(self, *a, **k):
            pass

    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)

    t = cd.CreatorDownloadThread(
        "service",
        "creator",
        str(tmp_path),
        ["1"],
        [file_url],
        {file_url: "1"},
        None,
        str(tmp_path),
        {},
        False,
        settings,
    )
    # Inject fake hash DB
    t.hash_db = FakeHashDB(entry)

    # Ensure domain config exists
    t.domain_config = {
        "api_base": "https://kemono.cr/api",
        "referer": "https://kemono.cr",
    }

    # Run the coroutine — lookup should short-circuit and mark as completed
    asyncio.run(t.download_file(file_url, str(tmp_path), 0, 1))

    assert file_url in t.completed_files
