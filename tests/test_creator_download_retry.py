import asyncio
import os
from types import SimpleNamespace

import kemonodownloader.creator_downloader as cd


def test_download_size_mismatch_deletion_raises(monkeypatch, tmp_path):
    # Prepare a CreatorDownloadThread with minimal config
    file_url = "https://kemono.cr/files/f.jpg"
    download_folder = str(tmp_path / "dl")
    other_dir = str(tmp_path / "other")
    os.makedirs(other_dir, exist_ok=True)

    settings = SimpleNamespace(settings_tab=None, file_download_max_retries=1)

    thread = cd.CreatorDownloadThread(
        service="kemono",
        creator_id="1",
        download_folder=download_folder,
        selected_posts=["1"],
        files_to_download=[file_url],
        files_to_posts_map={file_url: "1"},
        console=SimpleNamespace(),
        other_files_dir=other_dir,
        post_titles_map={},
        auto_rename_enabled=False,
        settings=settings,
        max_concurrent=1,
        download_text=False,
    )

    # Stub signals to avoid PyQt interactions
    thread.file_progress = SimpleNamespace(emit=lambda *a, **k: None)
    thread.file_completed = SimpleNamespace(emit=lambda *a, **k: None)
    thread.post_completed = SimpleNamespace(emit=lambda *a, **k: None)
    thread.log = SimpleNamespace(emit=lambda *a, **k: None)

    # Force filename generation to a known path
    target_folder = str(tmp_path / "dl")
    os.makedirs(target_folder, exist_ok=True)
    thread.generate_filename_and_folder = lambda *a, **k: (target_folder, "f.jpg")

    # Fake response: reports content-length 10 but only yields 5 bytes
    class Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        @property
        def headers(self):
            return {"content-length": "10"}

        def iter_content(self, chunk_size=8192):
            yield b"12345"

        def close(self):
            return None

    class Sess:
        def get(self, *a, **k):
            return Resp()

    monkeypatch.setattr(cd, "get_session", lambda st=None: Sess())

    # Make os.remove raise OSError when called to hit the deletion-failure branch
    def fake_remove(path):
        raise OSError("cannot delete")

    monkeypatch.setattr(os, "remove", fake_remove)

    # Run the async download
    asyncio.run(thread.download_file(file_url, target_folder, 0, total_files=1, page_number=1))

    # The thread should have recorded a failure for this file
    assert file_url in thread.failed_files
    assert (
        "Size mismatch" in thread.failed_files[file_url]
        or "downloaded" in thread.failed_files[file_url]
    )
