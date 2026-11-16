import asyncio
import ctypes
import gzip
import hashlib
import html
import json
import locale
import os
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import NamedTuple, Optional
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

import qtawesome as qta
import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from fake_useragent import UserAgent
from PyQt6.QtCore import (
    QBuffer,
    QByteArray,
    QIODevice,
    QObject,
    QSize,
    Qt,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
)
from PyQt6.QtGui import QDesktopServices, QImageReader, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from requests.adapters import HTTPAdapter  # type: ignore[import]

from kemonodownloader.creator_config import CreatorConfigStore
from kemonodownloader.domain_config import (
    clean_file_url,
    file_host_headers,
    get_domain_config,
    get_domains,
    preview_thumbnail_url,
    warm_file_host,
)
from kemonodownloader.download_history import DownloadHistoryDB, iso_to_local_date
from kemonodownloader.hash_db import HashDB
from kemonodownloader.kd_language import translate
from kemonodownloader.kd_paths import ensure_directory
from kemonodownloader.kd_theme import MENU_STYLE, scoped
from kemonodownloader.preview_cache import (
    DEFAULT_PREVIEW_CACHE_BYTES,
    PreviewImageCache,
)
from kemonodownloader.retry_policy import (
    api_retry_delay,
    countdown_seconds,
    is_terminal_error,
    is_terminal_status,
)


def _log_line_html(message, color):
    """Render one log line as coloured rich text.

    The text is escaped first: log messages carry server response bodies,
    URLs and file names straight from the network, and the console renders
    rich text. An unescaped ``<`` in a 403 body (or a filename like
    ``a<b.png``) was parsed as markup, which swallowed the rest of the line
    or silently rendered nothing.
    """
    return f"<span style='color:{color}'>{html.escape(str(message))}</span>"


# Cap for the in-memory log store and for every log view, in lines, so the
# store and both widgets always agree on how much history is kept.
LOG_LINE_LIMIT = 5000

# How many complete post records the Creator tab keeps for reopened previews.
# A record is small (JSON with description + attachment list), but the list is
# still bounded so browsing many posts cannot grow it without limit.
POST_PREVIEW_CACHE_LIMIT = 20

# One colour per level, shared by the inline console and the log window and
# taken from the muted palette the rest of the tab uses. The plain CSS
# primaries this replaces were unreadable on the #2A3B5A console (green
# #008000 sat at 2.2:1, red at 2.8:1) and DEBUG fell through to white, which
# made the least important lines the loudest thing on screen.
LOG_LEVEL_COLORS = {
    "DEBUG": "#8A9BB5",
    "INFO": "#D7E1F0",
    "WARNING": "#E5C07B",
    "ERROR": "#E06C75",
}
# Unknown levels keep the body text colour rather than shouting in white.
LOG_DEFAULT_COLOR = "#D7E1F0"

# The Creator Queue's menus use the shared app menu style (kd_theme.MENU_STYLE,
# which app.main() applies to every context menu). The menu chrome and item
# metrics stay native, so the queue menu and the input row's own edit menu
# match instead of drifting apart.

# How many profile-only name lookups may run at once; a bulk .txt import
# queues the rest instead of firing one request per link at the API.
CREATOR_NAME_LOOKUP_CONCURRENCY = 2
# A small gap after each lookup keeps a large import from hammering the API.
CREATOR_NAME_LOOKUP_DELAY = 0.15  # seconds
# Names are decoration, so a stalled request should not hold a worker long.
CREATOR_NAME_LOOKUP_TIMEOUT = 5  # seconds

# Repeated small-button chrome. Scoped, so a tooltip label parented to the
# button cannot inherit the size/background rule.
_RUN_BUTTON_STYLE = scoped(
    "QPushButton", "background: #4A5B7A; padding: 8px; border-radius: 5px;"
)
_TOOL_BUTTON_STYLE = scoped(
    "QPushButton", "background: #4A5B7A; padding: 6px; border-radius: 5px;"
)


def _post_published_datetime(post):
    """Return the post's own publish datetime, or None.

    Shared by the ``{post_date}`` and ``{post_time}`` placeholders so the two
    can never disagree about a post. Checks the common field names used by the
    API for the original post date, and deliberately ignores 'added' /
    'import*' style fields, which represent when the post was scraped rather
    than when it was posted.
    """
    if not isinstance(post, dict):
        return None
    for key in ("published", "post_date", "date"):
        raw = post.get(key)
        if not raw:
            continue
        try:
            text = str(raw).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text)
        except Exception:
            try:
                return datetime.strptime(str(raw)[:10], "%Y-%m-%d")
            except Exception:
                continue
    return None


def get_post_published_date(post):
    """Return the post's original publish date (NOT the import/scrape date)
    as a `datetime.date`, or None if it can't be determined.
    """
    published = _post_published_datetime(post)
    return published.date() if published is not None else None


def _hash_file(path):
    """Return the md5 of *path*, read in blocks.

    Streamed so a multi-gigabyte file is never loaded into memory, and called
    through ``asyncio.to_thread`` so hashing one file does not stall the other
    downloads sharing the event loop.
    """
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_filter_date(text):
    """Parse a user-entered 'YYYY-MM-DD' date filter boundary. Returns a
    `datetime.date` or None if *text* is blank/unparseable."""
    if not text:
        return None
    text = text.strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except Exception:
        return None


# Extensions treated as compressed archives: a post holding one of these is
# never dropped by the file-count filter when "Keep Archives" is on, and its
# images are skipped by the "Skip Images if Compressed" download option.
COMPRESSED_EXTENSIONS = (".zip", ".7z", ".rar")
# Extensions treated as images by the "Skip Images if Compressed" option.
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".jpe", ".png", ".gif", ".webp")
# Punctuation that encloses a token, so it can act as the token's own delimiter
# in keyword matching. Joiners (., -, _, +, /, #, @, *) are deliberately
# absent: they sit inside names, numbers and URLs, where they are not
# boundaries. ASCII, full-width and CJK bracket/quote pairs are all included.
ENCLOSING_PUNCTUATION = frozenset(
    "()[]{}<>\"'"
    "（）［］｛｝〈〉《》「」『』【】〔〕〖〗〘〙〚〛｢｣"
    "＂＇“”‘’〝〞"
)


def file_extension(name_or_path):
    """Return the lower-case extension of a filename or URL path ("" if none)."""
    if not name_or_path:
        return ""
    # A query string (".../file.zip?f=file.zip") must not be part of the ext.
    path = str(name_or_path).split("?")[0]
    return os.path.splitext(path.strip())[1].lower()


def filename_without_extension(name):
    """Return *name* without its final extension ("1_JP.png" -> "1_JP").

    The keyword filters match against this instead of the raw name: a file's
    type belongs to the filetype boxes, so a keyword like "png" must not drop
    every PNG, and "zip" must not drop archives by accident. Only the final
    suffix is removed, so "art.psd.png" keeps ".psd"; a name with no extension
    is returned unchanged and a query string is ignored first.
    """
    path = str(name or "").split("?")[0].strip()
    stem, _ = os.path.splitext(path)
    return stem


def normalize_extension(ext):
    """Return the filetype an extension is counted, listed and filtered as.

    ``.jpeg`` files are ordinary JPEGs under a second name, so they count
    as ``.jpg`` everywhere the app tallies, displays or filters a filetype.
    Only the type is folded; the file keeps its real name on disk.
    """
    ext = str(ext or "").strip().lower()
    return ".jpg" if ext == ".jpeg" else ext


def detect_extension(name_or_url):
    """The extension a file is filtered and counted as, from a name or URL.

    One helper for every caller: the fetch used to pull content-image
    extensions straight out of the URL (query string and all), so
    ``.../x.jpg?f=x.jpg`` counted as ``.jpg?f=x.jpg``, never matched a ticked
    type, and the image was silently dropped even though the post filter had
    counted it.
    """
    return normalize_extension(file_extension(name_or_url))


# Characters that would end a ``?f=`` value or change the query's meaning.
_QUERY_VALUE_BREAKERS = frozenset("&#+?=%")


def filename_query_value(name):
    """Encode a file name for use as a ``?f=`` value.

    Only the characters that would otherwise break the query are escaped.
    Everything else is left byte-identical on purpose: the URL is the hash
    database's identity for a file, so re-encoding a name that already worked
    would make every existing copy look new and download it again.
    """
    return "".join(
        quote(char, safe="") if char in _QUERY_VALUE_BREAKERS else char
        for char in str(name or "")
    )


def filename_from_query(url):
    """The decoded ``f=`` value of *url*, or "" when the URL has none.

    A real query parameter (``?f=name`` / ``&f=name``) wins; a bare ``f=`` in
    the path is still accepted, which is the shape some callers and tests
    build. The value stops at ``&`` and is percent-decoded, so a name that
    contains ``&`` or ``f=`` no longer truncates or keeps ``%20``.
    """
    text = str(url or "")
    match = re.search(r"[?&]f=([^&]*)", text) or re.search(r"f=([^&]*)", text)
    if not match:
        return ""
    return unquote(match.group(1))


def parse_filter_count(text):
    """Parse a user-entered file-count bound ("3", " 12 ").

    Returns a non-negative int, or None when *text* is blank, not a whole
    number, or negative — in which case the bound counts as disabled.
    """
    if text is None:
        return None
    try:
        value = int(str(text).strip())
    except Exception:
        return None
    return value if value >= 0 else None


def parse_post_tags(tags):
    """Parse a post's ``tags`` field into a plain list of strings.

    Tolerates every shape the APIs are known to return:
    - A PostgreSQL array string: "{tag1,tag2,tag3}" (Kemono/Coomer style)
    - A comma-separated string: "tag1, tag2, tag3"
    - A semicolon-separated string: "tag1; tag2; tag3"
    - A list of plain strings, or of dicts with a 'name', 'tag', 'label',
      or 'value' key
    - A dict mapping tag names to truthy/falsy values.
    """
    result = []
    try:
        if not tags:
            return result
        if isinstance(tags, str):
            text = tags
            if text.startswith("{") and text.endswith("}"):
                text = text[1:-1]
            candidates = text.split(",")
            if len(candidates) <= 1:
                candidates = text.split(";")
            for candidate in candidates:
                cleaned = candidate.strip().strip("{}'\"")
                if cleaned:
                    result.append(cleaned)
            return result
        if isinstance(tags, list):
            for tag in tags:
                if isinstance(tag, dict):
                    name = (
                        tag.get("name")
                        or tag.get("tag")
                        or tag.get("label")
                        or tag.get("value")
                    )
                    cleaned = str(name).strip().strip("{}'\"") if name else ""
                else:
                    cleaned = str(tag).strip().strip("{}'\"")
                if cleaned:
                    result.append(cleaned)
            return result
        if isinstance(tags, dict):
            for key in tags:
                cleaned = str(key).strip().strip("{}'\"")
                if cleaned:
                    result.append(cleaned)
    except Exception:
        return result
    return result


def analyze_post(post):
    """Return the searchable/measurable facts about a post.

    Keys:
    - ``filenames``: lower-case main-file + attachment names, space joined
      (full names, for the search bar)
    - ``description``: lower-case post body text
    - ``tags``: lower-case tag names, space joined
    - ``file_count``: main file + attachments + unique content images
    - ``has_compressed``: True when any of those files is a ZIP/7Z/RAR
    - ``extensions``: sorted lower-case extensions of every file found, so
      callers can ask which types a post actually holds
    - ``extension_counts``: extension -> how many files of that type it holds
    - ``filenames_list``: the same names, one per file, for per-file
      keyword matching (the keyword filters drop each name's extension)
    - ``tag_list``: the post's tags one by one, for per-tag matching
    - ``description_glued``: lower-case body text with the separators
      BeautifulSoup injects between inline tags removed ("" when that
      rendering adds nothing)
    - ``published``: the post's own publish date as a ``datetime.date``,
      or None when it cannot be read

    Extension names that are the same type are folded (see
    :func:`normalize_extension`), so a ``.jpeg`` file is counted as ``.jpg``.

    These are the facts every post filter reads. They live in the tab's
    post index so a filter change can be applied without fetching again.

    The HTML body is parsed once, so callers needing several of these values
    should cache the returned dict instead of calling this again.
    """
    analysis = {
        "filenames": "",
        "description": "",
        "tags": "",
        "file_count": 0,
        "has_compressed": False,
        "extensions": [],
        "filenames_list": [],
        "tag_list": [],
        "description_glued": "",
        "published": None,
    }
    if not isinstance(post, dict):
        return analysis

    names = []
    file_info = post.get("file")
    if isinstance(file_info, dict):
        name = file_info.get("name") or os.path.basename(file_info.get("path") or "")
        if name:
            names.append(
                (
                    str(name),
                    file_extension(name) or file_extension(file_info.get("path")),
                )
            )
    attachments = post.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            name = attachment.get("name") or os.path.basename(
                attachment.get("path") or ""
            )
            if name:
                names.append(
                    (
                        str(name),
                        file_extension(name) or file_extension(attachment.get("path")),
                    )
                )

    # How many files of each type this post holds, main file and attachments
    # first. These counts back the "Show found only (with counts)" labels.
    extension_counts = {}
    for _, ext in names:
        ext = normalize_extension(ext)
        if ext:
            extension_counts[ext] = extension_counts.get(ext, 0) + 1

    file_count = len(names)
    has_compressed = any(ext in COMPRESSED_EXTENSIONS for _, ext in names)

    content = post.get("content")
    if isinstance(content, str) and content:
        try:
            soup = BeautifulSoup(content, "html.parser")
        except Exception:
            soup = None
        if soup is not None:
            space_joined = soup.get_text(" ")
            analysis["description"] = space_joined.lower()
            tag_glued = _tag_glued_text(soup)
            if tag_glued and tag_glued != space_joined:
                analysis["description_glued"] = tag_glued.lower()
            seen_images = set()
            for img in soup.select("img[src]"):
                src = str(img.get("src") or "").strip()
                if not src or src in seen_images:
                    continue
                seen_images.add(src)
                file_count += 1
                image_ext = file_extension(src)
                if image_ext in COMPRESSED_EXTENSIONS:
                    has_compressed = True
                image_ext = normalize_extension(image_ext)
                if image_ext:
                    extension_counts[image_ext] = extension_counts.get(image_ext, 0) + 1

    analysis["file_count"] = file_count
    analysis["has_compressed"] = has_compressed
    analysis["extensions"] = sorted(extension_counts)
    analysis["extension_counts"] = extension_counts
    tag_list = parse_post_tags(post.get("tags"))
    analysis["filenames"] = " ".join(name for name, _ in names).lower()
    analysis["filenames_list"] = [name for name, _ in names]
    analysis["tags"] = " ".join(tag_list).lower()
    analysis["tag_list"] = tag_list
    analysis["published"] = get_post_published_date(post)
    return analysis


def post_matches_search(
    post_title, post_id, search_text, search_scopes, post_search_index=None
):
    """Return True when a post matches the Creator tab's search bar text.

    Matching is a case-insensitive substring test against every enabled scope
    (title, filenames, description, tags). Scopes other than the title are
    served by the per-post index built while detecting posts, so a post with
    no index entry still matches on its title alone. An empty scope set falls
    back to the title, which is the historical behaviour.
    """
    if not search_text:
        return True
    needle = str(search_text).lower()
    scopes = set(search_scopes) if search_scopes else {"title"}
    if "title" in scopes and needle in str(post_title or "").lower():
        return True
    if not post_search_index:
        return False
    entry = post_search_index.get(post_id)
    if not isinstance(entry, dict):
        return False
    for scope in ("filenames", "description", "tags"):
        if scope in scopes and needle in str(entry.get(scope) or ""):
            return True
    return False


class PostFilters(NamedTuple):
    """The Creator tab's post-level filters, as one immutable value.

    Built from the Filters box for the live pass and from the detection
    thread's options while fetching; both feed :func:`post_skip_reason`, so
    the list can never disagree with what a fetch would produce.
    """

    skip_keywords: tuple = ()
    skip_scopes: frozenset = frozenset({"title"})
    date_after: object = None
    date_before: object = None
    file_count_min: object = None
    file_count_max: object = None
    keep_compressed: bool = False
    # None = the filetype filter is off. An *empty* frozenset means the filter
    # is on with nothing ticked, which no post can satisfy.
    required_filetypes: object = None
    # Whether the run also writes the post's description. A post holding no
    # files at all still produces desc_<id>.txt when this is on, so it is not
    # "empty" from the download's point of view.
    download_post_text: bool = False
    # Relaxed keyword matching: substring instead of whole-word. Mirrors the
    # "Keyword Matching Rules" setting's Relaxed (Posts)/(Both) options, and
    # reaches the fetch through this same value so both passes apply identical
    # rules.
    lenient_keywords: bool = False
    # "Punctuation Matching Rules: Relaxed": any punctuation at a keyword edge
    # is its own delimiter. False keeps the default enclosing-punctuation list.
    lenient_punctuation: bool = False


def keyword_skip_reason(post_title, facts, filters):
    """Return the skip keyword that drops this post, or "".

    Scopes are the ticked combination of title, filenames, description and
    tags; the post is dropped when a keyword matches as a whole word in ANY
    enabled scope. File names are matched without their extension: a file's
    type is the filetype filter's business, so "png" cannot drop every PNG.
    ``filters.lenient_keywords`` switches every scope to substring matching.
    The tag-glued description is only consulted after the space-joined
    rendering misses, which is how the fetch has always behaved.
    """
    keywords = filters.skip_keywords or ()
    if not keywords:
        return ""
    lenient = bool(filters.lenient_keywords)
    punctuation_lenient = bool(filters.lenient_punctuation)
    # An empty set means no scope is ticked, so no post is dropped by
    # keyword; only a missing value falls back to the title.
    scopes = filters.skip_scopes
    if scopes is None:
        scopes = frozenset({"title"})
    if "title" in scopes and post_title:
        matched = _first_matching_keyword(
            keywords, post_title, lenient, punctuation_lenient
        )
        if matched:
            return matched
    if "filenames" in scopes:
        for name in facts.get("filenames_list") or ():
            matched = _first_matching_keyword(
                keywords,
                filename_without_extension(name),
                lenient,
                punctuation_lenient,
            )
            if matched:
                return matched
    if "description" in scopes:
        for text in (facts.get("description"), facts.get("description_glued")):
            if not text:
                continue
            matched = _first_matching_keyword(
                keywords, text, lenient, punctuation_lenient
            )
            if matched:
                return matched
    if "tags" in scopes:
        for tag in facts.get("tag_list") or ():
            matched = _first_matching_keyword(
                keywords, tag, lenient, punctuation_lenient
            )
            if matched:
                return matched
    return ""


def keyword_needed_rejoin(keyword, facts, filters):
    """True when *keyword* only matches the tag-glued description.

    Used purely so the fetch log keeps saying when an extra match came from
    re-joining inline markup.
    """
    scopes = filters.skip_scopes
    if scopes is None:
        scopes = frozenset({"title"})
    if "description" not in scopes:
        return False
    lenient = bool(filters.lenient_keywords)
    punctuation_lenient = bool(filters.lenient_punctuation)
    glued = facts.get("description_glued")
    if not glued or not _first_matching_keyword(
        [keyword], glued, lenient, punctuation_lenient
    ):
        return False
    return not _first_matching_keyword(
        [keyword], facts.get("description"), lenient, punctuation_lenient
    )


def date_out_of_range(facts, filters):
    """True when the post's own publish date falls outside the range.

    A post whose date we could not read is kept: dropping it would hide
    content for a reason the user never asked for.
    """
    if not filters.date_after and not filters.date_before:
        return False
    published = facts.get("published")
    if published is None:
        return False
    if filters.date_after and published < filters.date_after:
        return True
    if filters.date_before and published > filters.date_before:
        return True
    return False


def file_count_out_of_range(facts, filters):
    """True when the post's file count falls outside the range.

    "Keep Archives" lets a post holding a ZIP/7Z/RAR bypass the range
    entirely, so archive posts are never filtered out.
    """
    if filters.file_count_min is None and filters.file_count_max is None:
        return False
    if filters.keep_compressed and facts.get("has_compressed"):
        return False
    count = facts.get("file_count", 0)
    if filters.file_count_min is not None and count < filters.file_count_min:
        return True
    if filters.file_count_max is not None and count > filters.file_count_max:
        return True
    return False


def _thread_post_file_count(thread, post_id):
    """How many files the post has in this run, for {post_file_count}.

    The tab decides the number once and hands it over (:attr:`post_file_counts`).
    Falling back to the run's list keeps older callers working - but on a retry
    that list holds only the failed files, so the stored count is what keeps
    the placeholder (and the skip-post-folder rule) honest.
    """
    stored = (getattr(thread, "post_file_counts", None) or {}).get(post_id)
    if stored:
        return stored
    return len((getattr(thread, "post_files_map", None) or {}).get(post_id, []))


def _thread_run_files(thread):
    """The run's file list as a set, built once (it is queried per file).

    Built lazily rather than in ``__init__`` so a caller that fills
    ``files_to_download`` after construction still gets the right set.
    """
    cached = getattr(thread, "_files_to_download_set", None)
    if cached is None:
        cached = set(getattr(thread, "files_to_download", None) or ())
        thread._files_to_download_set = cached
    return cached


def filetypes_out_of_scope(facts, filters):
    """True when the post holds none of the required filetypes.

    ``required_filetypes`` is None while the filter is off, and an empty set
    while it is on with nothing ticked - a state nothing can satisfy, so the
    list is empty on purpose.

    One file of a required type anywhere in the post keeps it. A post with no
    files at all is out of scope: a run would fetch nothing for it unless the
    description is being downloaded, which is why "Download Post Text" keeps
    text-only posts visible. A post that does hold files but whose types cannot
    be read (no suffix on the name or path) is kept - dropping it would lose a
    real download over a naming detail.
    """
    required = filters.required_filetypes
    if required is None:
        return False
    required = set(required)
    if not required:
        return True
    extensions = set(facts.get("extensions") or [])
    if not extensions:
        if facts.get("file_count", 0) > 0:
            return False
        return not filters.download_post_text
    return not extensions & required


def post_skip_reason(post_title, facts, filters):
    """Return ``(reason, keyword)`` for the first filter that drops a post.

    ``reason`` is "keywords", "date", "file_count", "filetypes" or
    None; ``keyword`` names the skip keyword when the reason is
    "keywords". The order matches the Filters box, so a post caught by two
    filters is booked once, under the first one.

    *facts* is the post's entry in the tab's post index (see
    :func:`analyze_post`). A post with no entry is kept: emptying the list
    because the details are unavailable would hide posts for no reason. The
    exception is a filetype filter that is on with nothing ticked - that
    matches no post, so it needs no details to reject one.
    """
    if not isinstance(facts, dict):
        required = filters.required_filetypes
        if required is not None and not set(required):
            return "filetypes", ""
        return None, ""
    keyword = keyword_skip_reason(post_title, facts, filters)
    if keyword:
        return "keywords", keyword
    if date_out_of_range(facts, filters):
        return "date", ""
    if file_count_out_of_range(facts, filters):
        return "file_count", ""
    if filetypes_out_of_scope(facts, filters):
        return "filetypes", ""
    return None, ""


def resolve_creator_url(raw_url):
    """Normalize a pasted URL for the Creator Downloader queue.

    Returns a ``(creator_url, post_id)`` tuple:

    * ``.../<service>/user/<id>``               -> (itself, None)
    * ``.../<service>/user/<id>/post/<pid>``    -> (creator URL, "<pid>")
    * anything else                             -> (raw_url, None)

    Returning the input unchanged for unrecognized shapes lets the existing
    URL validation report the error, rather than silently rewriting it.
    """
    if not isinstance(raw_url, str):
        return raw_url, None
    candidate = raw_url.strip().rstrip("/")
    if not candidate:
        return raw_url, None
    try:
        parsed = urlparse(candidate)
        path = parsed.path.strip("/")
    except ValueError:
        return raw_url, None
    if not path:
        return raw_url, None

    parts = path.split("/")
    # Post URL: .../<service>/user/<creator_id>/post/<post_id>
    if len(parts) >= 5 and parts[-2] == "post" and parts[-4] == "user":
        post_id = parts[-1]
        # Drop only the trailing "post/<post_id>" pair; keep ".../user/<id>".
        creator_path = "/".join(parts[:-2])
        creator_url = f"{parsed.scheme}://{parsed.netloc}/{creator_path}"
        return creator_url, (post_id or None)
    return candidate, None


def split_creator_url(url):
    """Return ``(service, creator_id)`` for a creator URL.

    Creator URLs have the shape ``https://<host>/<service>/user/<creator_id>``
    (optionally with a query string).  Anything unexpected yields
    ``("unknown_service", "unknown_creator")`` so download-history lookups
    stay harmless instead of raising.
    """
    url = (url or "").rstrip("/")
    parts = url.split("/")
    if len(parts) >= 3:
        service = parts[-3].split("?")[0]
        creator_id = parts[-1].split("?")[0]
        return service, creator_id
    return "unknown_service", "unknown_creator"


def creator_profile_url(domain_config, service, creator_id):
    """Return the API URL that carries a creator's display name."""
    return f"{domain_config['api_base']}/{service}/user/{creator_id}/profile"


def fetch_creator_display_name(
    settings_tab, domain_config, service, creator_id, timeout=10
):
    """Return a creator's display name, or "" when it cannot be read.

    One small profile request, shared by the queue's name lookups and the
    detection fallback.  The caller owns retries and error reporting; this
    helper only builds and parses the one request both need.
    """
    headers = get_headers().copy()
    headers["Referer"] = domain_config["referer"]
    response = get_session(settings_tab).get(
        creator_profile_url(domain_config, service, creator_id),
        headers=headers,
        timeout=timeout,
    )
    if response.status_code != 200:
        return ""
    data = response.json()
    if not isinstance(data, dict):
        return ""
    return str(data.get("name") or "").strip()


class ThreadSettings:
    """Settings container for thread operations"""

    def __init__(
        self,
        creator_posts_max_attempts,
        post_data_max_retries,
        file_download_max_retries,
        api_request_max_retries,
        simultaneous_downloads,
        settings_tab=None,
    ):
        self.creator_posts_max_attempts = creator_posts_max_attempts
        self.post_data_max_retries = post_data_max_retries
        self.file_download_max_retries = file_download_max_retries
        self.api_request_max_retries = api_request_max_retries
        self.simultaneous_downloads = simultaneous_downloads
        self.settings_tab = settings_tab


try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    locale.setlocale(locale.LC_ALL, "C")

if hasattr(ctypes, "windll"):
    lcid = ctypes.windll.kernel32.GetUserDefaultLCID()
    system_language = locale.windows_locale.get(lcid, "en_US")
else:
    locale_info = locale.getlocale(locale.LC_CTYPE)
    system_language = locale_info[0] if locale_info and locale_info[0] else "en_US"

system_language = system_language.replace("_", "-")
accept_language = f"{system_language},en;q=0.9"

_user_agent: Optional[str] = None


def get_user_agent() -> str:
    global _user_agent
    if _user_agent is None:
        try:
            ua = UserAgent()
            _user_agent = ua.chrome
        except Exception:
            _user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            )
    assert _user_agent is not None
    return _user_agent


# Default headers (will be updated per request based on domain)
def _build_headers() -> dict:
    # The generic header set belongs to the default domain, not to whatever
    # URL a caller happens to preview. Reading the domain list directly keeps
    # a per-request domain override from changing the shared headers.
    domains = get_domains()
    default_domain = domains[0] if domains else "kemono.cr"
    return {
        "User-Agent": get_user_agent(),
        "Referer": f"https://{default_domain}/",
        "Accept": "text/css",
        "Accept-Language": accept_language,
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }


class _RetryableDownloadError(Exception):
    """Raised for download failures (e.g. size mismatch) that should go
    through the normal retry/backoff path in download_file(), rather than
    being treated as a fatal, non-retryable error."""


class _Cancelled(Exception):
    """Raised inside a worker when the user cancelled the run.

    A distinct type so a cancelled transfer is not reported as an unexpected
    failure and does not land in ``failed_files`` (which feeds Retry Failed
    Downloads) - retrying what the user deliberately stopped is noise.
    """


HEADERS = None  # Built lazily via get_headers()


def get_headers() -> dict:
    global HEADERS
    if HEADERS is None:
        HEADERS = _build_headers()
    return HEADERS


# Thread-local storage for per-thread sessions.
# Using a shared session across ThreadPoolExecutor workers causes
# concurrent SSL handshakes through the same connection pool, which
# triggers access-violation crashes on Windows (Python 3.14 / OpenSSL).
# Giving each thread its own session avoids the problem entirely.
_thread_local = threading.local()


def get_session(settings_tab=None):
    """Get or create a per-thread requests session with connection pooling.

    Each thread receives its own ``requests.Session`` (and connection pool)
    so that concurrent SSL handshakes never share underlying OpenSSL state,
    preventing access-violation crashes on Windows.
    """
    session: Optional[requests.Session] = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        # Disable automatic environment/registry proxy lookup.
        # On Windows, concurrent threads calling proxy_bypass_registry
        # via winreg cause "access violation" crashes.  The app manages
        # its own proxy settings through the Settings tab instead.
        session.trust_env = False
        # Configure connection pool (per-thread, so modest sizes suffice)
        adapter = HTTPAdapter(
            pool_connections=10, pool_maxsize=10, max_retries=3, pool_block=False
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _thread_local.session = session

    # Set proxies if settings_tab is provided
    if settings_tab:
        proxies = settings_tab.get_proxy_settings()
        if proxies:
            # Check if this is a SOCKS proxy
            is_socks = any(
                proxy_url.startswith(("socks4://", "socks5://", "socks5h://"))
                for proxy_url in proxies.values()
            )
            if is_socks:
                # Reuse a per-thread SOCKS session to avoid creating one
                # on every call while still keeping threads isolated.
                socks_session: Optional[requests.Session] = getattr(
                    _thread_local, "socks_session", None
                )
                if socks_session is None:
                    socks_session = requests.Session()
                    socks_session.trust_env = False
                    socks_adapter = HTTPAdapter(
                        pool_connections=5,
                        pool_maxsize=5,
                        max_retries=3,
                        pool_block=False,
                    )
                    socks_session.mount("http://", socks_adapter)
                    socks_session.mount("https://", socks_adapter)
                    _thread_local.socks_session = socks_session
                socks_session.proxies.update(proxies)
                return socks_session
            else:
                # For HTTP proxies, use the per-thread session
                session.proxies.update(proxies)
        else:
            session.proxies.clear()

    return session


class _StoppableThread:
    """Cooperative stop shared by every worker thread.

    ``QThread`` stays the Qt base of each subclass; this mixin only adds the
    flag and the two-line stop, so a worker cannot grow a divergent copy.
    """

    is_running = True

    def stop(self):
        self.is_running = False


_IMAGE_URL_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


def _looks_like_image(url):
    """True when *url*'s path ends in an extension Qt can preview."""
    return urlparse(str(url)).path.lower().endswith(_IMAGE_URL_EXTENSIONS)


def _decode_preview_qimage(data, max_size=800):
    """Decode *data* into a QImage that fits *max_size*.

    Qt refuses to decode an image whose full bitmap would exceed its 256 MB
    allocation limit, which multi-thousand-pixel Patreon JPEGs routinely do
    even though a preview only ever shows 800 px. QImageReader can read at a
    reduced size, so those files still preview instead of failing as
    "invalid image data".

    QImage, unlike QPixmap, may be built on a worker thread; the GUI thread
    converts it to a QPixmap when it is displayed.

    Returns None when the bytes are not a decodable image.
    """
    buffer = QBuffer()
    buffer.setData(QByteArray(bytes(data)))
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    source_size = reader.size()
    if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
        reader.setScaledSize(
            source_size.scaled(
                QSize(max_size, max_size),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
        )
    image = reader.read()
    if image.isNull():
        return None
    if image.width() > max_size or image.height() > max_size:
        image = image.scaled(
            max_size,
            max_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return image


def _decode_preview_image(data, max_size=800):
    """Decode *data* into a QPixmap that fits *max_size* (GUI thread)."""
    image = _decode_preview_qimage(data, max_size)
    if image is None:
        return None
    return QPixmap.fromImage(image)


def _download_image_bytes(url, settings_tab=None, on_progress=None):
    """Fetch *url* with the file-host headers and return its bytes.

    ``on_progress(downloaded, total)`` is called per chunk; *total* is 0 when
    the server sends no length. Raises ``requests.RequestException`` on
    transport/HTTP errors so callers can report the URL and the reason.
    """
    domain_config = get_domain_config(url)
    session = get_session(settings_tab)
    headers, file_base_url = file_host_headers(url, get_headers(), domain_config)
    response = session.get(url, headers=headers, stream=True)
    if response.status_code == 403:
        # DDoS-Guard challenges the first request of a fresh session; warming
        # the file host sets its clearance cookie, so retry once instead of
        # failing the preview outright.
        response.close()
        warm_file_host(
            session,
            file_base_url,
            headers.get("User-Agent", ""),
            domain_config.get("referer"),
        )
        response = session.get(url, headers=headers, stream=True)
    response.raise_for_status()
    header = response.headers.get("content-length")
    try:
        total_size = int(header) if header is not None else 0
    except Exception:
        total_size = 0
    data = bytearray()
    downloaded = 0
    for chunk in response.iter_content(chunk_size=8192):
        if not chunk:
            continue
        data.extend(chunk)
        downloaded += len(chunk)
        if on_progress is not None:
            on_progress(downloaded, total_size)
    return bytes(data)


class PreviewThread(QThread):
    preview_ready = pyqtSignal(str, object)
    progress = pyqtSignal(int)
    error = pyqtSignal(str)

    def __init__(self, url, settings_tab=None):
        super().__init__()
        self.url = url
        self.settings_tab = settings_tab
        self.total_size = 0
        self.downloaded_size = 0

    def run(self):
        if not _looks_like_image(self.url):
            return
        try:
            data = _download_image_bytes(
                self.url, self.settings_tab, self._report_progress
            )
            pixmap = _decode_preview_image(data)
            if pixmap is None:
                self.error.emit(
                    f"{translate('failed_to_download')}: {self.url}: "
                    f"{translate('invalid_image_data')}"
                )
                return
            self.preview_ready.emit(self.url, pixmap)
        except requests.RequestException as e:
            self.error.emit(
                f"{translate('failed_to_download')}: {self.url}: {str(e)}"
            )
        except Exception as e:
            self.error.emit(translate("unexpected_error", f"{self.url}: {str(e)}"))

    def _report_progress(self, downloaded, total_size):
        self.downloaded_size = downloaded
        self.total_size = total_size
        if total_size > 0:
            progress = int((downloaded / total_size) * 100)
        else:
            progress = 0
        self.progress.emit(min(progress, 100))


class ImageModal(QDialog):
    """Preview one image at the site's thumbnail resolution."""

    # Class-level default keeps the display helpers usable on instances built
    # with ``__new__`` in tests, before the Qt superclass is initialised.
    _image_shown = False
    _thumbnail_url = ""

    def __init__(self, url, parent=None, settings_tab=None, initial_image=None):
        super().__init__(parent)
        self._parent = parent
        self._full_url = str(url)
        self._thumbnail_url = preview_thumbnail_url(self._full_url) or self._full_url
        self._image_shown = False
        self._preview_threads = []
        self.setWindowTitle(translate("media_preview"))
        self.setModal(True)
        self.resize(800, 800)
        self._layout = QVBoxLayout()
        self._label = QLabel(translate("loading_image_simple"))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._label)

        self._closed = False

        self._progress_bar = QProgressBar()
        self._progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; } QProgressBar::chunk { background: #4A5B7A; }"
        )
        self._layout.addWidget(self._progress_bar)
        self.setLayout(self._layout)

        if settings_tab is None:
            settings_tab = self._resolve_settings_tab()
        self._settings_tab = settings_tab

        # A caller that already has the decoded thumbnail (the post image
        # list does) can show it immediately instead of fetching it again.
        if initial_image is not None:
            pixmap = (
                initial_image
                if isinstance(initial_image, QPixmap)
                else QPixmap.fromImage(initial_image)
            )
            if not pixmap.isNull():
                self.display_image(self._thumbnail_url, pixmap)
                return
        self._start_preview(self._thumbnail_url)

    def _resolve_settings_tab(self):
        """Return the Settings tab so previews honor the proxy settings.

        The creator tab keeps its owner as ``_parent`` and never shadows
        Qt's ``parent`` method, so ``self._parent.parent`` is a bound
        method rather than the main window.  Resolving through it yielded
        ``None``, which made previews bypass the proxy that downloads use.
        """
        owners = (
            self._parent,
            getattr(self._parent, "_parent", None),
            getattr(self._parent, "parent", None),
        )
        for owner in owners:
            candidate = getattr(owner, "settings_tab", None)
            if candidate is not None:
                return candidate
        return None

    def _start_preview(self, url):
        """Fetch one image and show it when it arrives."""
        self._progress_bar.setValue(0)
        self._progress_bar.show()
        if not self._image_shown:
            self._label.setText(translate("loading_image_simple"))
        thread = PreviewThread(url, self._settings_tab)
        self.preview_thread = thread
        self._preview_threads.append(thread)
        thread.preview_ready.connect(self._on_preview_ready)
        thread.progress.connect(self.update_progress)
        thread.error.connect(self._on_preview_error)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._forget_thread(t))
        thread.start()

    def _forget_thread(self, thread):
        """Drop a finished worker so only running threads stay referenced."""
        try:
            self._preview_threads.remove(thread)
        except ValueError:
            pass

    def _on_preview_ready(self, url, pixmap):
        if getattr(self, "_closed", False):
            return
        self.display_image(url, pixmap)

    def _on_preview_error(self, error_message):
        if getattr(self, "_closed", False):
            return
        self.display_error(error_message)

    def update_progress(self, value):
        self._progress_bar.setValue(value)
        if not getattr(self, "_image_shown", False):
            self._label.setText(translate("loading_image", value))

    def display_image(self, url, pixmap):
        self._image_shown = True
        self._label.setText("")
        self._progress_bar.hide()
        self._label.setPixmap(pixmap)

    def display_error(self, error_message):
        if not getattr(self, "_image_shown", False):
            self._label.setText(translate("error_loading_image"))
        self._progress_bar.hide()
        QMessageBox.critical(self, translate("image_load_error"), error_message)

    def _release_image(self):
        """Drop the shown pixmap instead of keeping it in a hidden modal."""
        self._closed = True
        self._label.clear()
        self._progress_bar.hide()

    def done(self, result):
        self._release_image()
        super().done(result)

    def closeEvent(self, event):
        self._release_image()
        super().closeEvent(event)


class PostImageEntry(NamedTuple):
    """One image inside a post, in display order."""

    name: str
    full_url: str
    thumbnail_url: str


def post_image_entries(post, domain_config=None):
    """Return the post's images in display order, without duplicates.

    The main file comes first, then attachments, then images embedded in the
    description. Pawchive's API often repeats the main file as the first
    attachment, so entries are deduplicated by their cleaned path.
    """
    if not isinstance(post, dict):
        return []
    config = domain_config if domain_config is not None else get_domain_config("")
    entries = []
    seen = set()

    def add(path, name=""):
        if not path:
            return
        full_url = clean_file_url(str(path), config)
        if not _looks_like_image(full_url):
            return
        key = urlparse(full_url).path
        if key in seen:
            return
        seen.add(key)
        thumbnail = preview_thumbnail_url(full_url, config) or full_url
        entries.append(
            PostImageEntry(
                name=str(name or os.path.basename(key) or translate("not_available")),
                full_url=full_url,
                thumbnail_url=thumbnail,
            )
        )

    main_file = post.get("file")
    if isinstance(main_file, dict) and main_file.get("path"):
        add(main_file["path"], main_file.get("name", ""))

    attachments = post.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            if isinstance(attachment, dict) and attachment.get("path"):
                add(attachment["path"], attachment.get("name", ""))

    content = post.get("content")
    if content:
        soup = BeautifulSoup(str(content), "html.parser")
        for img in soup.select("img[src]"):
            add(str(img.get("src")), "")

    return entries


def post_description_html(post):
    """Return the description HTML with non-text media removed.

    The post's images are already listed below the description, so embedded
    ``<img>`` tags are dropped instead of being fetched twice. Scripts and
    frames are removed as well: QTextBrowser must only render text.
    """
    if not isinstance(post, dict):
        return ""
    content = post.get("content")
    if not content:
        return ""
    try:
        soup = BeautifulSoup(str(content), "html.parser")
    except Exception:
        return ""
    for tag in soup.select("img, script, style, iframe, video, audio"):
        tag.decompose()
    # Content often carries inline colours meant for a light page; drop them
    # so the dark preview stays readable. Structural tags (bold, lists, links)
    # are left alone.
    for tag in soup.find_all(True):
        tag.attrs.pop("style", None)
    if not soup.get_text(strip=True):
        return ""
    return str(soup)


def _creator_api_parts(creator_url):
    """Return ``(service, creator_id)`` parsed from a creator URL."""
    url = str(creator_url or "").rstrip("/")
    parts = url.split("/")
    if len(parts) >= 3:
        service = parts[-3].split("?")[0]
        creator_id = parts[-1].split("?")[0]
        if service and creator_id:
            return service, creator_id
    return "unknown_service", "unknown_creator"


def fetch_post_data(post_id, creator_url, settings_tab=None, max_retries=1):
    """Fetch one post's JSON.

    Returns ``(post_dict, "")`` on success and ``(None, message)`` on failure.
    The preview only needs the post's own record, so this is deliberately
    narrower than the downloader's fetch-and-detect pass.
    """
    service, creator_id = _creator_api_parts(creator_url)
    domain_config = get_domain_config(creator_url)
    api_url = (
        f"{domain_config['api_base']}/{service}/user/{creator_id}/post/{post_id}"
    )
    headers = get_headers().copy()
    headers["Referer"] = domain_config["referer"]
    try:
        attempts = max(1, int(max_retries or 1))
    except (TypeError, ValueError):
        attempts = 1
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            response = get_session(settings_tab).get(
                api_url, headers=headers, timeout=(15, 30)
            )
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict):
                    post = (
                        data
                        if "post" not in data
                        else data.get("post", {})
                    )
                else:
                    post = None
                if isinstance(post, dict):
                    return post, ""
                return None, translate(
                    "invalid_posts_data_type", type(data).__name__
                )
            if (
                response.status_code == 429 or 500 <= response.status_code < 600
            ) and attempt < attempts:
                last_error = f"HTTP {response.status_code}"
                time.sleep(min(2 ** (attempt - 1), 8))
                continue
            return None, f"HTTP {response.status_code}"
        except Exception as e:
            last_error = str(e)
            if attempt < attempts:
                time.sleep(min(2 ** (attempt - 1), 8))
    return None, last_error or translate("not_available")


class PostPreviewFetchThread(QThread):
    """Fetch the post record the image list is built from."""

    fetched = pyqtSignal(str, object)
    error = pyqtSignal(str, str)

    def __init__(self, post_id, creator_url, settings_tab=None, max_retries=1):
        super().__init__()
        self.post_id = str(post_id)
        self.creator_url = str(creator_url or "")
        self.settings_tab = settings_tab
        self.max_retries = max_retries

    def run(self):
        post, message = fetch_post_data(
            self.post_id, self.creator_url, self.settings_tab, self.max_retries
        )
        if post is None:
            self.error.emit(self.post_id, message)
        else:
            self.fetched.emit(self.post_id, post)


class PostImagesLoader(QObject):
    """Background thumbnail fetcher for the post image list.

    A small pool keeps the UI responsive; each worker gets its own requests
    session via :func:`get_session`, which is per-thread by design. Images are
    decoded to QImage in the worker and converted to QPixmap on the GUI thread.
    Raw bytes are kept in a bounded LRU, either the Creator tab's shared
    session cache or a private one for a standalone loader, so scrolling back
    does not refetch.
    """

    image_ready = pyqtSignal(str, object)
    image_failed = pyqtSignal(str, str)

    def __init__(
        self,
        settings_tab=None,
        max_workers=4,
        parent=None,
        cache=None,
        cache_bytes=DEFAULT_PREVIEW_CACHE_BYTES,
    ):
        super().__init__(parent)
        self.settings_tab = settings_tab
        self._executor = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))
        self._lock = threading.Lock()
        self._in_flight = set()
        # A post preview dialog receives the Creator tab's session cache; a
        # standalone loader (tests, one-off previews) gets a private cache.
        self._cache = cache if cache is not None else PreviewImageCache(cache_bytes)
        self._owns_cache = cache is None
        self._cancelled = False

    def request(self, url):
        """Queue *url* once; cached bytes are decoded without a new request."""
        if not url:
            return
        with self._lock:
            if self._cancelled or url in self._in_flight:
                return
            self._in_flight.add(url)
        cached = self._cache.get(url)
        future = self._executor.submit(self._load, url, cached)
        future.add_done_callback(lambda f, u=url: self._finished(u, f))

    def _load(self, url, cached):
        data = (
            cached
            if cached is not None
            else _download_image_bytes(url, self.settings_tab)
        )
        return data, _decode_preview_qimage(data)

    def _finished(self, url, future):
        with self._lock:
            self._in_flight.discard(url)
        try:
            data, image = future.result()
        except Exception as e:
            with self._lock:
                cancelled = self._cancelled
            if not cancelled:
                self.image_failed.emit(url, str(e))
            return
        # Read the flag after the worker finished: stop() may have been called
        # while this request was in flight, and a stopped loader must neither
        # refill a cleared cache nor emit into a closed dialog.
        with self._lock:
            cancelled = self._cancelled
        if data and not cancelled:
            self._cache.store(url, data)
        if cancelled:
            return
        if image is None or image.isNull():
            self.image_failed.emit(url, translate("invalid_image_data"))
        else:
            self.image_ready.emit(url, image)

    @property
    def cached_bytes(self):
        return self._cache.cached_bytes

    @property
    def cached_urls(self):
        return self._cache.cached_urls

    def stop(self):
        with self._lock:
            self._cancelled = True
            self._in_flight.clear()
        if self._owns_cache:
            # A private cache dies with the loader.  A shared session cache is
            # owned by the Creator tab, so closing one dialog keeps it.
            self._cache.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)


class _ScaledImageLabel(QLabel):
    """A QLabel that paints its QImage scaled to the available width.

    The source stays at the site's 800 px thumbnail resolution; only the
    painted copy is sized to the row, so resizing the dialog does not reload
    or re-decode anything.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = None
        self._pixmap = None
        self._last_height = 180
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_source(self, image):
        self._source = image
        self._pixmap = None
        self._rebuild()

    def release_source(self):
        """Drop the decoded image but keep the row's height stable."""
        self._source = None
        self._pixmap = None
        self.clear()
        self.setFixedHeight(self._last_height)

    def _rebuild(self):
        if self._source is None or self._source.isNull():
            return
        available = self.width() if self.width() > 1 else self._source.width()
        target_width = max(1, min(available, self._source.width()))
        target_height = max(
            1, round(self._source.height() * target_width / self._source.width())
        )
        if (
            self._pixmap is not None
            and self._pixmap.width() == target_width
            and self._pixmap.height() == target_height
        ):
            return
        self._last_height = target_height
        self._pixmap = QPixmap.fromImage(
            self._source.scaled(
                target_width,
                target_height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.setPixmap(self._pixmap)
        if self.height() != self._pixmap.height():
            self.setFixedHeight(self._pixmap.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild()


class _PostImageRow(QWidget):
    """One full-width image in the post list, with a caption."""

    clicked = pyqtSignal(object)

    def __init__(self, entry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self._image = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self._image_label = _ScaledImageLabel()
        self._image_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._image_label.setText(translate("loading_image_simple"))
        self._image_label.setStyleSheet(
            "QLabel { background: #24344F; color: #8A9BB5; border-radius: 4px; }"
        )
        layout.addWidget(self._image_label)
        self._caption = QLabel(entry.name or translate("not_available"))
        self._caption.setTextFormat(Qt.TextFormat.PlainText)
        self._caption.setWordWrap(True)
        self._caption.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._caption.setStyleSheet("QLabel { color: #8A9BB5; font-size: 11px; }")
        layout.addWidget(self._caption)

    def set_image(self, image):
        self._image = image
        self._image_label.setStyleSheet(
            "QLabel { background: #24344F; border-radius: 4px; }"
        )
        self._image_label.set_source(image)

    def release_image(self):
        self._image = None
        self._image_label.setStyleSheet(
            "QLabel { background: #24344F; color: #8A9BB5; border-radius: 4px; }"
        )
        self._image_label.release_source()

    def set_error(self, _message=""):
        self._image = None
        self._image_label.release_source()
        self._image_label.setStyleSheet(
            "QLabel { background: #3A2A2A; color: #E06C75; border-radius: 4px; }"
        )
        self._image_label.setText(translate("post_preview_image_failed"))

    @property
    def has_image(self):
        return self._image is not None

    @property
    def image(self):
        return self._image

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.entry)
        super().mouseReleaseEvent(event)


class PostPreviewDialog(QDialog):
    """Show a post's description and every image in a scrollable list."""

    post_loaded = pyqtSignal(str, object)

    def __init__(
        self,
        post_id,
        creator_url,
        parent=None,
        settings_tab=None,
        post_data=None,
        max_retries=1,
        thread_registry=None,
        image_cache=None,
    ):
        super().__init__(parent)
        self._post_id = str(post_id)
        self._creator_url = str(creator_url or "")
        self._settings_tab = settings_tab
        self._max_retries = max_retries
        self._thread_registry = thread_registry
        self._image_cache = image_cache
        self._entries = []
        self._rows = []
        self._row_by_url = {}
        self._loaded_urls = set()
        self._failed_urls = set()
        self._loader = None
        self._fetch_thread = None
        self._closed = False

        self.setWindowTitle(translate("post_preview_title"))
        self.setModal(True)
        self.resize(1000, 800)
        self._build_ui()

        if isinstance(post_data, dict) and post_data:
            self._populate(post_data)
        else:
            self._start_fetch()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        header = QVBoxLayout()
        self._title_label = QLabel("")
        self._title_label.setTextFormat(Qt.TextFormat.PlainText)
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet(
            "QLabel { color: #FFFFFF; font-size: 16px; font-weight: bold; }"
        )
        header.addWidget(self._title_label)
        self._meta_label = QLabel("")
        self._meta_label.setTextFormat(Qt.TextFormat.PlainText)
        self._meta_label.setStyleSheet("QLabel { color: #8A9BB5; }")
        header.addWidget(self._meta_label)
        self._status_label = QLabel("")
        self._status_label.setTextFormat(Qt.TextFormat.PlainText)
        self._status_label.setStyleSheet("QLabel { color: #8A9BB5; }")
        header.addWidget(self._status_label)
        layout.addLayout(header)

        self._description = QTextBrowser()
        self._description.setOpenExternalLinks(True)
        self._description.setMinimumHeight(48)
        self._description.setStyleSheet(
            "QTextBrowser { background: #24344F; color: #D7E1F0; "
            "border: 1px solid #3A4B6A; border-radius: 5px; padding: 6px; }"
        )
        self._description.hide()

        self._error_label = QLabel("")
        self._error_label.setTextFormat(Qt.TextFormat.PlainText)
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet("QLabel { color: #E06C75; }")
        self._error_label.hide()
        layout.addWidget(self._error_label)

        self._retry_btn = QPushButton(translate("post_preview_retry"))
        self._retry_btn.clicked.connect(self._start_fetch)
        self._retry_btn.hide()
        layout.addWidget(self._retry_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self._container = QWidget()
        self._rows_layout = QVBoxLayout(self._container)
        self._rows_layout.setContentsMargins(4, 4, 4, 4)
        self._rows_layout.setSpacing(14)
        self._scroll.setWidget(self._container)
        self._scroll.verticalScrollBar().valueChanged.connect(self._request_visible)

        # The description and the image list share the space through a
        # vertical splitter: the description opens at roughly half its old
        # fixed height and the user can drag the divider to change it.
        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(6)
        self._splitter.setStyleSheet(
            "QSplitter::handle:vertical { background: #3A4B6A; height: 5px; }"
        )
        self._splitter.addWidget(self._description)
        self._splitter.addWidget(self._scroll)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setSizes([60, 600])
        layout.addWidget(self._splitter, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        self._close_btn = QPushButton(translate("close"))
        self._close_btn.clicked.connect(self.accept)
        close_row.addWidget(self._close_btn)
        layout.addLayout(close_row)


    def _start_fetch(self):
        self._error_label.hide()
        self._retry_btn.hide()
        self._status_label.setText(translate("loading_post"))
        thread = self._fetch_thread
        if thread is not None and thread.isRunning():
            return
        thread = PostPreviewFetchThread(
            self._post_id, self._creator_url, self._settings_tab, self._max_retries
        )
        self._fetch_thread = thread
        thread.fetched.connect(self._on_post_fetched)
        thread.error.connect(self._on_post_error)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread: self._forget_fetch(t))
        registry = self._thread_registry
        if registry is not None:
            registry.append(thread)
            thread.finished.connect(
                lambda t=thread, r=registry: r.remove(t) if t in r else None
            )
        thread.start()

    def _forget_fetch(self, thread):
        if self._fetch_thread is thread:
            self._fetch_thread = None

    def _on_post_fetched(self, post_id, post):
        self.post_loaded.emit(post_id, post)
        if getattr(self, "_closed", False):
            # The user closed the dialog while the API request was in flight;
            # the tab still caches the record, but there is no list to build.
            return
        self._populate(post)

    def _on_post_error(self, post_id, message):
        if getattr(self, "_closed", False):
            return
        self._status_label.setText("")
        self._error_label.setText(translate("post_preview_load_failed", message))
        self._error_label.show()
        self._retry_btn.show()

    def _clear_rows(self):
        if self._loader is not None:
            self._loader.stop()
            self._loader.deleteLater()
            self._loader = None
        # Rows hold decoded QImages and scaled QPixmaps.  Drop them now:
        # deleteLater() only destroys the widgets on the next event-loop pass,
        # and the dialog itself is a Qt child of the Creator tab.
        for row in self._rows:
            try:
                row.release_image()
            except RuntimeError:
                pass
        self._rows = []
        self._row_by_url.clear()
        self._entries = []
        self._loaded_urls.clear()
        self._failed_urls.clear()
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _populate(self, post):
        self._clear_rows()
        title = str(post.get("title") or "").strip()
        self._title_label.setText(title or translate("not_available"))
        raw_published = str(post.get("published") or post.get("added") or "").strip()
        published = iso_to_local_date(raw_published) or raw_published
        domain_config = get_domain_config(self._creator_url)
        self._entries = post_image_entries(post, domain_config)
        meta_parts = []
        if published:
            meta_parts.append(published)
        if self._entries:
            meta_parts.append(
                translate("post_preview_images_count", len(self._entries))
            )
        self._meta_label.setText(" · ".join(meta_parts))

        description = post_description_html(post)
        if description:
            self._description.setHtml(description)
            self._description.show()
            QTimer.singleShot(0, self._fit_description)
        else:
            self._description.hide()

        if not self._entries:
            self._status_label.setText(translate("post_preview_no_images"))
            return

        self._status_label.setText(
            translate("post_preview_loading_images", 0, len(self._entries))
        )
        self._loader = PostImagesLoader(
            self._settings_tab,
            max_workers=4,
            parent=self,
            cache=self._image_cache,
        )
        self._loader.image_ready.connect(self._on_image_ready)
        self._loader.image_failed.connect(self._on_image_failed)

        for entry in self._entries:
            row = _PostImageRow(entry)
            row.clicked.connect(self._open_image)
            self._rows_layout.addWidget(row)
            self._rows.append(row)
            self._row_by_url[entry.thumbnail_url] = row
        self._rows_layout.addStretch(1)

        if len(self._entries) <= 8:
            for entry in self._entries:
                self._loader.request(entry.thumbnail_url)
        else:
            QTimer.singleShot(0, self._request_visible)

    def _fit_description(self):
        """Open the description at its content height, capped at 120 px."""
        if self._description.isHidden():
            return
        document = self._description.document()
        width = self._description.viewport().width()
        if width <= 1:
            width = max(240, self.width() - 40)
        document.setTextWidth(width)
        content_height = int(document.size().height()) + 18
        target = max(56, min(content_height, 120))
        total = self._splitter.height()
        if total <= 1:
            total = 600
        self._splitter.setSizes([target, max(1, total - target)])


    def _request_visible(self):
        if self._loader is None or not self._rows:
            return
        if not any(row.geometry().height() > 0 for row in self._rows):
            # The layout has not run yet: load the first screen and let the
            # next call (after layout) apply the real viewport window.
            for index in range(min(len(self._rows), 8)):
                self._loader.request(self._entries[index].thumbnail_url)
            return
        scroll_y = self._scroll.verticalScrollBar().value()
        viewport_height = max(1, self._scroll.viewport().height())
        top = scroll_y - viewport_height
        bottom = scroll_y + viewport_height * 2
        visible = []
        for index, row in enumerate(self._rows):
            geometry = row.geometry()
            if geometry.bottom() >= top and geometry.top() <= bottom:
                visible.append(index)
        for index in visible:
            row = self._rows[index]
            if not row.has_image:
                self._loader.request(self._entries[index].thumbnail_url)
        if visible:
            keep_from = max(0, visible[0] - 20)
            keep_to = min(len(self._rows) - 1, visible[-1] + 20)
            for index, row in enumerate(self._rows):
                if (index < keep_from or index > keep_to) and row.has_image:
                    row.release_image()

    def _on_image_ready(self, url, image):
        row = self._row_by_url.get(url)
        if row is None:
            return
        row.set_image(image)
        self._loaded_urls.add(url)
        self._failed_urls.discard(url)
        self._update_status()
        QTimer.singleShot(0, self._request_visible)

    def _on_image_failed(self, url, message):
        row = self._row_by_url.get(url)
        if row is not None:
            row.set_error(message)
        self._failed_urls.add(url)
        self._update_status()

    def _update_status(self):
        total = len(self._entries)
        loaded = len(self._loaded_urls)
        failed = len(self._failed_urls)
        if total and loaded + failed >= total and failed:
            self._status_label.setText(
                translate("post_preview_images_failed", failed, total)
            )
        elif total and loaded >= total:
            self._status_label.setText(
                translate("post_preview_images_count", total)
            )
        else:
            self._status_label.setText(
                translate("post_preview_loading_images", loaded, total)
            )

    def _open_image(self, entry):
        row = self._row_by_url.get(entry.thumbnail_url)
        initial = row.image if row is not None else None
        modal = ImageModal(
            entry.thumbnail_url,
            self,
            settings_tab=self._settings_tab,
            initial_image=initial,
        )
        try:
            modal.exec()
        finally:
            delete_later = getattr(modal, "deleteLater", None)
            if delete_later is not None:
                delete_later()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._request_visible)

    def done(self, result):
        self._shutdown()
        super().done(result)

    def closeEvent(self, event):
        self._shutdown()
        super().closeEvent(event)

    def _shutdown(self):
        """Stop loading and drop every decoded image before the dialog hides."""
        self._closed = True
        self._clear_rows()


# Block-level HTML elements render as separate lines/blocks, so they stay
# hard word boundaries when the description is re-joined for keyword
# matching. Text from two paragraphs (or table cells) must never be fused
# into a single word.
_BLOCK_HTML_TAGS = frozenset(
    {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
)


def _tag_glued_text(soup):
    """Return the soup's text with the separators *between inline tags*
    removed, keeping block-level elements as boundaries.

    ``BeautifulSoup.get_text(" ")`` inserts a space between every pair of
    adjacent text nodes, even where the HTML has none. That turns
    ``<b>Alien</b>Comic`` (one word on the page) into two words, and turns
    ``Alien <b>Comic</b>`` (one space on the page) into a double space, so
    keywords that are plainly visible in the post could not match.

    This rendering keeps every character the author actually typed and only
    drops the injected separators: block-level tags become a newline, inline
    tags contribute nothing. Nothing is collapsed or trimmed, so author-typed
    whitespace (including multiple spaces and ``&nbsp;``) is preserved
    exactly as in the space-joined rendering.
    """
    parts = []
    for node in soup.descendants:
        if isinstance(node, NavigableString):
            if getattr(node.parent, "name", None) in ("script", "style"):
                continue
            parts.append(str(node))
        elif getattr(node, "name", None) in _BLOCK_HTML_TAGS:
            parts.append("\n")
    return "".join(parts)


def _is_word_edge(char):
    """True when *char* is one of the ASCII characters [a-z0-9] the keyword
    lookarounds treat as alphanumeric. Keywords reach this lower-cased."""
    return char.isascii() and char.isalnum()


def _keyword_matches_text(keywords, text, lenient=False, lenient_punctuation=False):
    """Case-insensitive match of any keyword in *text*.

    Strict (default) matching is whole-word: non-alphanumeric characters
    (including _, -, ., /, spaces, curly braces, etc.) are valid word
    boundaries in addition to string start/end. A keyword edge that is a
    word character must be delimited by the text around it; a keyword edge
    that is *enclosing* punctuation (brackets, braces, CJK brackets, quotes —
    see :data:`ENCLOSING_PUNCTUATION`) is its own delimiter, so "[JP]"
    matches "123[JP] art" and "【JP】" matches "123【JP】 art". Joiners such as
    ".", "-", "_" or "+" stay inside a token: ".5" does not match "1.5" and
    "zip-" does not match "zip-01.png". No normalization is performed — the
    keyword must appear exactly (case-insensitive). This avoids false
    positives from camelCase splitting (e.g. 'sketch' will NOT match
    'SketchBook').

    *lenient_punctuation* restores the wider rule where any punctuation at a
    keyword edge is its own delimiter (".5" matches "1.5", "zip-" matches
    "zip-01.png"). *lenient* drops the boundary rule entirely: a plain
    substring hit is enough, so "bean" matches "beanstoast".

    Shared by PostDetectionThread (post/title-level skip) and
    FilePreparationThread (individual-file-level skip).
    """
    if not keywords or not text:
        return False
    text_lower = text.lower()
    if not text_lower:
        return False
    for keyword in keywords:
        if not keyword:
            continue
        keyword_lower = keyword.lower()
        if not keyword_lower:
            continue
        if lenient:
            # Lenient: any occurrence counts, boundaries ignored.
            if keyword_lower in text_lower:
                return True
            continue
        if lenient_punctuation:
            lead = "" if not _is_word_edge(keyword_lower[0]) else r"(?<![a-z0-9])"
            trail = "" if not _is_word_edge(keyword_lower[-1]) else r"(?![a-z0-9])"
        else:
            lead = (
                "" if keyword_lower[0] in ENCLOSING_PUNCTUATION else r"(?<![a-z0-9])"
            )
            trail = (
                "" if keyword_lower[-1] in ENCLOSING_PUNCTUATION else r"(?![a-z0-9])"
            )
        # re.escape() cannot produce an invalid pattern, so this is a plain
        # whole-word search; the old re.error fallback was unreachable.
        if re.search(lead + re.escape(keyword_lower) + trail, text_lower):
            return True
    return False


def _first_matching_keyword(keywords, text, lenient=False, lenient_punctuation=False):
    """Return the first keyword that matches *text*, or "".

    Thin wrapper around :func:`_keyword_matches_text`, used purely so the
    log line and the counters can name the keyword that matched. Keywords
    are tried in the order the user typed them, so overlapping keywords are
    credited to the first one listed.
    """
    for keyword in keywords or []:
        if keyword and _keyword_matches_text(
            [keyword], text, lenient, lenient_punctuation
        ):
            return keyword
    return ""


class PostDetectionThread(_StoppableThread, QThread):
    finished = pyqtSignal(list)
    posts_batch = pyqtSignal(list)
    log = pyqtSignal(str, str)
    error = pyqtSignal(str)
    # (creator url, display name) once the profile endpoint answers.
    creator_name_found = pyqtSignal(str, str)

    def __init__(
        self,
        url,
        post_titles_map,
        settings,
        skip_keywords=None,
        skip_keywords_scopes=None,
        post_dates_map=None,
        date_after=None,
        date_before=None,
        file_count_min=None,
        file_count_max=None,
        file_count_keep_compressed=False,
        required_filetypes=None,
        post_search_index=None,
        found_extensions=None,
        post_filters=None,
        report_creator_name=False,
    ):
        super().__init__()
        self.url = url
        self.report_creator_name = bool(report_creator_name)
        self.post_titles_map = post_titles_map  # Shared dictionary to store post titles
        self.post_dates_map = post_dates_map if post_dates_map is not None else {}
        self.settings = settings
        self.is_running = True
        self.domain_config = get_domain_config(url)
        self.skip_keywords = skip_keywords if skip_keywords is not None else []
        # Set of scopes to check keywords against: any of "title",
        # "filenames", "description", "tags". A post is skipped if the
        # keyword matches in ANY enabled scope.
        if skip_keywords_scopes is None:
            # Legacy default when the caller doesn't specify scopes at all.
            self.skip_keywords_scopes = {"title"}
        else:
            # Respect the caller's exact selection — including an empty
            # set, which means no scope is checked and therefore no
            # post should be skipped by keyword.
            self.skip_keywords_scopes = set(skip_keywords_scopes)
        # Optional post-date range filter (datetime.date objects, inclusive).
        # Only the post's own publish date is considered, never the import date.
        self.date_after = date_after
        self.date_before = date_before
        # Optional post file-count range filter (both bounds inclusive, both
        # optional). "Keep Archives" makes posts holding a ZIP/7Z/RAR bypass
        # the range check entirely so archive posts are never lost.
        self.file_count_min = file_count_min
        self.file_count_max = file_count_max
        self.file_count_keep_compressed = file_count_keep_compressed
        # Optional set of extensions a post must hold at least one file of.
        # An empty set leaves the filter off: with nothing ticked in the
        # grid there is no type to require, so the right answer to "no
        # selected filetypes" is to change nothing, not to drop every post.
        self.required_filetypes = {
            normalize_extension(ext) for ext in (required_filetypes or ()) if ext
        }
        # Optional shared dict (post_id -> lower-case searchable text) that
        # feeds the Creator tab's "Search by" scopes. Only filled when the
        # caller passes a dict, so plain detection runs stay cost-free.
        self.post_search_index = post_search_index
        # Optional shared dict (extension -> number of posts holding it), so
        # the Creator tab can show the types this creator actually has. Like
        # the search index it is only filled when the caller passes a dict.
        self.found_extensions = found_extensions
        # One immutable value describing every post-level filter. The tab
        # passes the same shape to its live filter pass, so both apply
        # exactly the same rules; the individual options above stay as the
        # readable spelling for callers that only set one of them.
        self.post_filters = post_filters or PostFilters(
            skip_keywords=tuple(self.skip_keywords),
            skip_scopes=frozenset(self.skip_keywords_scopes),
            date_after=self.date_after,
            date_before=self.date_before,
            file_count_min=self.file_count_min,
            file_count_max=self.file_count_max,
            keep_compressed=self.file_count_keep_compressed,
            # Empty means "no requirement" for callers using the individual
            # options, which is the off state, not "on with nothing ticked".
            required_filetypes=frozenset(self.required_filetypes) or None,
        )
        self._skipped_count = 0
        self._keyword_skipped_count = 0
        self._date_skipped_count = 0
        self._file_count_skipped_count = 0
        self._filetype_skipped_count = 0
        # keyword -> number of posts it dropped, for the skip tooltip.
        self.keyword_skip_counts = {}
        # post_id -> analyze_post() result, so a post's HTML body is parsed at
        # most once per detection run even when several filters need it.
        self._analysis_cache = {}

    def _analyze(self, post):
        """Return the cached :func:`analyze_post` result for *post*."""
        post_id = post.get("id")
        analysis = self._analysis_cache.get(post_id)
        if analysis is None:
            analysis = analyze_post(post)
            self._analysis_cache[post_id] = analysis
        return analysis

    def _record_found_extensions(self, analysis):
        """Add this post's per-type file counts into found_extensions.

        The values are file counts, not post counts, so each extension box can
        say ".png (412)" without re-walking any payload.
        """
        if self.found_extensions is None:
            return
        counts = analysis.get("extension_counts") or {
            ext: 1 for ext in analysis.get("extensions") or []
        }
        for ext, amount in counts.items():
            self.found_extensions[ext] = self.found_extensions.get(ext, 0) + int(
                amount or 0
            )

    def _report_creator_name(self, service, creator_id):
        """Report the creator's display name when the profile endpoint answers.

        The name is decoration on the queue row, so every failure is ignored:
        the posts fetch below is what the user is actually waiting for.
        """
        try:
            name = fetch_creator_display_name(
                self.settings.settings_tab,
                self.domain_config,
                service,
                creator_id,
            )
            if name:
                self.creator_name_found.emit(self.url, name)
        except Exception:
            return

    def run(self):
        """Run the detection pass, always leaving the tab able to continue.

        Everything this thread touches comes off the network, so an
        unexpected shape (``attachments: null``, a non-dict ``file``) used
        to raise inside ``run``: Qt printed the traceback to stderr, no
        signal was emitted, and the tab stayed in its fetching state with
        every other tab disabled. Whatever goes wrong now reaches the tab,
        whose error handler unlocks the UI.
        """
        try:
            self._run()
        except Exception as e:
            try:
                self.log.emit(
                    translate(
                        "log_error", translate("unexpected_error_detecting", str(e))
                    ),
                    "ERROR",
                )
            except Exception:
                pass
            # A cancelled run stops on purpose: the cancel path owns the
            # cleanup, so only a genuine failure is reported here.
            if self.is_running:
                try:
                    self.error.emit(str(e))
                except Exception:
                    pass

    def _run(self):
        try:
            if not self.is_running:
                return

            # Parse URL to handle query parameters correctly and extract clean ID and service
            parsed_url = urlparse(self.url)
            path = parsed_url.path.strip("/")
            path_parts = path.split("/")
        except Exception as e:  # Top-level protection to at least log Python exceptions
            try:
                self.log.emit(translate("log_error", str(e)), "ERROR")
                self.error.emit(str(e))
            except Exception:
                pass
            return
        # Check validity.
        # path_parts should end with user/{id}
        # Example: fanbox/user/12345 -> parts: ['fanbox', 'user', '12345']
        if (
            len(path_parts) < 3
            or (
                self.domain_config["domain"] not in self.url
                and "coomer" not in self.url
            )
            or path_parts[-2] != "user"
        ):
            # Fallback to original split if basic check fails, though likely invalid
            parts = self.url.split("/")
            if (
                len(parts) < 5
                or (self.domain_config["domain"] not in self.url)
                or parts[-2] != "user"
            ):
                self.error.emit(translate("invalid_url_format"))
                return
            else:
                # If fallback worked (e.g. some weird URL structure I didn't anticipate)
                service, creator_id = parts[-3], parts[-1]
                # Clean creator_id from potential query params if using split
                if "?" in creator_id:
                    creator_id = creator_id.split("?")[0]
        else:
            service = path_parts[-3]
            creator_id = path_parts[-1]

        self.log.emit(
            translate("log_info", translate("checking_creator_with_url", self.url)),
            "INFO",
        )
        self.log.emit(
            translate(
                "log_debug",
                translate("parsed_url_service_creator", service, creator_id),
            ),
            "DEBUG",
        )

        base_api_url = f"{self.domain_config['api_base']}/{service}/user/{creator_id}"
        self.log.emit(
            translate("log_debug", translate("base_api_url", base_api_url)), "DEBUG"
        )

        # Parse query parameters
        query_params = parse_qs(parsed_url.query)
        search_query = query_params.get("q", [None])[0]
        offset_param = query_params.get("o", [None])[0]

        start_offset = 0
        single_page_target = False

        if offset_param:
            try:
                start_offset = int(offset_param)
                single_page_target = True
                self.log.emit(
                    translate(
                        "log_info",
                        f"Validation started with specific offset: {start_offset}",
                    ),
                    "INFO",
                )
            except ValueError:
                self.log.emit(
                    translate(
                        "log_warning", f"Invalid offset parameter: {offset_param}"
                    ),
                    "WARNING",
                )

        if search_query:
            self.log.emit(
                translate("log_info", f"Search query detected: {search_query}"), "INFO"
            )

        all_posts = []  # Accumulate raw post dicts for pagination checks
        all_processed_posts = []  # Accumulate (title, (post_id, thumbnail_url)) tuples
        offset = start_offset
        page_size = 50
        max_attempts = self.settings.creator_posts_max_attempts

        attempt = 1
        while attempt <= max_attempts and self.is_running:
            # Construct query string suffix. The search term is re-encoded:
            # parse_qs already decoded it, so pasting it back raw broke on
            # names containing &, #, + or %.
            query_suffix = f"?o={offset}"
            if search_query:
                query_suffix += "&" + urlencode({"q": search_query})

            alternative_urls = [
                f"{self.domain_config['api_base']}/{service}/user/{creator_id}/posts{query_suffix}",  # Try with /posts suffix
                f"{base_api_url}{query_suffix}",  # Original format as fallback
                f"{self.domain_config['base_url']}/api/{service}/user/{creator_id}{query_suffix}",  # Try without v1
            ]

            # Add variant with explicit offset/limit/q if needed, though usually standard params work
            # For 4th option in original code:
            alt_suffix_4 = f"?offset={offset}&limit={page_size}"
            if search_query:
                alt_suffix_4 += "&" + urlencode({"q": search_query})
            alternative_urls.append(f"{base_api_url}{alt_suffix_4}")

            success = False
            response = None
            likely_last_page = len(all_posts) > 0 and len(all_posts) % page_size != 0

            for alt_url in alternative_urls:
                if not self.is_running:
                    return
                self.log.emit(
                    translate("log_debug", translate("trying_endpoint", alt_url)),
                    "DEBUG",
                )

                fallback_headers = {
                    "User-Agent": get_user_agent(),
                    "Accept": "text/css",
                    "Accept-Language": accept_language,
                    "Connection": "keep-alive",
                    "Cache-Control": "max-age=0",
                    "Referer": self.domain_config["referer"],
                }

                try:
                    alt_response = get_session(self.settings.settings_tab).get(
                        alt_url, headers=fallback_headers, timeout=15
                    )
                    if alt_response.status_code == 200:
                        response = alt_response
                        self.log.emit(
                            translate(
                                "log_info", translate("endpoint_successful", alt_url)
                            ),
                            "INFO",
                        )
                        success = True
                        break
                    else:
                        if likely_last_page or len(all_posts) > 0:
                            self.log.emit(
                                translate(
                                    "log_debug",
                                    translate(
                                        "endpoint_returned_status_likely_end",
                                        alt_response.status_code,
                                        alt_url,
                                    ),
                                ),
                                "DEBUG",
                            )
                        else:
                            self.log.emit(
                                translate(
                                    "log_debug",
                                    translate(
                                        "endpoint_failed_with_status",
                                        alt_url,
                                        alt_response.status_code,
                                    ),
                                ),
                                "DEBUG",
                            )
                except requests.RequestException as alt_e:
                    if likely_last_page or len(all_posts) > 0:
                        self.log.emit(
                            translate(
                                "log_debug",
                                translate(
                                    "endpoint_unavailable_likely_end",
                                    alt_url,
                                    str(alt_e),
                                ),
                            ),
                            "DEBUG",
                        )
                    else:
                        self.log.emit(
                            translate(
                                "log_debug",
                                translate(
                                    "endpoint_error_with_exception", alt_url, str(alt_e)
                                ),
                            ),
                            "DEBUG",
                        )

            if not success:
                if len(all_posts) > 0:
                    self.log.emit(
                        translate(
                            "log_info",
                            translate("reached_last_page", creator_id, len(all_posts)),
                        ),
                        "INFO",
                    )
                    break
                else:
                    self.log.emit(
                        translate(
                            "log_error",
                            translate("all_api_endpoints_failed", creator_id),
                        ),
                        "ERROR",
                    )
                    break

            if not self.is_running:
                return

            response_text = ""
            try:

                is_gzipped = response.content[:2] == b"\x1f\x8b"

                if is_gzipped:
                    try:
                        decompressed = gzip.decompress(response.content)
                        response_text = decompressed.decode("utf-8")
                        self.log.emit(
                            translate(
                                "log_debug",
                                translate("successfully_decompressed_gzipped_response"),
                            ),
                            "DEBUG",
                        )
                    except (gzip.BadGzipFile, UnicodeDecodeError, EOFError) as e:
                        self.log.emit(
                            translate(
                                "log_warning",
                                translate("gzip_decompression_failed", str(e)),
                            ),
                            "WARNING",
                        )
                        response_text = getattr(response, "text", "")
                else:
                    # Content is not gzipped, use as plain text
                    response_text = getattr(response, "text", "")

                # Check if response is empty or just whitespace
                if not response_text.strip():
                    self.log.emit(
                        translate(
                            "log_info", translate("empty_response_at_offset", offset)
                        ),
                        "INFO",
                    )
                    break

                if not self.is_running:
                    return

                posts_data = json.loads(response_text or "")

            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                self.log.emit(
                    translate(
                        "log_error", translate("failed_to_parse_response", str(e))
                    ),
                    "ERROR",
                )
                self.log.emit(
                    translate(
                        "log_debug",
                        translate(
                            "response_content_first_500_chars",
                            (response_text or "")[:500],
                        ),
                    ),
                    "DEBUG",
                )
                break

            if not isinstance(posts_data, list):
                # Sometimes the API returns an object with a posts array
                if isinstance(posts_data, dict):
                    if "posts" in posts_data:
                        posts_data = posts_data["posts"]
                    elif "data" in posts_data:
                        posts_data = posts_data["data"]
                    else:
                        self.log.emit(
                            translate(
                                "log_error",
                                translate(
                                    "unexpected_response_structure",
                                    (
                                        list(posts_data.keys())
                                        if posts_data
                                        else "empty dict"
                                    ),
                                ),
                            ),
                            "ERROR",
                        )
                        break
                else:
                    self.log.emit(
                        translate(
                            "log_error",
                            translate("invalid_posts_data_type", type(posts_data)),
                        ),
                        "ERROR",
                    )
                    break

            self.log.emit(
                translate(
                    "log_debug",
                    translate("fetched_posts_at_offset", len(posts_data), offset),
                ),
                "DEBUG",
            )

            if len(posts_data) < page_size and len(posts_data) > 0:
                self.log.emit(
                    translate(
                        "log_info",
                        translate(
                            "received_less_than_page_size", len(posts_data), page_size
                        ),
                    ),
                    "INFO",
                )

            for post in posts_data:
                if not isinstance(post, dict):
                    continue
                post_id = post.get("id")
                if not post_id:
                    continue
                title = post.get("title", f"Post {post_id}")
                self.log.emit(
                    translate(
                        "log_debug", translate("post_id_and_title", post_id, title)
                    ),
                    "DEBUG",
                )
                # Store title in shared post_titles_map
                self.post_titles_map[(service, creator_id, post_id)] = (
                    sanitize_filename(title)
                )
                # One analysis per post carries the publish date, the search
                # text and every fact a post filter needs, so the tab can
                # re-apply filters later without fetching the posts again.
                analysis = self._analyze(post)
                parsed_date = analysis.get("published")
                self.post_dates_map[post_id] = (
                    parsed_date.strftime("%Y-%m-%d") if parsed_date else "Unknown date"
                )
                if self.post_search_index is not None:
                    self.post_search_index[post_id] = {
                        "filenames": analysis["filenames"],
                        "description": analysis["description"],
                        "tags": analysis["tags"],
                        "filenames_list": analysis.get("filenames_list") or [],
                        "tag_list": analysis.get("tag_list") or [],
                        "description_glued": analysis.get("description_glued") or "",
                        "file_count": analysis.get("file_count", 0),
                        "has_compressed": bool(analysis.get("has_compressed")),
                        "extensions": analysis.get("extensions") or [],
                        "published": parsed_date,
                    }
                self._record_found_extensions(analysis)

            if not posts_data:
                self.log.emit(
                    translate("log_info", translate("no_more_posts_at_offset", offset)),
                    "INFO",
                )
                break

            # Process posts for this batch (thumbnail extraction + skip filtering)
            batch_posts = []
            for post in posts_data:
                if not isinstance(post, dict):
                    continue
                post_id = post.get("id")
                if not post_id:
                    continue
                title = post.get("title", f"Post {post_id}")
                facts = self._analyze(post)
                reason, keyword = post_skip_reason(title, facts, self.post_filters)

                # The post is booked under the first filter that caught it,
                # so the per-filter numbers stay mutually exclusive and add
                # up to the number of skipped posts. It is still listed: the
                # tab keeps the whole fetched list so a filter change can
                # bring it straight back without another fetch.
                if reason == "keywords":
                    self._keyword_skipped_count += 1
                    self.keyword_skip_counts[keyword] = (
                        self.keyword_skip_counts.get(keyword, 0) + 1
                    )
                    if keyword_needed_rejoin(keyword, facts, self.post_filters):
                        self.log.emit(
                            translate(
                                "log_debug",
                                translate("skip_keyword_matched_after_rejoin", keyword),
                            ),
                            "DEBUG",
                        )
                elif reason == "date":
                    self._date_skipped_count += 1
                elif reason == "file_count":
                    self._file_count_skipped_count += 1
                elif reason == "filetypes":
                    self._filetype_skipped_count += 1
                if reason is not None:
                    self._skipped_count += 1
                thumbnail_url = None
                # The API has been seen to send ``"attachments": null`` and a
                # non-dict ``file``; neither is a reason to lose the whole
                # fetch, so anything unexpected is simply "no thumbnail".
                main_file = post.get("file")
                if isinstance(main_file, dict) and main_file.get("path"):
                    if (
                        main_file["path"]
                        .lower()
                        .endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
                    ):
                        thumbnail_url = clean_file_url(
                            main_file["path"], self.domain_config
                        )
                attachments = post.get("attachments")
                if not thumbnail_url and isinstance(attachments, list):
                    for attachment in attachments:
                        if (
                            isinstance(attachment, dict)
                            and "path" in attachment
                            and attachment["path"]
                            .lower()
                            .endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
                        ):
                            thumbnail_url = clean_file_url(
                                attachment["path"], self.domain_config
                            )
                            break
                if (
                    not thumbnail_url
                    and isinstance(main_file, dict)
                    and main_file.get("path")
                ):
                    thumbnail_url = clean_file_url(
                        main_file["path"], self.domain_config
                    )
                batch_posts.append((title, (post_id, thumbnail_url)))

            # Accumulate raw posts for pagination checks
            all_posts.extend(posts_data)

            # Accumulate processed tuples for the final finished.emit()
            all_processed_posts.extend(batch_posts)

            # Emit batch of processed posts
            if batch_posts:
                self.posts_batch.emit(batch_posts)

            # If user requested a single page (via offset parameter), stop after the first successful batch
            if single_page_target:
                self.log.emit(
                    translate("log_info", "Single page request satisfied, stopping."),
                    "INFO",
                )
                break

            if len(posts_data) < page_size:
                self.log.emit(
                    translate(
                        "log_info",
                        translate(
                            "last_page_reached_with_counts",
                            len(posts_data),
                            page_size,
                            len(all_posts),
                        ),
                    ),
                    "INFO",
                )
                break

            offset += page_size
            attempt += 1
            time.sleep(0.5)

        if self.is_running:
            self.filtered_count = self._skipped_count
            self.date_skipped_count = self._date_skipped_count
            self.keyword_skipped_count = self._keyword_skipped_count
            self.file_count_skipped_count = self._file_count_skipped_count
            self.filetype_skipped_count = self._filetype_skipped_count
            self.total_detected = len(all_posts)
            self.finished.emit(all_processed_posts)
            # Decoration only, and after the posts are already on their way:
            # the queue row shows the creator's name once this answers. Off by
            # default so a detection pass makes exactly the requests it did
            # before; the tab opts in.
            if self.report_creator_name:
                self._report_creator_name(service, creator_id)


class CreatorNameLookupThread(_StoppableThread, QThread):
    """Fetch just a creator's display name for its queue row.

    This is the same tiny profile request the downloader makes before a run,
    but on its own so a queued URL can show its name within a moment of being
    added, instead of waiting for the creator to be loaded. It deliberately
    touches nothing else: no posts, no files, no folder state.
    """

    found = pyqtSignal(str, str)  # creator url, display name

    def __init__(self, creator_url, settings_tab):
        super().__init__()
        self.creator_url = str(creator_url or "")
        self.settings_tab = settings_tab

    def run(self):
        """Look the name up; every failure is silent by design."""
        url = self.creator_url.rstrip("/")
        service, creator_id = split_creator_url(url)
        if not self.is_running or service == "unknown_service":
            return
        try:
            name = fetch_creator_display_name(
                self.settings_tab,
                get_domain_config(url),
                service,
                creator_id,
                timeout=CREATOR_NAME_LOOKUP_TIMEOUT,
            )
            if self.is_running and name:
                self.found.emit(url, name)
        except Exception:
            pass
        finally:
            # A bulk import queues many lookups; a small gap between requests
            # keeps the API from being hammered.
            time.sleep(CREATOR_NAME_LOOKUP_DELAY)


class PostPopulationThread(_StoppableThread, QThread):
    finished = pyqtSignal(dict, list)
    log = pyqtSignal(str, str)

    def __init__(self, detected_posts, post_dates_map=None):
        super().__init__()
        self.detected_posts = detected_posts
        self.post_dates_map = post_dates_map if post_dates_map is not None else {}
        self.is_running = True

    def run(self):
        if not self.is_running:
            return
        post_url_map = {}
        for post_title, (post_id, thumbnail_url) in self.detected_posts:
            post_date = self.post_dates_map.get(post_id, "Unknown date")
            unique_title = f"{post_title} ({post_date})"
            post_url_map[unique_title] = (post_id, thumbnail_url)
            self.log.emit(
                translate(
                    "log_debug",
                    translate(
                        "mapped_title_to_id_and_thumbnail",
                        unique_title,
                        post_id,
                        thumbnail_url,
                    ),
                ),
                "DEBUG",
            )
        self.log.emit(
            translate(
                "log_debug",
                translate(
                    "prepared_posts_for_population",
                    len(self.detected_posts),
                    len(post_url_map),
                ),
            ),
            "DEBUG",
        )
        self.finished.emit(post_url_map, self.detected_posts)


class FilterThread(_StoppableThread, QThread):
    """Apply the search bar and the post filters to the loaded post list.

    This is the one place that decides what the Creator tab lists: the fetch
    no longer drops posts, so re-running this pass is all a filter change
    costs. The rules themselves live in :func:`post_skip_reason`, shared with
    the fetch, so the list always matches what a fetch would have produced.
    """

    finished = pyqtSignal(list)

    def __init__(
        self,
        all_detected_posts,
        checked_urls,
        search_text,
        search_scopes=None,
        post_search_index=None,
        post_filters=None,
        creator_url=None,
        file_skip_keywords=None,
        file_skip_lenient=False,
        lenient_punctuation=False,
    ):
        super().__init__()
        self.all_detected_posts = all_detected_posts
        # Which creator this pass belongs to, so a pass that finishes after
        # the view moved on can be thrown away instead of painted.
        self.creator_url = creator_url
        self.checked_urls = checked_urls.copy()
        self.search_text = (search_text or "").lower()
        # Scopes the search bar looks in: any of "title", "filenames",
        # "description", "tags". An empty set falls back to the title.
        self.search_scopes = set(search_scopes) if search_scopes else {"title"}
        # post_id -> facts about that post, built while detecting posts.
        self.post_search_index = (
            post_search_index if post_search_index is not None else {}
        )
        self.post_filters = post_filters if post_filters is not None else PostFilters()
        # Same attribute names the detection thread publishes, so the run
        # summary can read whichever of the two produced the numbers.
        self.keyword_skipped_count = 0
        self.date_skipped_count = 0
        self.file_count_skipped_count = 0
        self.filetype_skipped_count = 0
        self.filtered_count = 0
        self.keyword_skip_counts = {}
        # Posts with no facts entry: their filters cannot be applied.
        self.facts_missing_count = 0
        # File-keyword skips follow the listed posts, using the names stored
        # with each post, so the file row moves with the list too.
        self.file_skip_keywords = list(file_skip_keywords or ())
        # Substring matching for the file list, from the "Keyword Matching
        # Rules" setting (Relaxed (Files)/(Both)). Snapshotted with the
        # keywords.
        self.file_skip_lenient = bool(file_skip_lenient)
        # "Punctuation Matching Rules: Relaxed" — snapshotted from Settings.
        self.lenient_punctuation = bool(lenient_punctuation)
        self.file_keyword_skipped_count = 0
        self.file_keyword_skip_counts = {}
        self.is_running = True

    def _count_skip(self, reason, keyword):
        """Book one skipped post under the filter that caught it."""
        self.filtered_count += 1
        if reason == "keywords":
            self.keyword_skipped_count += 1
            self.keyword_skip_counts[keyword] = (
                self.keyword_skip_counts.get(keyword, 0) + 1
            )
        elif reason == "date":
            self.date_skipped_count += 1
        elif reason == "file_count":
            self.file_count_skipped_count += 1
        elif reason == "filetypes":
            self.filetype_skipped_count += 1

    def run(self):
        if not self.is_running:
            return
        filtered_items = []
        for post_title, (post_id, thumbnail_url) in self.all_detected_posts:
            if not self.is_running:
                break
            facts = self.post_search_index.get(post_id)
            if facts is None:
                self.facts_missing_count += 1
            reason, keyword = post_skip_reason(post_title, facts, self.post_filters)
            if reason is not None:
                self._count_skip(reason, keyword)
                continue
            if not post_matches_search(
                post_title,
                post_id,
                self.search_text,
                self.search_scopes,
                self.post_search_index,
            ):
                continue
            if self.file_skip_keywords:
                for name in (facts or {}).get("filenames_list") or ():
                    matched = _first_matching_keyword(
                        self.file_skip_keywords,
                        filename_without_extension(name),
                        self.file_skip_lenient,
                        self.lenient_punctuation,
                    )
                    if not matched:
                        continue
                    self.file_keyword_skipped_count += 1
                    self.file_keyword_skip_counts[matched] = (
                        self.file_keyword_skip_counts.get(matched, 0) + 1
                    )
            is_checked = self.checked_urls.get(post_id, False)
            filtered_items.append((post_title, post_id, thumbnail_url, is_checked))
        self.finished.emit(filtered_items)


class FilePreparationThread(_StoppableThread, QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(list, dict)
    log = pyqtSignal(str, str)

    def __init__(
        self,
        post_ids,
        all_files_map,
        creator_ext_checks,
        creator_main_check,
        creator_attachments_check,
        creator_content_check,
        settings,
        max_concurrent=20,
        file_skip_keywords=None,
        skip_images_if_compressed=False,
        allowed_extensions=None,
        file_skip_lenient=False,
        lenient_punctuation=False,
    ):
        super().__init__()
        self.post_ids = post_ids
        self.all_files_map = all_files_map
        self.creator_ext_checks = creator_ext_checks
        # Snapshot the ticked extensions here, on the GUI thread. The workers
        # used to call checkbox.isChecked() themselves, which is a widget read
        # from a foreign thread and picked up any tick made mid-run.
        if allowed_extensions is not None:
            self.allowed_extensions = [str(ext).lower() for ext in allowed_extensions]
        else:
            self.allowed_extensions = [
                str(ext).lower()
                for ext, checkbox in (creator_ext_checks or {}).items()
                if checkbox.isChecked()
            ]
        self.creator_main_check = creator_main_check
        self.creator_attachments_check = creator_attachments_check
        self.creator_content_check = creator_content_check
        self.settings = settings
        self.max_concurrent = max_concurrent
        self.is_running = True
        # Independent, always-on, filename-only skip list.
        # It can be combined freely with whole-post skipping.
        self.file_skip_keywords = (
            file_skip_keywords if file_skip_keywords is not None else []
        )
        # Substring matching for the file list, from the "Keyword Matching
        # Rules" setting (Relaxed (Files)/(Both)). Snapshot on the GUI thread
        # like the keywords.
        self.file_skip_lenient = bool(file_skip_lenient)
        # "Punctuation Matching Rules: Relaxed" — snapshotted from Settings.
        self.lenient_punctuation = bool(lenient_punctuation)
        # Optional download option: when a post also offers a compressed
        # archive, its image files are dropped instead of downloaded.
        self.skip_images_if_compressed = skip_images_if_compressed
        self._images_skipped_count = 0
        self._files_skipped_count = 0
        # keyword -> number of files it dropped, for the skip tooltip.
        self._file_skip_counts = {}
        self._files_skipped_lock = threading.Lock()

    def _drop_images_when_archive_present(self, files_to_download):
        """Return *files_to_download* without its image files when the post
        also offers a compressed archive.

        The archive has to be one of the files actually being downloaded, so
        a post whose ZIP was not selected never loses its images. When no
        archive is present the list is returned untouched.
        """
        if not self.skip_images_if_compressed:
            return files_to_download

        def ext_of(name, url):
            return file_extension(name) or file_extension(urlparse(url).path)

        extensions = {ext_of(name, url) for name, url in files_to_download}
        if not any(ext in COMPRESSED_EXTENSIONS for ext in extensions):
            return files_to_download

        kept = []
        skipped = []
        for name, url in files_to_download:
            if ext_of(name, url) in IMAGE_EXTENSIONS:
                skipped.append(name)
            else:
                kept.append((name, url))
        if skipped:
            with self._files_skipped_lock:
                self._images_skipped_count += len(skipped)
            self.log.emit(
                translate(
                    "log_debug",
                    translate("images_skipped_archive_present", len(skipped)),
                ),
                "DEBUG",
            )
        return kept

    def _file_matches_skip_keyword(self, file_name):
        """Return the file-keyword that excludes *file_name*, or "" for none.

        Only file_skip_keywords are checked here -- these are always
        matched against the filename, regardless of any other setting. The
        extension is left out of the match (a file's type is the filetype
        filter's business), and ``file_skip_lenient`` switches the match to
        a plain substring hit. Whole-post skip keywords are handled upstream
        in PostDetectionThread.
        """
        return _first_matching_keyword(
            self.file_skip_keywords,
            filename_without_extension(file_name),
            self.file_skip_lenient,
            self.lenient_punctuation,
        )

    def _record_file_skip(self, file_name):
        """Count a file dropped by the file-keyword filter.

        Returns the matched keyword ("" when the file is kept) so callers can
        log it and the summary can show a per-keyword breakdown.
        """
        matched = self._file_matches_skip_keyword(file_name)
        if not matched:
            return ""
        with self._files_skipped_lock:
            self._files_skipped_count += 1
            self._file_skip_counts[matched] = self._file_skip_counts.get(matched, 0) + 1
        return matched

    def detect_files(self, post, allowed_extensions, domain_config):
        files_to_download = []
        self.log.emit(
            translate(
                "log_debug", translate("detecting_files_for_post", allowed_extensions)
            ),
            "DEBUG",
        )

        def get_effective_extension(file_path, file_name):
            # The name wins over the path, and both are normalised: the
            # filter, the tally and the grid have to agree on a type.
            name_ext = detect_extension(file_name)
            return name_ext if name_ext else detect_extension(file_path)

        # Main file detection
        main_file = post.get("file")
        if (
            self.creator_main_check
            and isinstance(main_file, dict)
            and main_file.get("path")
        ):
            file_path = main_file["path"]
            file_name = main_file.get("name", "")
            file_ext = get_effective_extension(file_path, file_name)
            file_url = clean_file_url(file_path, domain_config)
            if "f=" not in file_url and file_name:
                file_url += "?f=" + filename_query_value(file_name)
            self.log.emit(
                translate(
                    "log_debug", translate("checking_main_file", file_name, file_ext)
                ),
                "DEBUG",
            )
            if self._record_file_skip(file_name):
                self.log.emit(
                    translate(
                        "log_debug", translate("skipped_individual_file", file_name)
                    ),
                    "DEBUG",
                )
            elif ".jpg" in allowed_extensions and file_ext in [".jpg", ".jpeg"]:
                self.log.emit(
                    translate("log_debug", translate("added_main_file", file_name)),
                    "DEBUG",
                )
                files_to_download.append((file_name, file_url))
            elif file_ext in allowed_extensions:
                self.log.emit(
                    translate("log_debug", translate("added_main_file", file_name)),
                    "DEBUG",
                )
                files_to_download.append((file_name, file_url))

        # Attachments detection
        attachments = post.get("attachments")
        if self.creator_attachments_check and isinstance(attachments, list):
            for attachment in attachments:
                if isinstance(attachment, dict) and "path" in attachment:
                    attachment_path = attachment["path"]
                    attachment_name = attachment.get("name", "")
                    attachment_ext = get_effective_extension(
                        attachment_path, attachment_name
                    )
                    attachment_url = clean_file_url(attachment_path, domain_config)
                    if "f=" not in attachment_url and attachment_name:
                        attachment_url += "?f=" + filename_query_value(attachment_name)
                    self.log.emit(
                        translate(
                            "log_debug",
                            translate(
                                "checking_attachment", attachment_name, attachment_ext
                            ),
                        ),
                        "DEBUG",
                    )
                    if self._record_file_skip(attachment_name):
                        self.log.emit(
                            translate(
                                "log_debug",
                                translate("skipped_individual_file", attachment_name),
                            ),
                            "DEBUG",
                        )
                    elif ".jpg" in allowed_extensions and attachment_ext in [
                        ".jpg",
                        ".jpeg",
                    ]:
                        self.log.emit(
                            translate(
                                "log_debug",
                                translate("added_attachment", attachment_name),
                            ),
                            "DEBUG",
                        )
                        files_to_download.append((attachment_name, attachment_url))
                    elif attachment_ext in allowed_extensions:
                        self.log.emit(
                            translate(
                                "log_debug",
                                translate("added_attachment", attachment_name),
                            ),
                            "DEBUG",
                        )
                        files_to_download.append((attachment_name, attachment_url))

        # Content images detection
        if self.creator_content_check and "content" in post and post["content"]:
            soup = BeautifulSoup(post["content"], "html.parser")
            for img in soup.select("img[src]"):
                img_url = clean_file_url(str(img.get("src")), domain_config)
                # Extension and name come from the path only: a query string
                # ("?f=x.jpg") used to become part of the extension, so the
                # image never matched a ticked type and was dropped, and the
                # query leaked into the name.
                img_ext = detect_extension(img_url)
                img_name = os.path.basename(urlparse(img_url).path) or os.path.basename(
                    img_url.split("?")[0]
                )
                self.log.emit(
                    translate(
                        "log_debug",
                        translate("checking_content_image", img_name, img_ext),
                    ),
                    "DEBUG",
                )
                if self._record_file_skip(img_name):
                    self.log.emit(
                        translate(
                            "log_debug",
                            translate("skipped_individual_file", img_name),
                        ),
                        "DEBUG",
                    )
                elif ".jpg" in allowed_extensions and img_ext in [".jpg", ".jpeg"]:
                    self.log.emit(
                        translate(
                            "log_debug", translate("added_content_image", img_name)
                        ),
                        "DEBUG",
                    )
                    files_to_download.append((img_name, img_url))
                elif img_ext in allowed_extensions:
                    self.log.emit(
                        translate(
                            "log_debug", translate("added_content_image", img_name)
                        ),
                        "DEBUG",
                    )
                    files_to_download.append((img_name, img_url))

        self.log.emit(
            translate(
                "log_debug", translate("total_files_detected", len(files_to_download))
            ),
            "DEBUG",
        )
        files_to_download = self._drop_images_when_archive_present(files_to_download)
        return list(dict.fromkeys(files_to_download))

    def fetch_and_detect_files(self, post_id, creator_url):
        creator_url = creator_url.rstrip("/")
        parts = creator_url.split("/")
        if len(parts) >= 3:
            service = parts[-3]
            creator_id = parts[-1]
            # Clean service and creator_id from potential query params
            if "?" in service:
                service = service.split("?")[0]
            if "?" in creator_id:
                creator_id = creator_id.split("?")[0]
        else:
            service = "unknown_service"
            creator_id = "unknown_creator"
        domain_config = get_domain_config(creator_url)
        api_url = (
            f"{domain_config['api_base']}/{service}/user/{creator_id}/post/{post_id}"
        )
        max_retries = self.settings.post_data_max_retries
        retry_delay_seconds = 2
        for attempt in range(1, max_retries + 1):
            try:
                headers = get_headers().copy()
                headers["Referer"] = domain_config["referer"]
                response = get_session(self.settings.settings_tab).get(
                    api_url, headers=headers, timeout=(15, 30)
                )
                if response.status_code != 200:
                    # A 429 is a rate limit and a 5xx is the server having a bad
                    # day; both are worth the retry budget. Other 4xx mean the
                    # request itself is wrong, so retrying cannot help.
                    retryable_status = response.status_code == 429 or (
                        500 <= response.status_code < 600
                    )
                    if retryable_status and attempt < max_retries:
                        if response.status_code == 429:
                            self.log.emit(
                                translate(
                                    "log_warning",
                                    translate(
                                        "rate_limit_hit",
                                        api_url,
                                        attempt,
                                        max_retries,
                                    ),
                                ),
                                "WARNING",
                            )
                        else:
                            self.log.emit(
                                translate(
                                    "log_warning",
                                    translate(
                                        "server_error_retrying",
                                        api_url,
                                        response.status_code,
                                        attempt,
                                        max_retries,
                                    ),
                                ),
                                "WARNING",
                            )
                        delay = countdown_seconds(attempt, retry_delay_seconds)
                        for i in range(delay, 0, -1):
                            if not self.is_running:
                                return None
                            self.log.emit(
                                translate("log_info", translate("trying_again_in", i)),
                                "INFO",
                            )
                            self._interruptible_sleep(1)
                        continue
                    self.log.emit(
                        translate(
                            "log_error",
                            translate(
                                "failed_to_fetch_api", api_url, response.status_code
                            ),
                        ),
                        "ERROR",
                    )
                    return None
                post_data = response.json()
                post = (
                    post_data
                    if isinstance(post_data, dict) and "post" not in post_data
                    else post_data.get("post", {})
                )
                self.log.emit(
                    translate(
                        "log_debug",
                        translate(
                            "post_data_for_id", post_id, json.dumps(post, indent=2)
                        ),
                    ),
                    "DEBUG",
                )
                detected_files = self.detect_files(
                    post, self.allowed_extensions, domain_config
                )
                return (post_id, detected_files)
            except Exception as e:
                if attempt == max_retries:
                    self.log.emit(
                        translate(
                            "log_error",
                            translate(
                                "error_fetching_post_max_attempts",
                                post_id,
                                max_retries,
                                str(e),
                            ),
                        ),
                        "ERROR",
                    )
                    return None
                self.log.emit(
                    translate(
                        "log_warning",
                        translate(
                            "error_fetching_post", post_id, attempt, max_retries, str(e)
                        ),
                    ),
                    "WARNING",
                )
                delay = countdown_seconds(attempt, retry_delay_seconds)
                for i in range(delay, 0, -1):
                    if not self.is_running:
                        return None
                    self.log.emit(
                        translate("log_info", translate("trying_again_in", i)), "INFO"
                    )
                    self._interruptible_sleep(1)

    def _interruptible_sleep(self, seconds):
        """Sleep *seconds*, waking early when the run is stopped.

        A flat ``time.sleep`` here meant Cancel had to wait out every retry
        countdown before the worker noticed, and the preparation phase could
        outlive the wait the tab gave its workers.
        """
        remaining = float(seconds or 0)
        while remaining > 0 and self.is_running:
            step = min(remaining, 0.2)
            time.sleep(step)
            remaining -= step

    def _worker_wait_budget(self):
        """How long to wait for one preparation worker to finish.

        A worker may be sleeping through per-post retry countdowns, so the
        wait scales with the retry budget. The old single 30 s deadline was
        shorter than one slow post's countdowns, and whatever stragglers had
        not queued yet was then dropped with nothing but a warning.
        """
        try:
            retries = int(getattr(self.settings, "post_data_max_retries", 1) or 1)
        except (TypeError, ValueError):
            retries = 1
        # Each retry can spend up to COUNTDOWN_MAX_SECONDS in its countdown.
        return min(600, 30 + retries * 6)

    def run(self):
        if not self.is_running:
            return
        files_to_download = []
        files_to_posts_map = {}
        self.log.emit(
            translate(
                "log_debug",
                translate("allowed_extensions_for_download", self.allowed_extensions),
            ),
            "DEBUG",
        )

        total_posts = len(self.post_ids)
        completed_posts = 0

        # Find the creator URL(s) associated with these post_ids
        creator_urls = set()
        for creator_url, posts in self.all_files_map.items():
            for _, (post_id, _) in posts:
                if post_id in self.post_ids:
                    creator_urls.add(creator_url)
                    break

        if not creator_urls:
            self.log.emit(
                translate("log_error", translate("no_matching_creator_urls")), "ERROR"
            )
            self.finished.emit([], {})
            return

        # Build work list: (post_id, creator_url) pairs
        work_items = []
        for creator_url in creator_urls:
            for post_id in self.post_ids:
                if any(
                    p[1][0] == post_id for p in self.all_files_map.get(creator_url, [])
                ):
                    work_items.append((post_id, creator_url))

        # Use pure Lock + polling instead of Semaphore/Event to avoid
        # Condition.notify() access violations on Python 3.14 + Windows.
        slot_lock = threading.Lock()
        active_slots = [0]
        results_lock = threading.Lock()
        workers = []

        def _worker(pid, curl):
            """Fetch & detect files in a daemon thread."""
            try:
                if not self.is_running:
                    return
                result = self.fetch_and_detect_files(pid, curl)
                if result and self.is_running:
                    pid_result, detected_files = result
                    with results_lock:
                        for file_name, file_url in detected_files:
                            try:
                                self.log.emit(
                                    translate(
                                        "log_debug",
                                        translate("detected_file", file_name, file_url),
                                    ),
                                    "DEBUG",
                                )
                            except RuntimeError:
                                pass
                            files_to_download.append(file_url)
                            files_to_posts_map[file_url] = pid_result
            except Exception as e:
                # fetch_and_detect_files logs its own failures, but anything it
                # raises on the way out used to vanish here: a post's files
                # then simply never appeared, with no line saying why.
                try:
                    self.log.emit(
                        translate(
                            "log_error", translate("unexpected_error_detecting", str(e))
                        ),
                        "ERROR",
                    )
                except RuntimeError:
                    pass
            finally:
                with slot_lock:
                    active_slots[0] -= 1
                    nonlocal completed_posts
                    completed_posts += 1
                progress = min(int((completed_posts / total_posts) * 100), 100)
                try:
                    self.progress.emit(progress)
                except RuntimeError:
                    pass

        for idx, (pid, curl) in enumerate(work_items):
            if not self.is_running:
                break
            # Wait for a concurrency slot using pure Lock polling
            while True:
                with slot_lock:
                    if active_slots[0] < self.max_concurrent:
                        active_slots[0] += 1
                        break
                if not self.is_running:
                    break
                time.sleep(0.05)
            if not self.is_running:
                break
            t = threading.Thread(target=_worker, args=(pid, curl), daemon=True)
            t.start()
            workers.append(t)

        # Wait for all workers so none outlive the QThread C++ object.
        # Thread.join() internally uses Event.wait() which triggers
        # Condition.notify() access violations on Python 3.14 + Windows,
        # so poll is_alive() instead. The wait is per worker and scaled to the
        # retry budget: one global 30 s deadline silently stranded any post
        # still working through its countdowns.
        budget = self._worker_wait_budget()
        for w in workers:
            deadline = time.monotonic() + budget
            while w.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)

        # Whatever those stragglers were about to queue is lost, so say it
        # rather than dropping their files silently: a run of 429 countdowns
        # was enough to hit the deadline and leave files unexplained.
        stragglers = [w for w in workers if w.is_alive()]
        if stragglers and self.is_running:
            self.log.emit(
                translate(
                    "log_warning",
                    translate("file_preparation_deadline_warning", len(stragglers)),
                ),
                "WARNING",
            )

        if self.is_running:
            # Snapshot under the workers' lock: a straggler may still be
            # appending, and iterating the live list would race with it.
            with results_lock:
                queued = list(dict.fromkeys(files_to_download))
                queued_map = dict(files_to_posts_map)
            self.log.emit(
                translate(
                    "log_debug",
                    translate("total_files_to_download", len(queued)),
                ),
                "DEBUG",
            )
            # File-skip summary is emitted by CreatorDownloaderTab in
            # creator_download_finished() so it appears as the LAST line in the log.
            self.finished.emit(queued, queued_map)


def sanitize_filename(name, max_length=100):
    """Sanitize a filename by removing invalid characters, trailing dots, and limiting length."""
    if not name:
        return "unnamed"
    # Strip control characters (0x00-0x1F, DEL) and zero-width/BOM characters:
    # Windows rejects any path containing them, and post titles routinely end
    # with a newline (e.g. "Akeno Belly Progression (3/3) \n"), which used to
    # fail the write with "OSError: [Errno 22] Invalid argument".
    sanitized = re.sub(r"[\x00-\x1f\x7f\u200b-\u200f\ufeff]", "_", name)
    # Remove invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", sanitized)
    # Collapse whitespace (spaces, tabs, NBSP) into single underscores
    sanitized = re.sub(r"\s+", "_", sanitized)
    # Remove multiple consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)
    # Remove trailing dots (Windows compatibility)
    sanitized = sanitized.rstrip(".")
    # Remove leading dots to avoid hidden/unsafe filenames
    sanitized = sanitized.lstrip(".")
    # Trim leading/trailing underscores
    sanitized = sanitized.strip("_")
    # Limit length
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].rstrip(".").strip("_")
    # Ensure non-empty
    return sanitized if sanitized else "unnamed"


class CreatorDownloadThread(_StoppableThread, QThread):
    file_progress = pyqtSignal(int, int)
    file_completed = pyqtSignal(int, str, bool)  # Added success flag
    post_completed = pyqtSignal(str)
    log = pyqtSignal(str, str)
    finished = pyqtSignal()
    # The folder this run writes into, emitted once it is known to exist, so
    # the tab can offer its "open folder" button.
    creator_folder_ready = pyqtSignal(str)

    def __init__(
        self,
        service,
        creator_id,
        download_folder,
        selected_posts,
        files_to_download,
        files_to_posts_map,
        console,  # accepted for compatibility; logging goes through `log`
        other_files_dir,
        post_titles_map,
        settings,
        max_concurrent=20,
        download_text=False,
        skip_folder_enabled=False,
        skip_folder_threshold=1,
        force_folder_for_compressed=False,
        post_dates_map=None,
        post_times_map=None,
        file_numbers=None,
        post_file_counts=None,
    ):
        super().__init__()
        self.service = service
        self.creator_id = creator_id
        self.download_folder = download_folder
        self.selected_posts = selected_posts
        self.files_to_download = files_to_download
        self.files_to_posts_map = files_to_posts_map
        self.settings = settings
        self.is_running = True
        self.download_text = download_text
        self.other_files_dir = other_files_dir
        self.hash_db = HashDB(self.other_files_dir)
        self.history_db = DownloadHistoryDB(self.other_files_dir)
        self.max_concurrent = max_concurrent
        self.post_files_map = self.build_post_files_map()
        self.completed_files = set()
        self.failed_files = {}  # Map file_url to error message
        self.post_titles_map = post_titles_map
        # Publish date per post id ("YYYY-MM-DD") for {post_date} in the
        # filename templates; the download thread only sees file URLs, so the
        # tab hands the dates over rather than the whole post JSON.
        self.post_dates_map = post_dates_map or {}
        # Publish time per post id ("HHMM") for {post_time}, handed over
        # the same way as the dates; the template joins the two.
        self.post_times_map = post_times_map or {}
        # File position inside its post (url -> number) and the post's real
        # file count (post_id -> count). Both are decided once, when the run's
        # file list is built: recomputing them here counted only the files
        # passed in, so a retry renamed page 3 to 1 and shrank its post's
        # count - which also flipped the skip-post-folder decision.
        self.file_numbers = dict(file_numbers or {})
        self.post_file_counts = dict(post_file_counts or {})
        self.creator_name = None
        self.skip_folder_enabled = skip_folder_enabled
        self.skip_folder_threshold = skip_folder_threshold
        self.force_folder_for_compressed = force_folder_for_compressed
        self.domain_config = self._get_domain_config_from_files()
        # Locks for thread-safe access to shared dictionaries
        self.failed_files_lock = threading.Lock()
        # Cache of resolved per-post folder names (post_id -> folder name),
        # so repeated calls for the same post always resolve to the same
        # folder, and so we only need to check disk collisions once per post.
        self._post_folder_names = {}
        self._post_folder_names_lock = threading.Lock()
        # Filenames this run has already claimed, so two files that resolve to
        # the same name cannot both write it (the "append a number" guard).
        self._reserved_paths = set()
        self._reserved_paths_lock = threading.Lock()
        # Post folder names this run has already claimed (creator folder,
        # name), so two posts with the same title cannot share a folder.
        self._reserved_folder_names = set()
        self._reserved_folder_names_lock = threading.Lock()
        # Post ids already stamped after a real download in this run, so a
        # multi-file post writes one row instead of one row per file.
        self._history_lock = threading.Lock()
        self._stamped_posts = set()
        # Creator folder this run writes into, and whether it has been
        # announced to the tab yet (the "open folder" button waits for it).
        self._creator_folder = None
        self._folder_announced = False

        self.completed_files_lock = threading.Lock()
        self.fetched_texts_lock = threading.Lock()
        self.fetched_texts = set()
        # Lock to serialize SSL connection establishment across workers.
        # On Windows + Python 3.14, concurrent SSL handshakes / reads in
        # OpenSSL trigger native access-violation crashes.  Serialising
        # only the session.get() call (which does SSL + redirects) while
        # allowing concurrent body streaming avoids the problem.
        self._ssl_lock = threading.Lock()
        # Defence flag: set in stop() *before* any cleanup.  Workers
        # check this before emitting signals so they never touch the
        # C++ object after it has been scheduled for deletion.
        self._destroyed = False

    def _get_domain_config_from_files(self):
        """Determine domain configuration from the files to download"""
        if self.files_to_download:
            first_url = self.files_to_download[0]
            return get_domain_config(first_url)
        # Default fallback
        return get_domain_config("https://kemono.cr/")

    def build_post_files_map(self):
        post_files_map = {post_id: [] for post_id in self.selected_posts}
        for file_url in self.files_to_download:
            post_id = self.files_to_posts_map.get(file_url)
            if post_id in post_files_map:
                post_files_map[post_id].append(file_url)
        return post_files_map

    def fetch_creator_and_post_info(self):
        """Fetch creator name and retrieve post titles from post_titles_map."""
        profile_url = creator_profile_url(
            self.domain_config, self.service, self.creator_id
        )
        # The creator name becomes a folder name, so a single blip must not
        # rename it: falling back to "Unknown_Creator" split a creator's files
        # across two folders. Retry before accepting the fallback, using the
        # "API Request Max Retries" setting (this was the knob's only user
        # left unwired - the count was hard-coded to 3).
        attempts = getattr(self.settings, "api_request_max_retries", 3)
        if not isinstance(attempts, int) or attempts < 1:
            # Stub settings (mocks) and junk fall back to the old default.
            attempts = 3
        profile_attempts = attempts
        for attempt in range(1, profile_attempts + 1):
            try:
                headers = get_headers().copy()
                headers["Referer"] = self.domain_config["referer"]
                profile_response = get_session(self.settings.settings_tab).get(
                    profile_url, headers=headers, timeout=10
                )
                if profile_response.status_code == 200:
                    profile_data = profile_response.json()
                    self.creator_name = sanitize_filename(
                        profile_data.get("name", "Unknown_Creator")
                    )
                    break
                # A 404/401 will never succeed: stop retrying it.
                terminal = is_terminal_status(profile_response.status_code)
                if attempt < profile_attempts and not terminal:
                    self._safe_emit(
                        self.log,
                        translate(
                            "log_debug",
                            translate(
                                "retrying_creator_name_fetch",
                                f"HTTP {profile_response.status_code}",
                            ),
                        ),
                        "DEBUG",
                    )
                    time.sleep(api_retry_delay(attempt, profile_response))
                    continue
                self.creator_name = "Unknown_Creator"
                self._safe_emit(
                    self.log,
                    translate(
                        "log_warning",
                        translate("failed_to_fetch_creator_name", self.creator_name),
                    ),
                    "WARNING",
                )
                break
            except requests.RequestException as e:
                if attempt < profile_attempts:
                    self._safe_emit(
                        self.log,
                        translate(
                            "log_debug",
                            translate("retrying_creator_name_fetch", str(e)),
                        ),
                        "DEBUG",
                    )
                    time.sleep(api_retry_delay(attempt))
                    continue
                self._safe_emit(
                    self.log,
                    translate(
                        "log_error",
                        translate("error_fetching_creator_name", str(e)),
                    ),
                    "ERROR",
                )
                self.creator_name = "Unknown_Creator"
                break

        for post_id in self.selected_posts:
            key = (self.service, self.creator_id, post_id)
            if key not in self.post_titles_map:
                post_url = f"{self.domain_config['api_base']}/{self.service}/user/{self.creator_id}/post/{post_id}"
                try:
                    headers = get_headers().copy()
                    headers["Referer"] = self.domain_config["referer"]
                    response = get_session(self.settings.settings_tab).get(
                        post_url, headers=headers, timeout=10
                    )
                    if response.status_code == 200:
                        post_data = response.json()
                        title = post_data.get("title", f"Post_{post_id}")
                        self.post_titles_map[key] = sanitize_filename(title)
                        self._safe_emit(
                            self.log,
                            translate(
                                "log_info",
                                translate("fetched_title_for_post", post_id, title),
                            ),
                            "INFO",
                        )
                    else:
                        self.post_titles_map[key] = sanitize_filename(f"Post_{post_id}")
                        self._safe_emit(
                            self.log,
                            translate(
                                "log_warning",
                                translate("failed_to_fetch_title_for_post", post_id),
                            ),
                            "WARNING",
                        )
                except requests.RequestException as e:
                    self.post_titles_map[key] = sanitize_filename(f"Post_{post_id}")
                    self._safe_emit(
                        self.log,
                        translate(
                            "log_error",
                            translate("error_fetching_title_for_post", post_id, str(e)),
                        ),
                        "ERROR",
                    )

    def stop(self):
        super().stop()
        self._destroyed = True

    def _safe_emit(self, signal, *args):
        """Emit *signal* only when the C++ object is still alive."""
        if self._destroyed:
            return
        try:
            signal.emit(*args)
        except RuntimeError:
            pass

    def _post_folder_is_known(self, post_id, folder_path):
        """True when one of this post's files is recorded in *folder_path*.

        A folder template without ``{post_id}`` renders the same name on
        every run, so the second run of a post finds its own folder on
        disk. Without this check it took its own folder for someone
        else's and downloaded into "Title_1", then "Title_2", scattering
        the post across folders. The hash database remembers where each
        file went, so the post can be asked directly.
        """
        wanted = os.path.normcase(os.path.normpath(folder_path))
        for file_url in self.post_files_map.get(post_id, []):
            try:
                entry = self.hash_db.lookup(hashlib.md5(file_url.encode()).hexdigest())
            except Exception:
                return False
            recorded = (entry or {}).get("file_path")
            if not recorded:
                continue
            recorded_folder = os.path.normcase(
                os.path.normpath(os.path.dirname(recorded))
            )
            if recorded_folder == wanted:
                return True
        return False

    def get_post_folder_name(self, post_id, post_title, creator_folder):
        """Render the per-post folder name using the configurable
        ``creator_folder_name_template`` setting (default
        "{post_id}_{post_title}").

        If the template contains ``{post_id}``, the rendered name is
        guaranteed unique and no disk-collision check is performed.

        For templates without ``{post_id}``, a disk-existence check
        appends ``_1``, ``_2``, ... until a free name is found, except for
        the folder this post already writes to, which it keeps. The result
        is cached per post_id so repeated calls (once per file in the
        post) always resolve to the same folder.
        """
        with self._post_folder_names_lock:
            if post_id in self._post_folder_names:
                return self._post_folder_names[post_id]

            template = None
            try:
                if self.settings and getattr(self.settings, "settings_tab", None):
                    template = (
                        self.settings.settings_tab.get_creator_folder_name_template()
                    )
            except Exception:
                template = None

            if not template:
                template = "{post_id}_{post_title}"

            context = {
                "post_id": post_id,
                "post_title": sanitize_filename(post_title),
                "creator_id": self.creator_id,
                "creator_name": sanitize_filename(
                    self.creator_name or "Unknown_Creator"
                ),
            }

            try:
                rendered = template.format(**context)
            except Exception:
                try:
                    self._safe_emit(
                        self.log,
                        translate(
                            "log_warning",
                            translate("folder_name_template_error", template),
                        ),
                        "WARNING",
                    )
                except Exception:
                    pass
                rendered = f"{context['post_id']}_{context['post_title']}"

            base_name = sanitize_filename(rendered)

            # Short-circuit: if the template includes {post_id}, the
            # rendered folder name is guaranteed unique within the creator.
            if "{post_id}" in template:
                candidate = base_name
            elif not self._folder_dedup_enabled():
                # Folder names are not deduped: two posts with the same title
                # share their folder, which is what the setting asks for.
                candidate = base_name
            else:
                candidate = self._claim_post_folder(post_id, base_name, creator_folder)

            self._post_folder_names[post_id] = candidate
            return candidate

    def _claim_post_folder(self, post_id, base_name, creator_folder):
        """A folder name for this post that no other post of the run uses.

        The disk check alone could not see a folder another post of the *same
        run* had claimed but not created yet, so two posts with the same title
        merged their files. The reserved set closes that window; the post's
        own folder from an earlier run is still kept, so a re-download does
        not scatter a post across ``Title`` and ``Title_1``.
        """
        candidate = base_name
        counter = 1
        while True:
            path = os.path.join(creator_folder, candidate)
            key = (
                os.path.normcase(os.path.normpath(creator_folder)),
                os.path.normcase(candidate),
            )
            with self._reserved_folder_names_lock:
                claimed = key in self._reserved_folder_names
                if not claimed and not os.path.exists(path):
                    self._reserved_folder_names.add(key)
                    return candidate
            if not claimed and self._post_folder_is_known(post_id, path):
                # This post's own folder from an earlier run: keep it.
                with self._reserved_folder_names_lock:
                    self._reserved_folder_names.add(key)
                return candidate
            candidate = f"{base_name}_{counter}"
            counter += 1

    def generate_filename_and_folder(
        self,
        file_url,
        folder,
        file_index,
        total_files,
        post_id,
        post_title,
        page_number,
    ):
        """Generate the target folder path and filename for a given file according to
        the creator downloader settings (folder strategy, and the filename
        template for the folder the file lands in).

        Returns (target_folder, filename)
        """
        # Determine raw filename from URL. The "f=" value is percent-decoded
        # and stops at "&": it used to be everything after the last "f=", which
        # truncated names that themselves contain "f=" and left "%20" in the
        # name instead of a space.
        raw_filename = (
            filename_from_query(file_url) or file_url.split("/")[-1].split("?")[0]
        )
        # The extension is appended to the already-sanitized name, so scrub it
        # on its own: a URL can carry anything after "?f=", including the
        # control characters Windows rejects in a path.
        file_ext = re.sub(r"[^0-9A-Za-z.]", "", os.path.splitext(raw_filename)[1])
        original_name = os.path.splitext(raw_filename)[0]

        # Prepare context for template formatting
        key = (self.service, self.creator_id, post_id)
        post_title_safe = sanitize_filename(
            self.post_titles_map.get(key, f"Post_{post_id}")
        )
        context = {
            "post_id": post_id,
            "post_title": post_title_safe,
            "orig_name": sanitize_filename(original_name),
            "ext": file_ext.lstrip("."),
            "creator_name": sanitize_filename(self.creator_name or "Unknown_Creator"),
            "creator_id": self.creator_id,
            "file_index": file_index + 1,
            "file_number": page_number,
            "total_files": total_files,
            "post_file_count": _thread_post_file_count(self, post_id),
            "post_date": getattr(self, "post_dates_map", {}).get(str(post_id), ""),
            "post_time": getattr(self, "post_times_map", {}).get(str(post_id), ""),
            "service": self.service,
        }

        # Get settings. Two templates: files inside a post's own folder use the
        # post-folder template, files pooled in a folder shared with other posts
        # use the shared one. Both are ordinary user templates - nothing is
        # prepended behind the user's back.
        template = None
        shared_template = None
        strategy = "per_post"
        try:
            if self.settings and getattr(self.settings, "settings_tab", None):
                st = self.settings.settings_tab
                template = st.get_creator_filename_template()
                # Older/mocked settings tabs have no shared getter; anything
                # that is not a string (a bare MagicMock, say) is ignored so
                # the numbered defaults still apply.
                get_shared = getattr(st, "get_creator_filename_template_shared", None)
                if callable(get_shared):
                    shared_template = get_shared()
                strategy = st.get_creator_folder_strategy()
        except Exception:
            # Fallback to defaults
            template = None
            shared_template = None
            strategy = "per_post"

        if not isinstance(template, str) or not template:
            template = None
        if not isinstance(shared_template, str) or not shared_template:
            shared_template = None

        # Determine the target folder first: which template names this file
        # depends on whether it lands in a folder of its own or in one shared
        # with other posts.
        # Creator folder name
        creator_folder_name = (
            f"{self.creator_id}_{self.creator_name or self.creator_id}"
        )
        # Determine creator_folder: if `folder` already ends with the creator folder
        # (e.g., passed as the creator_folder in the thread), don't append it again.
        norm_folder = os.path.normpath(folder)
        if os.path.basename(norm_folder) == creator_folder_name:
            creator_folder = norm_folder
        else:
            creator_folder = os.path.join(folder, creator_folder_name)
        # Remember it so the tab can offer to open it (see
        # _announce_creator_folder).
        self._creator_folder = creator_folder

        # ``post_folder_name`` stays None whenever the file lands in a folder
        # that can also hold files of other posts: single_folder,
        # by_file_type, or a per-post download whose post folder was skipped.
        post_folder_name = None
        if strategy == "single_folder":
            target_folder = creator_folder
        elif strategy == "by_file_type":
            ext_folder = (file_ext.lstrip(".") or "other").lower()
            target_folder = os.path.join(creator_folder, ext_folder)
        else:  # per_post (default)
            # Check if skip-folder toggle is on and this post has few enough files
            post_file_count = _thread_post_file_count(self, post_id)
            is_compressed_file = file_ext.lower() in COMPRESSED_EXTENSIONS
            skip_folder_applies = (
                self.skip_folder_enabled
                and post_file_count <= self.skip_folder_threshold
                and not (self.force_folder_for_compressed and is_compressed_file)
            )
            if skip_folder_applies:
                target_folder = creator_folder
            else:
                post_folder_name = self.get_post_folder_name(
                    post_id, post_title_safe, creator_folder
                )
                target_folder = os.path.join(creator_folder, post_folder_name)

        # Pick the template for the folder this file lands in. A post folder
        # keeps its post's files together on its own; a shared folder has to be
        # told how to tell one post's files from another, which is what
        # {post_id} (or {post_date}) in the shared template is for. {file_number}
        # is the file's position inside its post, computed once at enqueue time
        # (detection order), so pages stay in reading order even when the
        # downloads run concurrently.
        if post_folder_name is not None:
            chosen = template or "{file_number}_{post_id}_{orig_name}"
        else:
            chosen = shared_template or "{post_id}_{file_number}_{orig_name}"

        try:
            formatted = chosen.format(**context)
        except Exception:
            # Log a warning and fallback to a safe default template
            try:
                self._safe_emit(
                    self.log,
                    translate(
                        "log_warning", translate("filename_template_error", chosen)
                    ),
                    "WARNING",
                )
            except Exception:
                pass
            formatted = f"{context['post_id']}_{context['orig_name']}"

        # Build final filename and sanitize
        filename_no_ext = sanitize_filename(formatted)
        final_filename = f"{filename_no_ext}{file_ext}"

        return target_folder, final_filename

    def get_desc_folder_for_post(self, creator_folder, post_id, post_title):
        """Return the folder where description files should be saved based on folder strategy."""
        strategy = "per_post"
        try:
            if self.settings and getattr(self.settings, "settings_tab", None):
                strategy = self.settings.settings_tab.get_creator_folder_strategy()
        except Exception:
            strategy = "per_post"

        # Normalize creator_folder path
        creator_folder = os.path.normpath(creator_folder)

        if strategy == "by_file_type":
            return os.path.join(creator_folder, "txt")
        elif strategy == "single_folder":
            return creator_folder
        else:  # per_post
            # Respect skip-folder toggle for description files too, and mirror
            # the file rule exactly: an archive forces the post folder, so the
            # description belongs there rather than in the creator root.
            post_files = self.post_files_map.get(post_id, [])
            post_file_count = _thread_post_file_count(self, post_id)
            post_has_archive = any(
                file_extension(urlparse(url).path) in COMPRESSED_EXTENSIONS
                for url in post_files
            )
            skip_folder_applies = (
                self.skip_folder_enabled
                and post_file_count <= self.skip_folder_threshold
                and not (self.force_folder_for_compressed and post_has_archive)
            )
            if skip_folder_applies:
                return creator_folder
            return os.path.join(
                creator_folder,
                self.get_post_folder_name(post_id, post_title, creator_folder),
            )

    async def download_post_text_if_needed(self, post_id, post_folder):
        should_download = False
        with self.fetched_texts_lock:
            if post_id not in self.fetched_texts:
                self.fetched_texts.add(post_id)
                should_download = True

        if should_download:
            await asyncio.to_thread(self._download_text_sync, post_id, post_folder)

    def _download_text_sync(self, post_id, post_folder):
        try:
            # Always write a per-post description file to avoid collisions when using
            # shared folders (like single_creator or file-type subfolders).
            desc_filename = f"desc_{post_id}.txt"
            desc_path = os.path.join(post_folder, desc_filename)
            if os.path.exists(desc_path):
                return

            api_url = f"{self.domain_config['api_base']}/{self.service}/user/{self.creator_id}/post/{post_id}"
            headers = get_headers().copy()
            headers["Referer"] = self.domain_config["referer"]
            response = get_session(self.settings.settings_tab).get(
                api_url, headers=headers, timeout=10
            )
            if response.status_code == 200:
                post_data = response.json()
                post = (
                    post_data
                    if isinstance(post_data, dict) and "post" not in post_data
                    else post_data.get("post", {})
                )
                content = post.get("content", "")
                if content:
                    soup = BeautifulSoup(content, "html.parser")
                    text = soup.get_text(separator="\n\n")
                    try:
                        os.makedirs(post_folder, exist_ok=True)
                    except OSError:
                        pass
                    with open(desc_path, "w", encoding="utf-8") as f:
                        f.write(text)
                    self._safe_emit(
                        self.log,
                        translate(
                            "log_info", translate("saved_post_description", post_id)
                        ),
                        "INFO",
                    )
        except Exception as e:
            self._safe_emit(
                self.log,
                translate(
                    "log_warning",
                    translate("failed_save_post_description", post_id, str(e)),
                ),
                "WARNING",
            )

    def _announce_creator_folder(self):
        """Tell the tab which folder this run writes into, once.

        Called from the first file that lands (or the first hash-db hit, which
        implies the folder is already there), so the tab's "open folder"
        button only lights up once the path exists.
        """
        if self._folder_announced or not self._creator_folder:
            return
        self._folder_announced = True
        self._safe_emit(self.creator_folder_ready, self._creator_folder)

    def _unique_path(self, full_path, entry):
        """Return the path this file should be written to.

        The templates are what normally keep names apart - ``{file_number}``
        inside a post, ``{post_id}``/``{post_date}`` in a shared folder - and
        when they do, this changes nothing. When a template drops those
        placeholders, two files can resolve to one name and the write would
        silently replace the first one. With the guard on, the second file
        takes ``name_1.ext``, then ``name_2.ext``, and so on.

        The file this URL was downloaded to before is exempt: repairing a
        damaged or truncated file must overwrite it in place rather than leave
        a near-duplicate beside it.
        """
        if not self._unique_filenames_enabled():
            return full_path
        if entry:
            recorded = entry.get("file_path")
            if recorded and os.path.normcase(recorded) == os.path.normcase(full_path):
                return full_path

        directory, name = os.path.split(full_path)
        stem, extension = os.path.splitext(name)
        try:
            with self._reserved_paths_lock:
                candidate = full_path
                counter = 1
                while os.path.exists(candidate) or candidate in self._reserved_paths:
                    candidate = os.path.join(directory, f"{stem}_{counter}{extension}")
                    counter += 1
                self._reserved_paths.add(candidate)
            return candidate
        except Exception:
            # The guard is best-effort: a filesystem check must never be the
            # reason a download fails, so fall back to the templated name.
            return full_path

    def _name_dedup(self, getter_name):
        """Ask the settings tab one "Name Dedup" question.

        Settings tabs built before the option existed (and mocked ones) have
        no getter; they keep the old unconditional behaviour (on).
        """
        tab = getattr(self.settings, "settings_tab", None)
        getter = getattr(tab, getter_name, None)
        if getter is None:
            return True
        try:
            return bool(getter())
        except Exception:
            return True

    def _unique_filenames_enabled(self):
        """Whether the "append a number when the name is taken" guard is on."""
        return self._name_dedup("get_creator_unique_filenames")

    def _folder_dedup_enabled(self):
        """Whether a post folder name is checked for collisions."""
        return self._name_dedup("get_creator_folder_dedup")

    def _discard_part_file(self, part_path):
        """Delete a partial transfer, logging what happened.

        Only the ".part" file is ever touched: the real name is created by a
        rename that happens after the size check, so anything half-written
        lives here and nowhere else.
        """
        try:
            if not os.path.exists(part_path):
                return
            os.remove(part_path)
            self._safe_emit(
                self.log,
                translate("log_info", translate("deleted_incomplete_file", part_path)),
                "INFO",
            )
        except OSError as e:
            self._safe_emit(
                self.log,
                translate(
                    "log_error",
                    translate("failed_to_delete_incomplete_file", part_path, str(e)),
                ),
                "ERROR",
            )
        except Exception:
            # Best-effort cleanup; never mask the original failure.
            pass

    async def download_file(
        self, file_url, folder, file_index, total_files, page_number
    ):
        if not self.is_running or file_url not in _thread_run_files(self):
            self._safe_emit(
                self.log, translate("log_info", f"Skipping {file_url}"), "INFO"
            )
            return

        post_id = self.files_to_posts_map.get(file_url, self.creator_id)
        key = (self.service, self.creator_id, post_id)
        post_title = self.post_titles_map.get(key, f"Post_{post_id}")

        # Generate the final target folder and filename from the templates
        target_folder, filename = self.generate_filename_and_folder(
            file_url, folder, file_index, total_files, post_id, post_title, page_number
        )

        full_path = os.path.join(target_folder, filename)
        url_hash = hashlib.md5(file_url.encode()).hexdigest()

        entry = self.hash_db.lookup(url_hash)
        if entry:
            existing_path = entry["file_path"]
            if os.path.exists(existing_path):
                # Check file size first for fast corruption detection
                actual_size = os.path.getsize(existing_path)
                expected_size = entry.get("file_size", 0)
                if expected_size > 0 and actual_size != expected_size:
                    self._safe_emit(
                        self.log,
                        translate(
                            "log_warning",
                            translate(
                                "size_mismatch_error",
                                actual_size,
                                expected_size,
                                file_url,
                            ),
                        ),
                        "WARNING",
                    )
                    self._safe_emit(
                        self.log,
                        translate(
                            "log_info",
                            f"File size mismatch for {existing_path}, re-downloading",
                        ),
                        "INFO",
                    )
                else:
                    # Hashing re-reads the whole file, so hand it to a worker
                    # thread: on the loop it stalled every other download.
                    file_hash = await asyncio.to_thread(_hash_file, existing_path)
                    if file_hash == entry["file_hash"]:
                        self._safe_emit(
                            self.log,
                            translate(
                                "log_info",
                                translate(
                                    "file_already_downloaded",
                                    filename,
                                    existing_path,
                                ),
                            ),
                            "INFO",
                        )
                        self._safe_emit(self.file_progress, file_index, 100)
                        self._safe_emit(self.file_completed, file_index, file_url, True)
                        with self.completed_files_lock:
                            self.completed_files.add(file_url)
                        # A hash hit means the file (and so the folder) is
                        # already on disk.
                        self._announce_creator_folder()
                        self.check_post_completion(file_url)
                        return

        # Optional guard: a template without {file_number}/{post_id} can name
        # two files alike, and the write below would silently replace the first
        # one. The guard takes the next free name instead (and never renames a
        # file being repaired in place).
        full_path = self._unique_path(full_path, entry)
        # Transfers land here first and are renamed on success, so a cancelled
        # or failed download can never leave a truncated file at the real name
        # for the next run's dedup lookup to trust.
        part_path = full_path + ".part"

        self._safe_emit(
            self.log,
            translate(
                "log_info",
                translate(
                    "starting_download",
                    file_index + 1,
                    total_files,
                    file_url,
                    target_folder,
                ),
            ),
            "INFO",
        )

        # Create the target folder now that we've confirmed the file
        # isn't already downloaded (hash-db dedup). This prevents empty
        # _1/_2 folders from being created when re-downloading a post
        # whose files are all dedup hits.
        try:
            os.makedirs(target_folder, exist_ok=True)
        except OSError as e:
            error_msg = translate("failed_to_create_post_folder", target_folder, str(e))
            self._safe_emit(self.log, translate("log_error", error_msg), "ERROR")
            with self.failed_files_lock:
                self.failed_files[file_url] = error_msg
            self._safe_emit(self.file_progress, file_index, 0)
            self._safe_emit(self.file_completed, file_index, file_url, False)
            self.check_post_completion(file_url)
            return

        # The folder exists now, so the tab can offer to open it.
        self._announce_creator_folder()

        # Download text if enabled (only once per post).
        # This is placed AFTER the hash-db dedup check so that re-downloading
        # a post whose files are all dedup hits does NOT create an empty
        # _1 folder (the desc download would resolve a different folder name
        # since _post_folder_names cache is per-thread, not per-session).
        if self.download_text:
            # Determine destination for description files depending on folder strategy
            # (e.g., 'txt' subfolder when using file-type subfolders)
            desc_folder = self.get_desc_folder_for_post(folder, post_id, post_title)
            await self.download_post_text_if_needed(post_id, desc_folder)

        max_retries = self.settings.file_download_max_retries
        for attempt in range(1, max_retries + 1):
            try:
                headers = get_headers().copy()
                # Use the file host's own origin as Referer/Origin instead of
                # the base-domain referer. For hosts like pawchive, files are
                # served from a different subdomain (file.pawchive.<suffix>)
                # than the site itself (pawchive.<suffix>). DDoS-Guard (and
                # similar WAFs) treat a Referer that doesn't match the
                # requested host as a bot/hotlink signal and 403 immediately
                # (no CF-RAY, since it's DDoS-Guard, not Cloudflare).
                file_base_url = (
                    self.domain_config.get("file_base_url")
                    or self.domain_config["base_url"]
                )
                headers["Referer"] = file_base_url.rstrip("/") + "/"
                headers["Origin"] = self.domain_config["base_url"].rstrip("/")
                # get_headers() returns the module-wide default header set,
                # which hardcodes Accept: text/css (meant for a stylesheet
                # probe, not a file download). Sending that Accept header
                # while requesting a media/binary URL is a strong bot
                # signal to WAFs like DDoS-Guard. Override it, and add the
                # Sec-Fetch-* hints a real browser would send for a
                # cross-site subresource request (file.<domain> is a
                # different origin than the referring page's domain).
                headers["Accept"] = "*/*"
                # Streamed files are size-checked against content-length, which
                # counts encoded bytes, so asking for compression would make
                # the check fail on any server that honours it ("br" also needs
                # a brotli module that this app does not depend on).
                headers["Accept-Encoding"] = "identity"
                headers["Sec-Fetch-Dest"] = "empty"
                headers["Sec-Fetch-Mode"] = "cors"
                headers["Sec-Fetch-Site"] = "same-site"

                # Use requests instead of aiohttp for better proxy support
                def download_with_requests():
                    session = get_session(self.settings.settings_tab)
                    # Serialize SSL connection establishment to prevent
                    # concurrent SSL access violations on Windows.
                    with self._ssl_lock:
                        if not self.is_running:
                            raise _Cancelled("Download cancelled before connection")

                        # Warm up the file host once per thread/session so
                        # DDoS-Guard issues its clearance cookie for that
                        # specific host before we request the actual file.
                        # Without this, the very first file request on a
                        # fresh session/thread can 403 even with a correct
                        # Referer, because no cookie has been set for
                        # file.<domain> yet.
                        warmed_hosts = getattr(
                            _thread_local, "ddos_guard_warmed_hosts", None
                        )
                        if warmed_hosts is None:
                            warmed_hosts = set()
                            _thread_local.ddos_guard_warmed_hosts = warmed_hosts
                        if file_base_url not in warmed_hosts:
                            try:
                                session.get(
                                    file_base_url.rstrip("/") + "/",
                                    headers={
                                        "User-Agent": headers["User-Agent"],
                                        "Referer": self.domain_config["referer"],
                                    },
                                    timeout=(10, 10),
                                )
                            except Exception:
                                # Warm-up is best-effort; proceed regardless.
                                pass
                            warmed_hosts.add(file_base_url)

                        response = session.get(
                            file_url,
                            headers=headers,
                            stream=True,
                            timeout=(30, 30),
                        )
                    # After headers are received each thread has its own
                    # SSL connection and can stream data concurrently.
                    try:
                        if response.status_code == 403:
                            self._safe_emit(
                                self.log,
                                f"[DEBUG 403] Server: {response.headers.get('Server')} | "
                                f"CF-RAY: {response.headers.get('cf-ray')} | "
                                f"Body: {response.text[:300]}",
                                "DEBUG",
                            )
                        response.raise_for_status()
                        header = response.headers.get("content-length")
                        try:
                            file_size = int(header) if header is not None else 0
                        except Exception:
                            file_size = 0
                        downloaded_size = 0
                        hasher = hashlib.md5()

                        file_handle = open(part_path, "wb")
                        try:
                            for chunk in response.iter_content(chunk_size=8192):
                                if not self.is_running:
                                    raise _Cancelled("Download interrupted by user")
                                if chunk:
                                    file_handle.write(chunk)
                                    hasher.update(chunk)
                                    downloaded_size += len(chunk)
                                    if file_size > 0:
                                        progress = int(
                                            (downloaded_size / file_size) * 100
                                        )
                                    else:
                                        progress = 0
                                    self._safe_emit(
                                        self.file_progress,
                                        file_index,
                                        min(progress, 100),
                                    )
                        finally:
                            file_handle.close()

                        return file_size, downloaded_size, hasher.hexdigest()
                    finally:
                        response.close()

                # Run the download in a thread to avoid blocking
                file_size, downloaded_size, file_hash = await asyncio.to_thread(
                    download_with_requests
                )

                # Validate downloaded size matches content-length
                if file_size > 0 and downloaded_size != file_size:
                    error_msg = translate(
                        "size_mismatch_error", downloaded_size, file_size, file_url
                    )
                    self._safe_emit(
                        self.log, translate("log_warning", error_msg), "WARNING"
                    )
                    # Delete the partial transfer so nothing truncated is left
                    self._discard_part_file(part_path)
                    # Raise a retryable exception so this is caught by the
                    # RequestException/_RetryableDownloadError branch below
                    # and actually retried, instead of falling into the
                    # generic `except Exception` handler further down (which
                    # gives up immediately with no retry at all).
                    raise _RetryableDownloadError(
                        f"Size mismatch: downloaded {downloaded_size} bytes, expected {file_size} bytes"
                    )

                # Only a complete transfer is promoted to its final name. The
                # hash comes from the same pass that wrote the bytes, so the
                # file is never re-read just to hash it.
                os.replace(part_path, full_path)
                self.hash_db.store(
                    url_hash, full_path, file_hash, file_url, downloaded_size
                )
                # The file is on disk now, so this post was last downloaded
                # today.
                self._record_post_download(post_id)
                self._safe_emit(
                    self.log,
                    translate(
                        "log_info", translate("successfully_downloaded", full_path)
                    ),
                    "INFO",
                )
                with self.completed_files_lock:
                    self.completed_files.add(file_url)
                self._safe_emit(self.file_completed, file_index, file_url, True)
                self.check_post_completion(file_url)
                return

            except (requests.RequestException, _RetryableDownloadError) as e:
                resp = getattr(e, "response", None)
                status_code = getattr(resp, "status_code", None)
                if is_terminal_error(e):
                    # 400/404/410/...: the request itself is wrong, so no
                    # number of retries can succeed. Report it once instead of
                    # spending the whole retry budget on it: a 404 used to cost
                    # 50 requests and ~23 minutes of sleeping.
                    error_msg = translate(
                        "download_file_unavailable", file_url, status_code
                    )
                    self._safe_emit(
                        self.log, translate("log_error", error_msg), "ERROR"
                    )
                    with self.failed_files_lock:
                        self.failed_files[file_url] = error_msg
                    self._safe_emit(self.file_progress, file_index, 0)
                    self._safe_emit(self.file_completed, file_index, file_url, False)
                    self.check_post_completion(file_url)
                    return
                if attempt == max_retries:
                    error_msg = translate(
                        "error_downloading_after_retries", file_url, max_retries, str(e)
                    )
                    self._safe_emit(
                        self.log, translate("log_error", error_msg), "ERROR"
                    )
                    # Out of retries: the truncated transfer must not stay on
                    # disk under any name.
                    self._discard_part_file(part_path)
                    with self.failed_files_lock:
                        self.failed_files[file_url] = str(e)
                    self._safe_emit(self.file_progress, file_index, 0)
                    self._safe_emit(self.file_completed, file_index, file_url, False)
                    self.check_post_completion(file_url)
                    return
                else:
                    # Exponential backoff instead of a flat 1s delay, so
                    # repeated failures don't hammer the server at a fixed
                    # rate. Retry-After is only present on HTTP errors; other
                    # failures (timeouts, connection errors,
                    # _RetryableDownloadError) fall back to the plain
                    # exponential schedule.
                    retry_after_header = (
                        resp.headers.get("Retry-After") if resp is not None else None
                    )

                    delay = min(2 ** (attempt - 1), 30)
                    if status_code in (403, 429):
                        # These are WAF/rate-limit signals specifically -
                        # retrying fast makes the block more likely to
                        # persist, so enforce a higher floor even on the
                        # first retry.
                        delay = max(delay, 5)
                    if retry_after_header:
                        try:
                            delay = max(delay, float(retry_after_header))
                        except ValueError:
                            pass

                    self._safe_emit(
                        self.log,
                        translate(
                            "log_warning",
                            translate(
                                "download_failed_retrying",
                                file_url,
                                attempt,
                                max_retries,
                                str(e),
                            ),
                        ),
                        "WARNING",
                    )
                    await asyncio.sleep(delay)
            except _Cancelled:
                # The user stopped the run. Nothing failed, so nothing is
                # recorded and nothing is offered for retry.
                self._discard_part_file(part_path)
                self._safe_emit(self.file_progress, file_index, 0)
                self._safe_emit(self.file_completed, file_index, file_url, False)
                return
            except Exception as e:
                self._safe_emit(
                    self.log,
                    translate(
                        "log_error",
                        translate("unexpected_error_downloading", file_url, str(e)),
                    ),
                    "ERROR",
                )
                # Attempt to remove the partial transfer left on disk. The
                # final name is only ever created by a successful rename, so
                # this is the only place leftovers can be.
                self._discard_part_file(part_path)

                with self.failed_files_lock:
                    self.failed_files[file_url] = str(e)
                self._safe_emit(self.file_progress, file_index, 0)
                self._safe_emit(self.file_completed, file_index, file_url, False)
                self.check_post_completion(file_url)
                return

    def check_post_completion(self, file_url):
        post_id = self.files_to_posts_map.get(file_url)
        if post_id in self.post_files_map:
            post_files = self.post_files_map[post_id]
            if all(f in self.completed_files for f in post_files):
                self._safe_emit(self.post_completed, post_id)

    def _record_post_download(self, post_id):
        """Stamp a post's last-download date once one of its files hits disk.

        Called for every file that is actually written to disk, but only the
        first call per post reaches the database, so a 40-file post produces a
        single row.  Files skipped by the hash-database dedup never call this,
        so re-checking a post you already have leaves its date alone.
        """
        if not post_id:
            return
        with self._history_lock:
            if post_id in self._stamped_posts:
                return
            self._stamped_posts.add(post_id)
        try:
            self.history_db.record_post(self.service, self.creator_id, post_id)
        except Exception as e:
            self._safe_emit(
                self.log,
                translate("log_warning", f"Could not update download history: {e}"),
                "WARNING",
            )

    async def download_worker(self, queue, folder, total_files):
        while self.is_running:
            try:
                file_index, file_url, page_number = await asyncio.wait_for(
                    queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                # Re-check self.is_running on next iteration
                continue
            except asyncio.CancelledError:
                return
            try:
                await self.download_file(
                    file_url, folder, file_index, total_files, page_number
                )
            except asyncio.CancelledError:
                return  # finally still runs → task_done()
            except Exception as e:
                self._safe_emit(
                    self.log,
                    translate(
                        "log_error", translate("error_in_download_worker", str(e))
                    ),
                    "ERROR",
                )
            finally:
                queue.task_done()

    def run(self):
        try:
            if not self.is_running:
                # Emit anyway: this signal is what runs the tab's cleanup, and
                # without it the page stays locked in the downloading state.
                self.finished.emit()
                return
            self._safe_emit(
                self.log,
                translate(
                    "log_info",
                    translate(
                        "creator_download_thread_started", self.service, self.creator_id
                    ),
                ),
                "INFO",
            )
            self.fetch_creator_and_post_info()
        except Exception as e:
            try:
                self._safe_emit(self.log, translate("log_error", str(e)), "ERROR")
            except Exception:
                pass
            # Ensure we exit cleanly
            self.is_running = False
            # The tab's cleanup runs off this signal; an early exit that emits
            # nothing left the page busy until Cancel was pressed.
            self.finished.emit()
            return
        total_posts = len(self.selected_posts)
        self._safe_emit(
            self.log,
            translate("log_info", translate("total_posts", total_posts)),
            "INFO",
        )

        creator_folder_name = f"{self.creator_id}_{self.creator_name}"
        creator_folder = os.path.join(self.download_folder, creator_folder_name)
        try:
            os.makedirs(creator_folder, exist_ok=True)
        except OSError as e:
            self._safe_emit(
                self.log,
                translate(
                    "log_error",
                    translate(
                        "failed_to_create_creator_folder", creator_folder, str(e)
                    ),
                ),
                "ERROR",
            )
        self._safe_emit(
            self.log,
            translate("log_info", translate("created_directory", creator_folder)),
            "INFO",
        )

        total_files = len(self.files_to_download)
        self._safe_emit(
            self.log,
            translate(
                "log_info", translate("total_selected_files_to_download", total_files)
            ),
            "INFO",
        )

        if total_files > 0:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                queue = asyncio.Queue()
                post_order_counts = {}
                for i, file_url in enumerate(self.files_to_download):
                    pid = self.files_to_posts_map.get(file_url, self.creator_id)
                    post_order_counts[pid] = post_order_counts.get(pid, 0) + 1
                    # A number decided when the file list was built wins, so a
                    # retry reuses the name the first run would have used.
                    number = self.file_numbers.get(file_url, post_order_counts[pid])
                    queue.put_nowait((i, file_url, number))

                async def main():
                    tasks = [
                        loop.create_task(
                            self.download_worker(queue, creator_folder, total_files)
                        )
                        for _ in range(self.max_concurrent)
                    ]
                    # Wait for all queued items to be processed, but
                    # periodically check for cancellation so we don't
                    # block forever when workers stop consuming.
                    while self.is_running:
                        try:
                            await asyncio.wait_for(queue.join(), timeout=0.5)
                            break  # All items processed
                        except asyncio.TimeoutError:
                            continue
                    # Cancel idle workers still waiting on queue.get()
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)

                loop.run_until_complete(main())
            except Exception as e:
                self._safe_emit(
                    self.log,
                    translate(
                        "log_error", translate("error_in_async_download_loop", str(e))
                    ),
                    "ERROR",
                )
            finally:
                if not loop.is_closed():
                    loop.run_until_complete(loop.shutdown_asyncgens())
                    # Wait for asyncio.to_thread() executor threads to finish
                    # so no thread outlives the QThread C++ object.
                    loop.run_until_complete(loop.shutdown_default_executor())
                    loop.close()
        else:
            self._safe_emit(
                self.log,
                translate("log_warning", translate("no_files_selected_for_download")),
                "WARNING",
            )

        # Log summary of failed files
        if self.failed_files:
            self._safe_emit(
                self.log,
                translate(
                    "log_warning",
                    translate(
                        "download_completed_with_failed_files", len(self.failed_files)
                    ),
                ),
                "WARNING",
            )
            for file_url, error in self.failed_files.items():
                self._safe_emit(
                    self.log,
                    translate(
                        "log_error",
                        translate("failed_to_download_file", file_url, error),
                    ),
                    "ERROR",
                )

        if self.is_running:
            self._safe_emit(self.finished)


class CheckboxToggleThread(_StoppableThread, QThread):
    finished = pyqtSignal(dict, list)
    log = pyqtSignal(str, str)

    def __init__(self, visible_posts, checked_urls, check_all_state):
        super().__init__()
        self.visible_posts = (
            visible_posts  # Use visible posts instead of all_detected_posts
        )
        self.checked_urls = checked_urls.copy()
        self.check_all_state = check_all_state
        self.is_running = True

    def run(self):
        if not self.is_running:
            return
        is_checked = self.check_all_state == 2  # Qt.CheckState.Checked
        new_state = Qt.CheckState.Checked if is_checked else Qt.CheckState.Unchecked

        # Only update checked_urls for posts that are currently visible
        affected_post_ids = set()
        for post_title, (post_id, _) in self.visible_posts:
            self.checked_urls[post_id] = new_state == Qt.CheckState.Checked
            affected_post_ids.add(post_id)

        # Update posts_to_download based on all checked posts, not just visible ones
        posts_to_download = [
            post_id for post_id, checked in self.checked_urls.items() if checked
        ]
        self.log.emit(
            translate(
                "log_debug",
                translate(
                    "checkbox_toggle_completed",
                    is_checked,
                    len(affected_post_ids),
                    len(posts_to_download),
                ),
            ),
            "DEBUG",
        )
        self.finished.emit(self.checked_urls, posts_to_download)


class LogsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent = parent
        self.setWindowTitle(translate("full_logs"))
        self.setModal(False)
        self.resize(800, 600)
        self.setStyleSheet("background: #1A2B4A; color: white;")

        layout = QVBoxLayout(self)

        # Logs display
        self.logs_display = QTextEdit()
        self.logs_display.setReadOnly(True)
        self.logs_display.setStyleSheet(
            "background: #2A3B5A; border-radius: 5px; padding: 5px;"
        )
        self.logs_display.document().setMaximumBlockCount(LOG_LINE_LIMIT)
        layout.addWidget(self.logs_display)

        # Buttons layout
        buttons_layout = QHBoxLayout()

        self.clear_logs_btn = QPushButton(translate("clear_logs"))
        self.clear_logs_btn.clicked.connect(self.clear_logs)
        self.clear_logs_btn.setStyleSheet(_RUN_BUTTON_STYLE)
        buttons_layout.addWidget(self.clear_logs_btn)

        self.download_logs_btn = QPushButton(translate("download_logs"))
        self.download_logs_btn.clicked.connect(self.download_logs)
        self.download_logs_btn.setStyleSheet(_RUN_BUTTON_STYLE)
        buttons_layout.addWidget(self.download_logs_btn)

        buttons_layout.addStretch()
        layout.addLayout(buttons_layout)

        # Batch update with timer to reduce UI updates
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._do_update)
        self.update_timer.setInterval(500)  # Update every 500ms instead of every log
        self.needs_update = False
        # Index into the parent's log store: only lines past this point still
        # have to be drawn, so updates never rebuild the whole document.
        self._shown = 0

        # Update logs content
        self.update_logs_content()

    def update_logs_content(self):
        """Schedule a batched update instead of updating immediately"""
        self.needs_update = True
        if not self.update_timer.isActive():
            self.update_timer.start()

    def _do_update(self):
        """Draw whatever is new since the last tick.

        ``setHtml`` used to rebuild the whole document every 500 ms, which
        snapped the window back to the top on every update. Appending only the
        new lines keeps the scroll position, and follows the bottom when the
        user was already there.
        """
        if not self.needs_update or not self._parent:
            self.needs_update = False
            self.update_timer.stop()
            return

        bar = self.logs_display.verticalScrollBar()
        old_value = bar.value()
        at_bottom = old_value >= bar.maximum() - 4

        if hasattr(self._parent, "log_lines_from"):
            pending = self._parent.log_lines_from(self._shown)
            if pending:
                batched = len(pending) > 1
                if batched:
                    self.logs_display.setUpdatesEnabled(False)
                try:
                    for message, color in pending:
                        self.logs_display.append(_log_line_html(message, color))
                finally:
                    if batched:
                        self.logs_display.setUpdatesEnabled(True)
            # Absolute index, so trimming the parent's store never stalls us.
            self._shown = self._parent.log_next_index()

        bar.setValue(bar.maximum() if at_bottom else old_value)
        self.needs_update = False
        # Caught up: idle instead of re-firing every 500 ms until the window
        # closes. ``update_logs_content()`` restarts the timer on the next
        # line, so nothing can be missed.
        self.update_timer.stop()

    def closeEvent(self, a0):
        """Stop timer when window closes"""
        self.update_timer.stop()
        if a0 is not None:
            a0.accept()

    def clear_logs(self):
        """Clear the log window and the parent's shared log store"""
        self.logs_display.clear()
        self._shown = 0
        if self._parent and hasattr(self._parent, "clear_log"):
            self._parent.clear_log()

    def download_logs(self):
        """Download logs as a txt file"""
        # Get plain text content (without HTML formatting)
        logs_content = self.logs_display.toPlainText()

        if not logs_content.strip():
            return

        # Default filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"kemono_logs_{timestamp}.txt"

        # Open file dialog
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            self.windowTitle(),
            default_filename,
            "Text Files (*.txt);;All Files (*)",
        )

        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(logs_content)
                if self._parent and hasattr(self._parent, "append_log_to_console"):
                    self._parent.append_log_to_console(
                        f"Logs saved to: {file_path}", "INFO"
                    )
            except Exception as e:
                if self._parent and hasattr(self._parent, "append_log_to_console"):
                    self._parent.append_log_to_console(
                        translate("log_error", f"Failed to save logs: {str(e)}"),
                        "ERROR",
                    )


class _CreatorQueueComposer(QLineEdit):
    """The Creator Queue's one-line URL field.

    Enter arrives as ``returnPressed`` already, but Space is not a legal URL
    character, so it commits the entry too instead of inserting whitespace
    the validator would then reject.
    """

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event):
        """Show the standard edit menu with the queue's shared highlight."""
        menu = self.createStandardContextMenu()
        menu.setStyleSheet(MENU_STYLE)
        menu.exec(event.globalPos())
        menu.deleteLater()


class _CreatorQueueRow(QWidget):
    """A queue row whose empty area means "load this creator".

    The eye and the ✕ stay ordinary buttons; double-clicking anywhere else on
    the row (the URL text, the gaps) opens the creator, which makes the label
    itself a big, obvious target.
    """

    def __init__(self, on_double_click, parent=None):
        super().__init__(parent)
        self._on_double_click = on_double_click

    def mouseDoubleClickEvent(self, event):
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._on_double_click is not None
        ):
            self._on_double_click()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class CreatorDownloaderTab(QWidget):
    def __init__(self, parent):
        super().__init__()
        self._parent = parent
        self.posts_to_download = []
        self.post_url_map = {}
        self.all_detected_posts = []
        self.creator_queue = []
        self.downloading = False
        # Set when an auto-loaded creator will re-enable the queue afterwards;
        # the input row takes focus back so the next URL can be typed.
        self._restore_queue_input_focus = False
        # Guards the end-of-run bookkeeping so a late cleanup_thread pass
        # cannot re-finalise a run that already finalised itself.
        self._run_finished = False
        self.other_files_dir = self._parent.other_files_folder if self._parent else ""
        self.current_creator_url = None
        self.all_files_map = {}
        self.checked_urls = {}
        # (creator_url, post_id) -> the post record last shown in the preview
        # dialog, so reopening a post does not hit the API again.  OrderedDict
        # lets a cache hit refresh its position for LRU eviction.
        self._post_preview_cache = OrderedDict()
        # One bounded byte cache for every post preview in this session.  Each
        # dialog's loader reads and writes it; switching creators clears it.
        self._preview_image_cache = PreviewImageCache(DEFAULT_PREVIEW_CACHE_BYTES)
        # Post preview fetches outlive their dialog when the user closes it
        # before the API answers; the tab keeps them alive until finished.
        self._preview_fetch_threads = []
        self.current_file_index = -1
        self.active_threads = []
        # Threads that were stopped but were still running when their last
        # other reference went away; held here until Qt reports them finished.
        self._lingering_threads = []
        self.completed_posts = set()
        self.total_posts_to_download = 0
        self.total_files_to_download = 0
        self.completed_files = set()

        self.failed_files = {}  # Map file_url to error message
        # Locks for thread-safe access to shared data structures
        self.completed_files_lock = threading.Lock()
        self.failed_files_lock = threading.Lock()
        self.post_detection_thread = None
        self.post_population_thread = None
        self.filter_thread = None
        self.file_preparation_thread = None
        self.checkbox_toggle_thread = None
        self._cancellation_thread = None
        # The CreatorDownloadThread of the run in flight. A finished thread can
        # linger in active_threads until its cleanup slot runs, so "is a
        # download running?" consults this reference instead of the list.
        self._download_thread = None
        self.post_titles_map = {}
        self.post_dates_map = (
            {}
        )  # post_id -> display string of the post's own publish date
        # post_id -> lower-case searchable text ("filenames"/"description"/
        # "tags"), filled while detecting posts so the "Search by" scopes can
        # filter the list without touching the network or re-parsing HTML.
        self.post_search_index = {}
        self._found_type_counts = {}
        # Set when a filter request arrives while FilterThread is still
        # running, so the change is applied once that pass finishes.
        self._filter_refresh_pending = False
        # post_id -> "YYYY-MM-DD" of the last actual download, for the creator
        # being viewed only.  Rendered in square brackets after the publish
        # date in each row.
        self._post_history_cache = {}
        # Newest download timestamp recorded for the creator being viewed.
        self._creator_last_download = None
        # Lazily opened download-history database (see _history_db()).
        self._history_db_instance = None
        self._history_db_dir = None
        self._history_db_failed_dir = None
        # Lazily opened config-profile store (see _config_store()).
        self._config_store_instance = None
        self._config_store_dir = None
        self._config_store_failed_dir = None
        # The built-in page state, captured after setup_ui() and before any
        # stored profile is applied, so "back to default" works even with
        # nothing saved. Empty until then.
        self._builtin_config: dict = {}
        self.post_widget_cache = (
            {}
        )  # Maps post_title -> (item, widget) for O(1) lookups
        # Pagination variables
        self.posts_per_page = 200  # Number of posts to show per page
        self.current_page = 1
        self.total_pages = 1
        self.filtered_posts = []  # Cache of filtered posts for pagination
        # Creator URL -> set of post ids requested via pasted post links. When a
        # creator is queued from a post link, viewing that creator auto-selects
        # only those posts instead of every post the creator has.
        self._batch_post_ids: dict[str, set] = {}
        # Creator URL -> display name reported by the profile endpoint while
        # that creator was loaded. Names are decoration on a queue row and are
        # never required, so a failed lookup simply leaves the row as the URL.
        self._creator_names: dict[str, str] = {}
        # URLs waiting for / using one of the name-lookup workers, so the same
        # creator is never requested twice.
        self._name_lookup_pending: list[str] = []
        self._name_lookup_wanted: set[str] = set()
        self._name_lookup_threads: dict[str, object] = {}
        # Where the reader was before a search narrowed the list. A search
        # always starts on page 1; clearing it puts the page and scroll back.
        self._search_return_position: Optional[tuple[int, int]] = None
        self._pending_filter_scroll: Optional[int] = None
        # Set when a post-link selection still has to be applied to the filtered
        # list once it has been rebuilt for display.
        self._post_link_selection_pending = False
        self._pending_detection_summary = False
        self._last_detection_thread = None
        self._file_skip_count = 0
        self._file_skip_keywords = []
        self._images_skipped_count = 0
        # Latest per-filter skip counters, surfaced in the run summary block
        # under the progress bars instead of being buried in the log.
        self._post_skip_stats = {
            "keywords": 0,
            "date": 0,
            "file_count": 0,
            "filetypes": 0,
        }
        # Per-keyword skip counts (post level and file level) for the tooltip.
        self._post_keyword_skip_counts = {}
        self._file_keyword_skip_counts = {}
        # True once the fetch in flight has delivered its first batch, so a
        # refetch replaces the cached post list instead of appending to it.
        self._fetch_batches_started = False
        # Canonical log store: (message, colour) pairs. The full LogsWindow is
        # the only view over this list, so logging never touches a widget (and
        # therefore never invalidates the layout).
        self._log_lines = []
        self._log_line_limit = LOG_LINE_LIMIT
        # Debug lines are only kept when the Settings switch is on; refreshed
        # whenever settings are applied and read once more on startup below.
        self._verbose_logging = False
        # Count of lines dropped from the front of the store, so view indices
        # stay absolute even after the cap starts trimming.
        self._log_dropped = 0
        # The log button's line count is the only live UI logging touches, so
        # it is refreshed on a short timer instead of once per line.
        self._log_counter_timer = QTimer(self)
        self._log_counter_timer.setSingleShot(True)
        self._log_counter_timer.setInterval(500)
        self._log_counter_timer.timeout.connect(self._update_log_button_text)
        # Cached skip breakdown: those counters cannot change during a
        # download, so rebuilding them per completed file is wasted work.
        self._skip_summary_cache = None
        # Failures from the last finished/cancelled run, kept so they can be
        # retried without re-fetching or re-preparing anything.
        self._last_run_failed_files = {}
        self._last_run_files_to_posts_map = {}
        self._last_run_creator_url = None
        # {file_number} (url -> position in its post) and {post_file_count}
        # (post_id -> files), decided when a run's file list is built so a
        # retry of the failures keeps the same names and folder rules.
        self._last_run_file_numbers = {}
        self._last_run_post_file_counts = {}
        # Creator folder of the run in flight (or the last one that produced
        # files), for the "open folder" button. None until it is confirmed.
        self._current_creator_folder = None
        self.files_to_posts_map = {}
        self.other_files_dir = ensure_directory(
            self.other_files_dir, "Other Files folder"
        )
        self.setup_ui()
        if self._parent and hasattr(self._parent, "settings_tab"):
            self._parent.settings_tab.settings_applied.connect(self.refresh_ui)
            self._parent.settings_tab.language_changed.connect(self.update_ui_text)
            self._parent.settings_tab.settings_applied.connect(
                self._refresh_verbose_logging
            )
            self._parent.settings_tab.settings_applied.connect(
                self._refresh_show_only_found_filetypes
            )
            # Keyword matching lives in Settings now; a change must re-run the
            # list pass so the rows and counters match the new rules.
            self._parent.settings_tab.settings_applied.connect(
                self._on_keyword_settings_applied
            )
        self._refresh_verbose_logging()
        self._refresh_show_only_found_filetypes()
        # Capture the built-in page state before a stored profile can touch
        # it: that snapshot is what a creator without a config falls back to
        # when nothing was ever saved, and it tracks new widgets for free.
        self._builtin_config = self._config_snapshot()
        self._load_page_config()
        self._refresh_config_buttons()

    def _refresh_verbose_logging(self):
        """Pick up the Settings switch, tolerating a parent without settings."""
        settings_tab = getattr(self._parent, "settings_tab", None)
        getter = getattr(settings_tab, "get_verbose_logging", None)
        self._verbose_logging = bool(getter()) if callable(getter) else False

    def _refresh_show_only_found_filetypes(self):
        """Pick up the Settings mode, then re-lay the extension boxes."""
        settings_tab = getattr(self._parent, "settings_tab", None)
        getter = getattr(settings_tab, "get_show_only_found_filetypes", None)
        mode = getter() if callable(getter) else "off"
        if mode not in ("on", "on_with_count"):
            mode = "off"
        self._found_filetypes_mode = mode
        self._render_creator_ext_checks()

    def _on_keyword_settings_applied(self):
        """Re-filter the loaded list after keyword-matching settings change."""
        fetch = getattr(self, "post_detection_thread", None)
        if fetch is not None and fetch.isRunning():
            # The fetch owns the list and runs its own pass at the end.
            return
        if not self.all_detected_posts or self._download_in_progress():
            return
        self.filter_items()

    def _create_thread_settings(self):
        """Create a ThreadSettings object with current settings values"""
        if not (self._parent and hasattr(self._parent, "settings_tab")):
            # Return defaults when parent settings are not available
            return ThreadSettings(1, 1, 1, 1, 1, settings_tab=None)

        return ThreadSettings(
            creator_posts_max_attempts=self._parent.settings_tab.get_creator_posts_max_attempts(),
            post_data_max_retries=self._parent.settings_tab.get_post_data_max_retries(),
            file_download_max_retries=self._parent.settings_tab.get_file_download_max_retries(),
            api_request_max_retries=self._parent.settings_tab.get_api_request_max_retries(),
            simultaneous_downloads=self._parent.settings_tab.get_simultaneous_downloads(),
            settings_tab=self._parent.settings_tab,
        )

    def setup_ui(self):
        layout = QHBoxLayout(self)

        # Left widget
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        # Creator Queue Group. The list keeps its three-row height; the one
        # blank row underneath is where a creator or post URL is typed or
        # pasted. The input lives outside the list so rebuilding the list can
        # never disturb the widget being typed into.
        self.creator_queue_group = QGroupBox()
        self.creator_queue_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        creator_queue_layout = QVBoxLayout()

        self.creator_queue_list = QListWidget()
        self.creator_queue_list.setFixedHeight(100)
        self.creator_queue_list.setStyleSheet(
            # A muted, low-opacity selection (and hover) that matches the post
            # list's selected-row tint. The :!active rule is the important one:
            # without it Fusion paints an opaque black bar once the list loses
            # focus, which looked like a stuck selection.
            "QListWidget { background: #2A3B5A; border-radius: 5px; }"
            "QListWidget::item { background: transparent; border-radius: 4px; }"
            "QListWidget::item:hover { background: rgba(74, 91, 122, 60); }"
            "QListWidget::item:selected { background: rgba(74, 91, 122, 150); }"
            "QListWidget::item:selected:!active"
            " { background: rgba(74, 91, 122, 90); }"
        )
        # File import has no button of its own any more; it is reachable from
        # the queue's context menu instead of taking a row of its own.
        self.creator_queue_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self.creator_queue_list.customContextMenuRequested.connect(
            self._show_queue_context_menu
        )
        creator_queue_layout.addWidget(self.creator_queue_list)

        creator_queue_input_layout = QHBoxLayout()
        creator_queue_input_layout.setContentsMargins(0, 0, 0, 0)
        creator_queue_input_layout.setSpacing(5)

        self.creator_queue_input_btn = QPushButton(
            qta.icon("fa5s.eye", color="white"), ""
        )
        self.creator_queue_input_btn.setStyleSheet(
            # Scoped to QPushButton: an unscoped rule also lands on the
            # tooltip label Qt parents to the button, which squeezed the
            # tooltip down to the button's own size.
            scoped(
                "QPushButton",
                "background: #4A5B7A; padding: 2px; border-radius: 5px; "
                "min-width: 30px; max-width: 30px; min-height: 30px; "
                "max-height: 30px;",
            )
        )
        self.creator_queue_input_btn.setToolTip(
            translate("add_creator_and_load_tooltip")
        )
        self.creator_queue_input_btn.clicked.connect(self.add_creator_and_load)
        creator_queue_input_layout.addWidget(self.creator_queue_input_btn)

        self.creator_queue_input = _CreatorQueueComposer()
        self.creator_queue_input.setPlaceholderText(
            translate("creator_queue_input_placeholder")
        )
        self.creator_queue_input.setStyleSheet(
            # Scoped so the field's padding/radius does not leak into the
            # standard edit menu Qt parents to it.
            scoped(
                "QLineEdit",
                "background: #2A3B5A; border-radius: 5px;"
                " padding: 2px 8px; color: white;",
            )
        )
        self.creator_queue_input.setFixedHeight(30)
        self.creator_queue_input.returnPressed.connect(self.add_creator_to_queue)
        creator_queue_input_layout.addWidget(self.creator_queue_input, stretch=1)

        creator_queue_layout.addLayout(creator_queue_input_layout)
        self.creator_queue_group.setLayout(creator_queue_layout)
        left_layout.addWidget(self.creator_queue_group)

        # Download Options Group
        self.creator_options_group = QGroupBox()
        self.creator_options_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        creator_options_layout = QVBoxLayout()

        creator_categories_layout = QHBoxLayout()
        self.creator_main_check = QCheckBox()
        self.creator_main_check.setChecked(False)
        creator_categories_layout.addWidget(self.creator_main_check)
        self.creator_attachments_check = QCheckBox()
        self.creator_attachments_check.setChecked(False)
        creator_categories_layout.addWidget(self.creator_attachments_check)
        self.creator_content_check = QCheckBox()
        self.creator_content_check.setChecked(False)
        creator_categories_layout.addWidget(self.creator_content_check)
        creator_categories_layout.addStretch()
        creator_options_layout.addLayout(creator_categories_layout)

        # Download text checkbox
        self.creator_download_text_check = QCheckBox(translate("download_text"))
        self.creator_download_text_check.setChecked(False)
        self.creator_download_text_check.setStyleSheet("color: white;")
        creator_options_layout.addWidget(self.creator_download_text_check)

        # Skip post folder for low-image-count posts toggle + dropdown
        skip_single_image_layout = QHBoxLayout()
        skip_single_image_layout.setContentsMargins(0, 0, 0, 0)
        self.creator_skip_folder_check = QCheckBox(
            translate("skip_folder_for_few_images")
        )
        self.creator_skip_folder_check.setChecked(False)
        self.creator_skip_folder_check.setStyleSheet("color: white;")
        skip_single_image_layout.addWidget(self.creator_skip_folder_check)

        # Toggle: keep compressed archives (ZIP/7z/RAR) in their own post
        # folder even when Skip Post Folder would otherwise skip it.
        self.creator_force_compressed_folder_check = QCheckBox()
        self.creator_force_compressed_folder_check.setIcon(
            qta.icon("fa5s.file-archive", color="#FFD700")
        )
        self.creator_force_compressed_folder_check.setChecked(False)
        self.creator_force_compressed_folder_check.setStyleSheet("color: white;")
        self.creator_force_compressed_folder_check.setToolTip(
            translate("force_folder_for_compressed")
        )
        skip_single_image_layout.addWidget(self.creator_force_compressed_folder_check)

        self.creator_skip_folder_info_btn = QPushButton(
            qta.icon("fa5s.info-circle", color="#A0C0FF"), ""
        )
        self.creator_skip_folder_info_btn.setFixedSize(26, 26)
        self.creator_skip_folder_info_btn.setStyleSheet(
            scoped("QPushButton", "background: #4A5B7A; border-radius: 5px;")
        )
        self.creator_skip_folder_info_btn.clicked.connect(self.show_skip_folder_info)
        skip_single_image_layout.addWidget(self.creator_skip_folder_info_btn)
        skip_single_image_layout.addSpacing(10)

        self.creator_skip_folder_combo = QComboBox()
        for n in range(1, 11):
            self.creator_skip_folder_combo.addItem(str(n), n)
        self.creator_skip_folder_combo.setCurrentIndex(0)  # Default: 1
        self.creator_skip_folder_combo.setFixedWidth(60)
        self.creator_skip_folder_combo.setStyleSheet(
            scoped("QComboBox", "padding: 5px; border-radius: 5px;")
        )
        skip_single_image_layout.addWidget(self.creator_skip_folder_combo)
        skip_single_image_layout.addStretch()
        creator_options_layout.addLayout(skip_single_image_layout)

        # Skip a post's images when it also offers a compressed archive (the
        # archive is downloaded instead). Sits above the extension tickboxes
        # so the option that prunes files comes first.
        skip_images_layout = QHBoxLayout()
        skip_images_layout.setContentsMargins(0, 0, 0, 0)
        self.creator_skip_images_check = QCheckBox(
            translate("skip_images_if_compressed")
        )
        self.creator_skip_images_check.setChecked(False)
        self.creator_skip_images_check.setStyleSheet("color: white;")
        skip_images_layout.addWidget(self.creator_skip_images_check)

        self.creator_skip_images_info_btn = QPushButton(
            qta.icon("fa5s.info-circle", color="#A0C0FF"), ""
        )
        self.creator_skip_images_info_btn.setFixedSize(26, 26)
        self.creator_skip_images_info_btn.setStyleSheet(
            scoped("QPushButton", "background: #4A5B7A; border-radius: 5px;")
        )
        self.creator_skip_images_info_btn.clicked.connect(self.show_skip_images_info)
        skip_images_layout.addWidget(self.creator_skip_images_info_btn)
        skip_images_layout.addStretch()
        creator_options_layout.addLayout(skip_images_layout)

        self.creator_ext_group = QGroupBox()
        self.creator_ext_group.setStyleSheet("QGroupBox { color: white; }")
        creator_ext_layout = QGridLayout()
        creator_ext_layout.setHorizontalSpacing(20)
        creator_ext_layout.setVerticalSpacing(10)
        self.creator_ext_checks = {
            ".jpg": QCheckBox("JPG"),
            ".png": QCheckBox("PNG"),
            ".zip": QCheckBox("ZIP"),
            ".mp4": QCheckBox("MP4"),
            ".gif": QCheckBox("GIF"),
            ".pdf": QCheckBox("PDF"),
            ".7z": QCheckBox("7Z"),
            ".mp3": QCheckBox("MP3"),
            ".wav": QCheckBox("WAV"),
            ".flac": QCheckBox("FLAC"),
            ".rar": QCheckBox("RAR"),
            ".mov": QCheckBox("MOV"),
            ".docx": QCheckBox("DOCX"),
            ".psd": QCheckBox("PSD"),
            ".clip": QCheckBox("CLIP"),
            ".jpe": QCheckBox("JPE"),
            ".webp": QCheckBox("WEBP"),
        }
        # Remember the plain labels so the count suffix can be dropped again.
        self._creator_ext_base_labels = {
            ext: check.text() for ext, check in self.creator_ext_checks.items()
        }
        for i, (ext, check) in enumerate(self.creator_ext_checks.items()):
            check.setChecked(False)
            check.stateChanged.connect(self._on_filetype_filter_changed)
            creator_ext_layout.addWidget(check, i // 5, i % 5)
        self.creator_ext_group.setLayout(creator_ext_layout)
        # Kept for _render_creator_ext_checks(), which re-lays the boxes from
        # the Settings "Show only types found in creator" switch.
        self._creator_ext_layout = creator_ext_layout

        # Shown instead of the boxes when the filter is on and none of the
        # supported types are present (no creator loaded, or a creator holding
        # none of them), so an enabled filter never falls back to listing every
        # type.
        self.creator_ext_empty_label = QLabel(
            translate("supported_filetypes_not_present")
        )
        self.creator_ext_empty_label.setStyleSheet("color: #8FA6C8;")
        self.creator_ext_empty_label.setVisible(False)
        creator_options_layout.addWidget(self.creator_ext_group)

        self.creator_options_group.setLayout(creator_options_layout)
        left_layout.addWidget(self.creator_options_group)

        # Progress and the run summary share one box, so everything above the
        # buttons reads as a single section.
        self.run_summary_group = QGroupBox()
        self.run_summary_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        run_summary_layout = QVBoxLayout()

        creator_progress_layout = QVBoxLayout()
        self.creator_file_progress_label = QLabel()
        creator_progress_layout.addWidget(self.creator_file_progress_label)
        self.creator_file_progress = QProgressBar()
        self.creator_file_progress.setStyleSheet(
            "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; background: #2A3B5A; } QProgressBar::chunk { background: #4A5B7A; }"
        )
        self.creator_file_progress.setRange(0, 100)
        creator_progress_layout.addWidget(self.creator_file_progress)
        self.creator_overall_progress_label = QLabel()
        creator_progress_layout.addWidget(self.creator_overall_progress_label)
        self.creator_overall_progress = QProgressBar()
        self.creator_overall_progress.setStyleSheet(
            "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; background: #2A3B5A; } QProgressBar::chunk { background: #4A5B7A; }"
        )
        self.creator_overall_progress.setRange(0, 100)
        creator_progress_layout.addWidget(self.creator_overall_progress)
        run_summary_layout.addLayout(creator_progress_layout)

        # Run summary: what the last run did, kept out of the log so it stays
        # visible while the log panel is minimised.
        self.creator_download_summary_label = QLabel()
        self.creator_download_summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.creator_download_summary_label.setStyleSheet("color: white;")
        run_summary_layout.addWidget(self.creator_download_summary_label)

        self.creator_skip_summary_label = QLabel()
        self.creator_skip_summary_label.setTextFormat(Qt.TextFormat.RichText)
        self.creator_skip_summary_label.setStyleSheet("color: white;")
        self.creator_skip_summary_label.setWordWrap(True)
        run_summary_layout.addWidget(self.creator_skip_summary_label)

        # File-level filters: keyword skips follow the loaded list, the archive
        # rule is only decided when a download runs.
        self.creator_skip_files_label = QLabel()
        self.creator_skip_files_label.setTextFormat(Qt.TextFormat.RichText)
        self.creator_skip_files_label.setStyleSheet("color: white;")
        self.creator_skip_files_label.setWordWrap(True)
        run_summary_layout.addWidget(self.creator_skip_files_label)

        self.run_summary_group.setLayout(run_summary_layout)
        left_layout.addWidget(self.run_summary_group)

        # Buttons layout
        creator_btn_layout = QHBoxLayout()
        self.creator_download_btn = QPushButton(
            qta.icon("fa5s.download", color="white"), ""
        )
        self.creator_download_btn.clicked.connect(self.start_creator_download)
        self.creator_download_btn.setStyleSheet(_RUN_BUTTON_STYLE)
        creator_btn_layout.addWidget(self.creator_download_btn)
        self.creator_cancel_btn = QPushButton(qta.icon("fa5s.times", color="white"), "")
        self.creator_cancel_btn.clicked.connect(self.cancel_creator_download)
        self.creator_cancel_btn.setStyleSheet(_RUN_BUTTON_STYLE)
        self.creator_cancel_btn.setEnabled(False)
        creator_btn_layout.addWidget(self.creator_cancel_btn)

        # Retry sits with the other run controls. It stays visible and is only
        # greyed out when there is nothing to retry (or a run is in progress).
        self.creator_retry_failed_btn = QPushButton(
            qta.icon("fa5s.redo", color="white"), ""
        )
        self.creator_retry_failed_btn.clicked.connect(self.retry_failed_downloads)
        self.creator_retry_failed_btn.setStyleSheet(_RUN_BUTTON_STYLE)
        self.creator_retry_failed_btn.setEnabled(False)
        creator_btn_layout.addWidget(self.creator_retry_failed_btn)

        # Sits with the run controls but follows the folder, not the run: it
        # stays greyed until this run's creator folder actually exists.
        self.creator_open_folder_btn = QPushButton(
            qta.icon("fa5s.folder-open", color="white"), ""
        )
        self.creator_open_folder_btn.clicked.connect(self._open_creator_folder)
        self.creator_open_folder_btn.setStyleSheet(_RUN_BUTTON_STYLE)
        self.creator_open_folder_btn.setEnabled(False)
        creator_btn_layout.addWidget(self.creator_open_folder_btn)

        left_layout.addLayout(creator_btn_layout)

        left_layout.addStretch()

        # Wrap the left panel in a scroll area so it remains usable
        # on lower screen resolutions without overlapping.
        left_scroll = QScrollArea()
        left_scroll.setWidget(left_widget)
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setStyleSheet(
            "QScrollArea { background: transparent; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        layout.addWidget(left_scroll, stretch=2)

        # Right widget
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)

        # Posts to Download Group
        self.post_list_group = QGroupBox()
        self.post_list_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        post_list_layout = QVBoxLayout()

        # Filters get their own box above the post list: they act on the whole
        # creator rather than on the list widget, and keeping them out of the
        # post group leaves that group height for the posts themselves.
        self.filters_group = QGroupBox()
        self.filters_group.setStyleSheet(
            "QGroupBox { color: white; font-weight: bold; padding: 10px; }"
        )
        filters_layout = QVBoxLayout()

        # Inline skip-keywords filter row (above search bar)
        skip_filter_layout = QHBoxLayout()
        skip_filter_layout.setContentsMargins(0, 0, 0, 0)

        self.skip_keywords_label = QLabel(translate("skip_posts_keywords"))
        self.skip_keywords_label.setStyleSheet("color: white;")
        skip_filter_layout.addWidget(self.skip_keywords_label)

        self.skip_keywords_edit = QLineEdit()
        self.skip_keywords_edit.setPlaceholderText(
            translate("skip_posts_keywords_placeholder")
        )
        self.skip_keywords_edit.setStyleSheet(
            scoped("QLineEdit", "padding: 5px; border-radius: 5px;")
        )
        skip_filter_layout.addWidget(self.skip_keywords_edit, stretch=1)

        self.skip_keywords_help_btn = QPushButton(
            qta.icon("fa5s.info-circle", color="#A0C0FF"), ""
        )
        self.skip_keywords_help_btn.setFixedSize(26, 26)
        self.skip_keywords_help_btn.setStyleSheet(
            scoped("QPushButton", "background: #4A5B7A; border-radius: 5px;")
        )
        self.skip_keywords_help_btn.clicked.connect(self.show_skip_keywords_help)
        skip_filter_layout.addWidget(self.skip_keywords_help_btn)

        filters_layout.addLayout(skip_filter_layout)

        # Skip scope toggles row — each toggle is independent (multi-select),
        # so a post is skipped if the keyword matches in ANY enabled scope.
        skip_scope_layout = QHBoxLayout()
        skip_scope_layout.setContentsMargins(0, 0, 0, 0)

        self.skip_scope_label = QLabel(translate("skip_keywords_scope"))
        self.skip_scope_label.setStyleSheet("color: white;")
        skip_scope_layout.addWidget(self.skip_scope_label)

        self._skip_scope_options = [
            ("skip_scope_title_toggle", "title"),
            ("skip_scope_filenames_toggle", "filenames"),
            ("skip_scope_description_toggle", "description"),
            ("skip_scope_tags_toggle", "tags"),
        ]
        self.skip_scope_checkboxes = {}
        for label_key, value in self._skip_scope_options:
            checkbox = QCheckBox(translate(label_key))
            checkbox.setStyleSheet("color: white;")
            checkbox.setChecked(value == "title")  # Title enabled by default
            skip_scope_layout.addWidget(checkbox)
            self.skip_scope_checkboxes[value] = checkbox
        skip_scope_layout.addStretch()

        filters_layout.addLayout(skip_scope_layout)

        file_skip_filter_layout = QHBoxLayout()
        file_skip_filter_layout.setContentsMargins(0, 0, 0, 0)

        self.file_skip_keywords_label = QLabel(translate("skip_files_keywords"))
        self.file_skip_keywords_label.setStyleSheet("color: white;")
        file_skip_filter_layout.addWidget(self.file_skip_keywords_label)

        self.file_skip_keywords_edit = QLineEdit()
        self.file_skip_keywords_edit.setPlaceholderText(
            translate("skip_files_keywords_placeholder")
        )
        self.file_skip_keywords_edit.setStyleSheet(
            scoped("QLineEdit", "padding: 5px; border-radius: 5px;")
        )
        file_skip_filter_layout.addWidget(self.file_skip_keywords_edit, stretch=1)

        self.file_skip_keywords_help_btn = QPushButton(
            qta.icon("fa5s.info-circle", color="#A0C0FF"), ""
        )
        self.file_skip_keywords_help_btn.setFixedSize(26, 26)
        self.file_skip_keywords_help_btn.setStyleSheet(
            scoped("QPushButton", "background: #4A5B7A; border-radius: 5px;")
        )
        self.file_skip_keywords_help_btn.clicked.connect(
            self.show_file_skip_keywords_help
        )
        file_skip_filter_layout.addWidget(self.file_skip_keywords_help_btn)

        filters_layout.addLayout(file_skip_filter_layout)

        # Post date range filter — "From"/"To" bounds (both optional,
        # both inclusive). Filters by the post's own publish date, not
        # the import/scrape date.
        date_range_layout = QHBoxLayout()
        date_range_layout.setContentsMargins(0, 0, 0, 0)

        self.date_range_label = QLabel(translate("date_range_filter"))
        self.date_range_label.setStyleSheet("color: white;")
        date_range_layout.addWidget(self.date_range_label)

        self.date_from_label = QLabel(translate("date_range_from"))
        self.date_from_label.setStyleSheet("color: white;")
        date_range_layout.addWidget(self.date_from_label)

        self.date_from_edit = QLineEdit()
        self.date_from_edit.setPlaceholderText(translate("date_range_from_placeholder"))
        self.date_from_edit.setStyleSheet(
            scoped("QLineEdit", "padding: 5px; border-radius: 5px;")
        )
        date_range_layout.addWidget(self.date_from_edit, stretch=1)

        self.date_to_label = QLabel(translate("date_range_to"))
        self.date_to_label.setStyleSheet("color: white;")
        date_range_layout.addWidget(self.date_to_label)

        self.date_to_edit = QLineEdit()
        self.date_to_edit.setPlaceholderText(translate("date_range_to_placeholder"))
        self.date_to_edit.setStyleSheet(
            scoped("QLineEdit", "padding: 5px; border-radius: 5px;")
        )
        date_range_layout.addWidget(self.date_to_edit, stretch=1)

        self.date_filter_help_btn = QPushButton(
            qta.icon("fa5s.info-circle", color="#A0C0FF"), ""
        )
        self.date_filter_help_btn.setFixedSize(26, 26)
        self.date_filter_help_btn.setStyleSheet(
            scoped("QPushButton", "background: #4A5B7A; border-radius: 5px;")
        )
        self.date_filter_help_btn.clicked.connect(self.show_date_filter_help)
        date_range_layout.addWidget(self.date_filter_help_btn)

        filters_layout.addLayout(date_range_layout)

        # Post file-count range filter — "From"/"To" bounds on how many files
        # a post holds (main file + attachments + content images). Both bounds
        # are optional and inclusive. "Keep Archives" always keeps posts that
        # contain a ZIP/7Z/RAR, whatever their count.
        file_count_layout = QHBoxLayout()
        file_count_layout.setContentsMargins(0, 0, 0, 0)

        self.file_count_label = QLabel(translate("file_count_filter"))
        self.file_count_label.setStyleSheet("color: white;")
        file_count_layout.addWidget(self.file_count_label)

        self.file_count_from_edit = QLineEdit()
        self.file_count_from_edit.setPlaceholderText(
            translate("file_count_from_placeholder")
        )
        self.file_count_from_edit.setStyleSheet(
            scoped("QLineEdit", "padding: 5px; border-radius: 5px;")
        )
        file_count_layout.addWidget(self.file_count_from_edit, stretch=1)

        self.file_count_to_label = QLabel(translate("file_count_to"))
        self.file_count_to_label.setStyleSheet("color: white;")
        file_count_layout.addWidget(self.file_count_to_label)

        self.file_count_to_edit = QLineEdit()
        self.file_count_to_edit.setPlaceholderText(
            translate("file_count_to_placeholder")
        )
        self.file_count_to_edit.setStyleSheet(
            scoped("QLineEdit", "padding: 5px; border-radius: 5px;")
        )
        file_count_layout.addWidget(self.file_count_to_edit, stretch=1)

        self.file_count_keep_compressed_check = QCheckBox(
            translate("file_count_keep_compressed")
        )
        self.file_count_keep_compressed_check.setChecked(False)
        self.file_count_keep_compressed_check.setStyleSheet("color: white;")
        file_count_layout.addWidget(self.file_count_keep_compressed_check)

        self.file_count_help_btn = QPushButton(
            qta.icon("fa5s.info-circle", color="#A0C0FF"), ""
        )
        self.file_count_help_btn.setFixedSize(26, 26)
        self.file_count_help_btn.setStyleSheet(
            scoped("QPushButton", "background: #4A5B7A; border-radius: 5px;")
        )
        self.file_count_help_btn.clicked.connect(self.show_file_count_help)
        file_count_layout.addWidget(self.file_count_help_btn)

        filters_layout.addLayout(file_count_layout)

        # The post-level partner of the File Extensions grid: the grid
        # decides which files come out of a post, this decides whether a
        # post holding none of those types is listed at all.
        filetype_filter_layout = QHBoxLayout()
        filetype_filter_layout.setContentsMargins(0, 0, 0, 0)

        self.filter_no_selected_filetypes_check = QCheckBox()
        self.filter_no_selected_filetypes_check.setChecked(False)
        self.filter_no_selected_filetypes_check.setStyleSheet("color: white;")
        filetype_filter_layout.addWidget(self.filter_no_selected_filetypes_check)

        self.filter_no_selected_filetypes_help_btn = QPushButton(
            qta.icon("fa5s.info-circle", color="#A0C0FF"), ""
        )
        self.filter_no_selected_filetypes_help_btn.setFixedSize(26, 26)
        self.filter_no_selected_filetypes_help_btn.setStyleSheet(
            scoped("QPushButton", "background: #4A5B7A; border-radius: 5px;")
        )
        self.filter_no_selected_filetypes_help_btn.clicked.connect(
            self.show_filter_no_selected_filetypes_help
        )
        filetype_filter_layout.addWidget(self.filter_no_selected_filetypes_help_btn)
        filetype_filter_layout.addStretch()

        filters_layout.addLayout(filetype_filter_layout)

        self.filters_group.setLayout(filters_layout)
        right_layout.addWidget(self.filters_group)

        # "Search by" row — same layout as the skip-keyword "Filter By" row,
        # but it points the search bar at the ticked fields. Toggling a box
        # re-filters the already-loaded list immediately.
        search_scope_layout = QHBoxLayout()
        search_scope_layout.setContentsMargins(0, 0, 0, 0)

        self.search_scope_label = QLabel(translate("search_scope"))
        self.search_scope_label.setStyleSheet("color: white;")
        search_scope_layout.addWidget(self.search_scope_label)

        self._search_scope_options = [
            ("search_scope_title_toggle", "title"),
            ("search_scope_filenames_toggle", "filenames"),
            ("search_scope_description_toggle", "description"),
            ("search_scope_tags_toggle", "tags"),
        ]
        self.search_scope_checkboxes = {}
        for label_key, value in self._search_scope_options:
            checkbox = QCheckBox(translate(label_key))
            checkbox.setStyleSheet("color: white;")
            checkbox.setChecked(value == "title")  # Title enabled by default
            checkbox.stateChanged.connect(self.filter_items)
            search_scope_layout.addWidget(checkbox)
            self.search_scope_checkboxes[value] = checkbox
        search_scope_layout.addStretch()

        post_list_layout.addLayout(search_scope_layout)

        self.creator_search_input = QLineEdit()
        self.creator_search_input.setStyleSheet(
            scoped("QLineEdit", "padding: 5px; border-radius: 5px;")
        )
        self.creator_search_input.textChanged.connect(self._on_search_text_changed)
        post_list_layout.addWidget(self.creator_search_input)

        checkbox_layout = QHBoxLayout()
        self.creator_check_all = QCheckBox()
        self.creator_check_all.setChecked(False)
        self.creator_check_all.setStyleSheet("color: white;")
        self.creator_check_all.stateChanged.connect(self.toggle_check_all)
        checkbox_layout.addWidget(self.creator_check_all)

        self.creator_check_all_all = QCheckBox()
        self.creator_check_all_all.setChecked(False)
        self.creator_check_all_all.setStyleSheet("color: white;")
        self.creator_check_all_all.stateChanged.connect(self.toggle_check_all_all)
        checkbox_layout.addWidget(self.creator_check_all_all)

        # Info button for the post list itself: outside the list widget but
        # still inside the group, right-aligned so it lines up with the help
        # buttons on the filter rows above.
        checkbox_layout.addStretch()
        self.creator_box_info_btn = QPushButton(
            qta.icon("fa5s.info-circle", color="#A0C0FF"), ""
        )
        self.creator_box_info_btn.setFixedSize(26, 26)
        self.creator_box_info_btn.setStyleSheet(
            scoped("QPushButton", "background: #4A5B7A; border-radius: 5px;")
        )
        self.creator_box_info_btn.clicked.connect(self.show_downloader_box_info)
        checkbox_layout.addWidget(self.creator_box_info_btn)

        post_list_layout.addLayout(checkbox_layout)

        # Explains an empty list that is empty because of the filters, not
        # because the creator has nothing.
        self.creator_post_empty_label = QLabel()
        self.creator_post_empty_label.setStyleSheet("color: #8FA6C8;")
        # Centred: it stands in for the list when every post is filtered out.
        self.creator_post_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.creator_post_empty_label.setVisible(False)
        post_list_layout.addWidget(self.creator_post_empty_label)

        self.creator_post_list = QListWidget()
        self.creator_post_list.setStyleSheet("background: #2A3B5A; border-radius: 5px;")
        self.creator_post_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.creator_post_list.itemSelectionChanged.connect(self.on_selection_changed)
        # Double-clicking a row previews that post's thumbnail, replacing the
        # old eye button.  Both wirings call the same handler: the per-row
        # widget handler catches clicks landing on the row's own children,
        # this one catches anything that reaches the view.
        self.creator_post_list.itemDoubleClicked.connect(self.preview_post)
        post_list_layout.addWidget(self.creator_post_list)

        # Counters row: the post count on the left, with the creator-level
        # "Last Downloaded from Creator" date centred in the space to its
        # right and held well clear of the count by expanding spacers.
        bottom_layout = QHBoxLayout()
        self.creator_post_count_label = QLabel()
        self.creator_post_count_label.setStyleSheet("color: white;")
        bottom_layout.addWidget(self.creator_post_count_label)

        bottom_layout.addStretch()
        self.creator_last_download_label = QLabel()
        self.creator_last_download_label.setStyleSheet("color: white;")
        self.creator_last_download_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bottom_layout.addWidget(self.creator_last_download_label)
        bottom_layout.addStretch()

        post_list_layout.addLayout(bottom_layout)

        # Pagination controls sit on their own row below the counters.
        controls_layout = QHBoxLayout()
        self.page_label = QLabel()
        self.page_label.setStyleSheet("color: white;")
        controls_layout.addWidget(self.page_label)

        self.prev_page_btn = QPushButton(
            qta.icon("fa5s.chevron-left", color="white"), ""
        )
        self.prev_page_btn.setStyleSheet(
            scoped(
                "QPushButton",
                "background: #4A5B7A; padding: 2px; border-radius: 5px; "
                "min-width: 30px; max-width: 30px; min-height: 30px; "
                "max-height: 30px;",
            )
        )
        self.prev_page_btn.clicked.connect(self.prev_page)
        self.prev_page_btn.setEnabled(False)
        controls_layout.addWidget(self.prev_page_btn)

        self.next_page_btn = QPushButton(
            qta.icon("fa5s.chevron-right", color="white"), ""
        )
        self.next_page_btn.setStyleSheet(
            scoped(
                "QPushButton",
                "background: #4A5B7A; padding: 2px; border-radius: 5px; "
                "min-width: 30px; max-width: 30px; min-height: 30px; "
                "max-height: 30px;",
            )
        )
        self.next_page_btn.clicked.connect(self.next_page)
        self.next_page_btn.setEnabled(False)
        controls_layout.addWidget(self.next_page_btn)

        controls_layout.addStretch()

        post_list_layout.addLayout(controls_layout)
        self.post_list_group.setLayout(post_list_layout)
        right_layout.addWidget(self.post_list_group, stretch=1)

        # Background task indicators
        self.background_task_label = QLabel()
        self.background_task_label.setStyleSheet("color: white;")
        right_layout.addWidget(self.background_task_label)

        self.background_task_progress = QProgressBar()
        self.background_task_progress.setStyleSheet(
            "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; background: #2A3B5A; } QProgressBar::chunk { background: #4A5B7A; }"
        )
        self.background_task_progress.setRange(0, 100)
        self.background_task_progress.setValue(0)
        right_layout.addWidget(self.background_task_progress)

        # Log + config row: the log button opens the full log window (there is
        # no inline console any more), and the two config buttons save the
        # page's options and filters as profiles. A plain row, not a group box:
        # the box's title and border clipped the buttons on narrow windows.
        self.log_config_group = QWidget()
        log_config_layout = QHBoxLayout(self.log_config_group)
        log_config_layout.setContentsMargins(0, 0, 0, 0)

        self.creator_log_btn = QPushButton(
            qta.icon("fa5s.chevron-right", color="white"), ""
        )
        self.creator_log_btn.clicked.connect(self.open_logs)
        self.creator_log_btn.setStyleSheet(_TOOL_BUTTON_STYLE)
        log_config_layout.addWidget(self.creator_log_btn)

        # Saved page state, first for every creator, then for this one only.
        self.creator_save_config_btn = QPushButton(
            qta.icon("fa5s.save", color="white"), ""
        )
        self.creator_save_config_btn.clicked.connect(self.save_page_config)
        self.creator_save_config_btn.setStyleSheet(_TOOL_BUTTON_STYLE)
        log_config_layout.addWidget(self.creator_save_config_btn)

        self.creator_save_creator_config_btn = QPushButton(
            qta.icon("fa5s.user-shield", color="white"), ""
        )
        self.creator_save_creator_config_btn.clicked.connect(self.save_creator_config)
        self.creator_save_creator_config_btn.setStyleSheet(_TOOL_BUTTON_STYLE)
        # Nothing to attach a creator profile to until a creator is loaded.
        self.creator_save_creator_config_btn.setEnabled(False)
        log_config_layout.addWidget(self.creator_save_creator_config_btn)

        log_config_layout.addStretch()

        right_layout.addWidget(self.log_config_group)

        layout.addWidget(right_widget, stretch=1)

        # Button hover animations
        if self._parent:
            self.creator_download_btn.enterEvent = (
                lambda *a, **k: self._parent.animate_button(
                    self.creator_download_btn, True
                )
            )
            self.creator_download_btn.leaveEvent = (
                lambda *a, **k: self._parent.animate_button(
                    self.creator_download_btn, False
                )
            )
            self.creator_cancel_btn.enterEvent = (
                lambda *a, **k: self._parent.animate_button(
                    self.creator_cancel_btn, True
                )
            )
            self.creator_cancel_btn.leaveEvent = (
                lambda *a, **k: self._parent.animate_button(
                    self.creator_cancel_btn, False
                )
            )

        # Initial text update
        self.update_ui_text()
        # Lay the extension boxes out once the widgets exist, so a persisted
        # "on" filter starts empty instead of showing every type.
        self._render_creator_ext_checks()

        # Connect the live filters last: every widget they read now exists.
        self._connect_live_filters()

    def update_ui_text(self):
        self.creator_queue_input.setPlaceholderText(
            translate("creator_queue_input_placeholder")
        )
        self.creator_queue_input.setToolTip(translate("creator_queue_input_tooltip"))
        self.creator_queue_input_btn.setToolTip(
            translate("add_creator_and_load_tooltip")
        )

        self.creator_queue_group.setTitle(translate("creator_queue"))
        self.creator_options_group.setTitle(translate("download_options"))
        self.creator_ext_group.setTitle(translate("file_extensions"))
        self.creator_ext_empty_label.setText(
            translate("supported_filetypes_not_present")
        )
        self.creator_post_empty_label.setText(translate("no_posts_match_filters"))
        self.run_summary_group.setTitle(translate("run_summary"))
        self.post_list_group.setTitle(translate("posts_to_download"))
        self.filters_group.setTitle(translate("filters_group_title"))

        self.creator_main_check.setText(translate("main_file"))
        self.creator_attachments_check.setText(translate("attachments"))
        self.creator_content_check.setText(translate("content_images"))
        self.creator_check_all.setText(translate("check_all"))
        self.creator_check_all_all.setText(translate("check_all_all"))
        self.creator_skip_folder_info_btn.setToolTip(
            translate("skip_folder_info_title")
        )
        self.skip_keywords_help_btn.setToolTip(
            translate("skip_posts_keywords_help_title")
        )
        self.file_skip_keywords_help_btn.setToolTip(
            translate("skip_files_keywords_help_title")
        )
        self.date_filter_help_btn.setToolTip(translate("date_filter_help_title"))
        self.creator_box_info_btn.setToolTip(translate("downloader_box_info_title"))
        self.creator_force_compressed_folder_check.setToolTip(
            translate("force_folder_for_compressed")
        )
        self.creator_skip_images_check.setText(translate("skip_images_if_compressed"))
        self.creator_skip_images_info_btn.setToolTip(
            translate("skip_images_info_title")
        )
        self.file_count_help_btn.setToolTip(translate("file_count_help_title"))
        self.file_count_label.setText(translate("file_count_filter"))
        self.file_count_from_edit.setPlaceholderText(
            translate("file_count_from_placeholder")
        )
        self.file_count_to_label.setText(translate("file_count_to"))
        self.file_count_to_edit.setPlaceholderText(
            translate("file_count_to_placeholder")
        )
        self.file_count_keep_compressed_check.setText(
            translate("file_count_keep_compressed")
        )
        self.filter_no_selected_filetypes_check.setText(
            translate("filter_no_selected_filetypes")
        )
        self.search_scope_label.setText(translate("search_scope"))

        self.creator_file_progress_label.setText(translate("file_progress", 0))
        self.creator_overall_progress_label.setText(
            translate("overall_progress", 0, 0, 0, 0)
        )
        self.creator_post_count_label.setText(
            translate("posts_count", len(self.posts_to_download))
        )
        self._update_last_download_label()
        self.background_task_label.setText(translate("idle"))

        self.creator_download_btn.setText(translate("download"))
        self.creator_cancel_btn.setText(translate("cancel"))
        self.creator_save_config_btn.setText(translate("save_config_btn"))
        self.creator_save_config_btn.setToolTip(translate("save_config_btn_tooltip"))
        self.creator_save_creator_config_btn.setText(
            translate("save_creator_config_btn")
        )
        self.creator_save_creator_config_btn.setToolTip(
            translate("save_creator_config_btn_tooltip")
        )
        self._refresh_retry_button()
        self._refresh_open_folder_button()
        self._refresh_config_buttons()
        self._update_download_summary()
        self._update_log_button_text()

        self.creator_search_input.setPlaceholderText(translate("search_posts"))

        # Update inline skip-keywords filter labels
        self.skip_keywords_label.setText(translate("skip_posts_keywords"))
        self.skip_keywords_edit.setPlaceholderText(
            translate("skip_posts_keywords_placeholder")
        )
        self.skip_scope_label.setText(translate("skip_keywords_scope"))
        self.file_skip_keywords_label.setText(translate("skip_files_keywords"))
        self.file_skip_keywords_edit.setPlaceholderText(
            translate("skip_files_keywords_placeholder")
        )
        for label_key, value in self._skip_scope_options:
            checkbox = self.skip_scope_checkboxes.get(value)
            if checkbox is not None:
                checkbox.setText(translate(label_key))
        for label_key, value in self._search_scope_options:
            checkbox = self.search_scope_checkboxes.get(value)
            if checkbox is not None:
                checkbox.setText(translate(label_key))

        self.update_creator_queue_list()

    def update_progress_bar_style(self):
        separator_style = "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; background: #2A3B5A; } QProgressBar::chunk { background: #4A5B7A; }"
        self.creator_file_progress.setStyleSheet(separator_style)
        self.creator_overall_progress.setStyleSheet(separator_style)
        self.background_task_progress.setStyleSheet(separator_style)

    def refresh_ui(self):
        """Re-apply the visual state after settings change.

        The counters reset, but the last run's failures and the post-list skip
        counts are kept: applying a setting is not a new run, and losing them
        would grey out Retry Failed Downloads for no reason.
        """
        self.update_progress_bar_style()
        if not self.downloading:
            self.creator_file_progress.setValue(0)
            self.creator_file_progress_label.setText(translate("file_progress", 0))
            self.creator_overall_progress.setValue(0)
            self.creator_overall_progress_label.setText(
                translate("overall_progress", 0, 0, 0, 0)
            )
            self.current_file_index = -1
            self.completed_posts.clear()
            self.completed_files.clear()
            self.total_files_to_download = 0
            self._reset_download_summary(keep_post_stats=True, keep_run_failures=True)
            self.background_task_progress.setRange(0, 100)
            self.background_task_progress.setValue(0)
            self.background_task_label.setText(translate("idle"))

    # ------------------------------------------------------------------
    # Page config profiles ("Save Config" / "Save Creator Config")
    #
    # A profile is the page's options and post filters, never its post ticks:
    # ticks are a momentary choice, and a stored selection would only be a
    # list of post ids that may not exist any more. The default profile is
    # applied when the tab is built; a creator profile replaces it wholesale
    # whenever that creator is loaded, so switching creators is a switch
    # between two independent profiles rather than a merge of them.
    # ------------------------------------------------------------------

    def _open_store(self, factory, instance_attr, dir_attr, failed_attr, label):
        """Open a SQLite store once per "Other Files" folder, or None.

        Nothing is opened in ``__init__``, so constructing the tab never
        touches the disk. A failed open is remembered (and logged once) so it
        is not retried on every save or row render.
        """
        if not self.other_files_dir:
            return None
        if getattr(self, dir_attr) == self.other_files_dir:
            return getattr(self, instance_attr)
        if getattr(self, failed_attr) == self.other_files_dir:
            return None
        try:
            instance = factory(self.other_files_dir)
            setattr(self, instance_attr, instance)
            setattr(self, dir_attr, self.other_files_dir)
            setattr(self, failed_attr, None)
            return instance
        except Exception as e:
            setattr(self, instance_attr, None)
            setattr(self, failed_attr, self.other_files_dir)
            self.append_log_to_console(
                translate("log_warning", f"{label}: {e}"), "WARNING"
            )
            return None

    def _config_store(self):
        """Return the profile store, or None when it cannot be opened."""
        return self._open_store(
            CreatorConfigStore,
            "_config_store_instance",
            "_config_store_dir",
            "_config_store_failed_dir",
            "Saved configs unavailable",
        )

    def _config_snapshot(self):
        """Return the page's options and filters as a JSON-ready dict.

        Reads the widgets only, so it is safe to call at any point in the
        page's life — including at startup, before anything is loaded.
        """
        return {
            "options": {
                "main": self.creator_main_check.isChecked(),
                "attachments": self.creator_attachments_check.isChecked(),
                "content": self.creator_content_check.isChecked(),
                "download_text": self.creator_download_text_check.isChecked(),
                "skip_folder": self.creator_skip_folder_check.isChecked(),
                "skip_folder_max": int(
                    self.creator_skip_folder_combo.currentData()
                    or (self.creator_skip_folder_combo.currentIndex() + 1)
                ),
                "force_compressed_folder": (
                    self.creator_force_compressed_folder_check.isChecked()
                ),
                "skip_images_if_compressed": (
                    self.creator_skip_images_check.isChecked()
                ),
                "filetypes": self._selected_extensions(),
            },
            "filters": {
                "skip_keywords": self.skip_keywords_edit.text(),
                "skip_scopes": sorted(
                    scope
                    for scope, box in self.skip_scope_checkboxes.items()
                    if box.isChecked()
                ),
                "file_skip_keywords": self.file_skip_keywords_edit.text(),
                "date_from": self.date_from_edit.text(),
                "date_to": self.date_to_edit.text(),
                "file_count_from": self.file_count_from_edit.text(),
                "file_count_to": self.file_count_to_edit.text(),
                "keep_compressed": (self.file_count_keep_compressed_check.isChecked()),
                "filter_no_selected_filetypes": (
                    self.filter_no_selected_filetypes_check.isChecked()
                ),
            },
            "search_scopes": sorted(
                scope
                for scope, box in self.search_scope_checkboxes.items()
                if box.isChecked()
            ),
        }

    @staticmethod
    def _set_config_checkbox(checkbox, value):
        """Set a tick without firing the live-filter pass behind it."""
        checkbox.blockSignals(True)
        checkbox.setChecked(bool(value))
        checkbox.blockSignals(False)

    @staticmethod
    def _set_config_text(editor, value):
        """Set a filter field without starting a debounced filter pass."""
        editor.blockSignals(True)
        editor.setText("" if value is None else str(value))
        editor.blockSignals(False)

    def _set_config_scopes(self, checkboxes, values):
        """Tick exactly the named scopes of a ``{scope: checkbox}`` mapping."""
        wanted = {str(value) for value in (values or ())}
        for scope, checkbox in checkboxes.items():
            self._set_config_checkbox(checkbox, scope in wanted)

    def _apply_config(self, config):
        """Apply a profile to the page's widgets.

        Signals are blocked on every widget written, so restoring six filter
        fields cannot fire six filter passes; one pass runs at the end when a
        post list is already loaded. A key the profile does not contain is
        left alone, so a profile written by an older version only restores
        what it actually describes.
        """
        if not config:
            return
        options = config.get("options") or {}
        filters = config.get("filters") or {}

        ticks = (
            ("main", self.creator_main_check),
            ("attachments", self.creator_attachments_check),
            ("content", self.creator_content_check),
            ("download_text", self.creator_download_text_check),
            ("skip_folder", self.creator_skip_folder_check),
            ("force_compressed_folder", self.creator_force_compressed_folder_check),
            ("skip_images_if_compressed", self.creator_skip_images_check),
        )
        for key, checkbox in ticks:
            if key in options:
                self._set_config_checkbox(checkbox, options[key])

        if "skip_folder_max" in options:
            try:
                wanted = int(options["skip_folder_max"])
            except (TypeError, ValueError):
                wanted = 1
            index = self.creator_skip_folder_combo.findData(wanted)
            self.creator_skip_folder_combo.blockSignals(True)
            self.creator_skip_folder_combo.setCurrentIndex(index if index >= 0 else 0)
            self.creator_skip_folder_combo.blockSignals(False)

        if "filetypes" in options:
            wanted_types = {
                str(ext).lower() for ext in (options.get("filetypes") or ())
            }
            for ext, checkbox in self.creator_ext_checks.items():
                self._set_config_checkbox(checkbox, ext in wanted_types)

        text_fields = (
            ("skip_keywords", self.skip_keywords_edit),
            ("file_skip_keywords", self.file_skip_keywords_edit),
            ("date_from", self.date_from_edit),
            ("date_to", self.date_to_edit),
            ("file_count_from", self.file_count_from_edit),
            ("file_count_to", self.file_count_to_edit),
        )
        for key, editor in text_fields:
            if key in filters:
                self._set_config_text(editor, filters[key])

        if "skip_scopes" in filters:
            self._set_config_scopes(self.skip_scope_checkboxes, filters["skip_scopes"])
        if "keep_compressed" in filters:
            self._set_config_checkbox(
                self.file_count_keep_compressed_check, filters["keep_compressed"]
            )
        if "filter_no_selected_filetypes" in filters:
            self._set_config_checkbox(
                self.filter_no_selected_filetypes_check,
                filters["filter_no_selected_filetypes"],
            )
        if "search_scopes" in config:
            self._set_config_scopes(
                self.search_scope_checkboxes, config["search_scopes"]
            )

        # A restored filetype tick has to stay visible even when only the
        # types this creator has are shown.
        self._render_creator_ext_checks()
        if self.all_detected_posts:
            self.filter_items()

    def _load_page_config(self):
        """Apply the saved default profile, if there is one."""
        store = self._config_store()
        config = None
        if store is not None:
            try:
                config = store.get_page_default()
            except Exception as e:
                self.append_log_to_console(
                    translate("log_warning", translate("config_load_failed", e)),
                    "WARNING",
                )
        self._apply_config(config)

    def _load_config_for_creator(self):
        """Switch the page to the loaded creator's profile, or back to default.

        Called when a creator is loaded, when its view is cleared, and before
        the fetch reads the Filters box, so the restored filters are the ones
        the fetch actually uses. A creator profile replaces the default rather
        than being layered on it; with no creator profile — or with no creator
        loaded at all — the saved default is what the page returns to, and
        with neither the built-in page state is.
        """
        store = self._config_store()
        service, creator_id = self._current_creator_identity()
        config = None
        from_creator = False
        if store is not None:
            if self.current_creator_url:
                try:
                    config = store.get_creator_config(service, creator_id)
                except Exception as e:
                    self.append_log_to_console(
                        translate("log_warning", translate("config_load_failed", e)),
                        "WARNING",
                    )
                if config is not None:
                    from_creator = True
            if not from_creator:
                try:
                    config = store.get_page_default()
                except Exception:
                    config = None
        if from_creator:
            self.append_log_to_console(
                translate("log_info", translate("creator_config_loaded", creator_id)),
                "INFO",
            )
        self._apply_config(config or self._builtin_config)
        self._refresh_config_buttons()

    def _refresh_config_buttons(self):
        """Enable the config buttons when pressing one would mean something.

        "Save Creator Config" needs a creator to attach the profile to. Both
        are off during a run: the download already snapshotted the options it
        is using, so a save now would describe something nothing reads.
        """
        default_btn = getattr(self, "creator_save_config_btn", None)
        creator_btn = getattr(self, "creator_save_creator_config_btn", None)
        if default_btn is None or creator_btn is None:
            return
        busy = bool(getattr(self, "downloading", False)) or self._download_in_progress()
        default_btn.setEnabled(not busy)
        creator_btn.setEnabled(bool(self.current_creator_url) and not busy)

    def _config_warnings(self):
        """Return the translation keys of filter entries a save cannot store."""
        _filters, warnings = self._post_filters_from_widgets()
        return warnings

    def _warn_config_warnings(self, warnings):
        """Name the entries that stopped a save; nothing is stored."""
        lines = "\n".join(translate(key) for key in warnings)
        QMessageBox.warning(
            self,
            translate("config_save_invalid_title"),
            translate("config_save_invalid_text", lines),
        )

    def _store_config(self, payload, service=None, creator_id=None):
        """Write a profile and report the outcome. Returns True on success."""
        warnings = self._config_warnings()
        if warnings:
            self._warn_config_warnings(warnings)
            return False
        for_creator = bool(service) and bool(creator_id)
        if (service is not None or creator_id is not None) and not for_creator:
            # A creator save with no usable identity must never fall through
            # to the page default, and must never claim success: the store
            # refuses such a key, so a success message would be a lie.
            self.append_log_to_console(
                translate("log_warning", translate("config_no_creator_text")),
                "WARNING",
            )
            return False
        store = self._config_store()
        if store is None:
            self.append_log_to_console(
                translate("log_warning", translate("config_unavailable")), "WARNING"
            )
            return False
        try:
            if for_creator:
                store.set_creator_config(service, creator_id, payload)
            else:
                store.set_page_default(payload)
        except Exception as e:
            self.append_log_to_console(
                translate("log_error", translate("config_save_failed", e)), "ERROR"
            )
            return False

        options = len(payload.get("options") or {})
        filters = len(payload.get("filters") or {})
        if for_creator:
            self.append_log_to_console(
                translate(
                    "log_info", translate("creator_config_saved_log", creator_id)
                ),
                "INFO",
            )
            QMessageBox.information(
                self,
                translate("creator_config_saved_title"),
                translate("creator_config_saved_text", options, filters, creator_id),
            )
        else:
            self.append_log_to_console(
                translate("log_info", translate("config_saved_log")), "INFO"
            )
            QMessageBox.information(
                self,
                translate("config_saved_title"),
                translate("config_saved_text", options, filters),
            )
        return True

    def save_page_config(self):
        """Store the page as the default profile for every creator."""
        return self._store_config(self._config_snapshot())

    def save_creator_config(self):
        """Store the page as the loaded creator's profile."""
        if not self.current_creator_url:
            self.append_log_to_console(
                translate("log_warning", translate("config_no_creator_text")),
                "WARNING",
            )
            return False
        service, creator_id = self._current_creator_identity()
        return self._store_config(self._config_snapshot(), service, creator_id)

    # ------------------------------------------------------------------
    # Download history ("last downloaded") tracking
    # ------------------------------------------------------------------

    def _history_db(self):
        """Return the download-history database, or None when unavailable."""
        return self._open_store(
            DownloadHistoryDB,
            "_history_db_instance",
            "_history_db_dir",
            "_history_db_failed_dir",
            "Download history unavailable",
        )

    def _current_creator_identity(self):
        """Return ``(service, creator_id)`` for the creator being viewed."""
        return split_creator_url(self.current_creator_url)

    def _load_creator_history(self):
        """Reload the creator-level date and redraw the label beside the count."""
        self._creator_last_download = None
        db = self._history_db()
        if db is not None and self.current_creator_url:
            try:
                service, creator_id = self._current_creator_identity()
                self._creator_last_download = db.get_creator_time(service, creator_id)
            except Exception:
                self._creator_last_download = None
        self._update_last_download_label()

    def _update_last_download_label(self):
        """Re-text the "Last Downloaded from Creator" label.

        Always visible: "N/A" while no creator is being viewed, "Never" for a
        creator with nothing recorded, otherwise the newest date.
        """
        if not self.current_creator_url:
            value = translate("not_available")
        else:
            value = iso_to_local_date(self._creator_last_download) or translate(
                "never_downloaded"
            )
        self.creator_last_download_label.setText(
            translate("last_downloaded_creator", value)
        )

    def _load_post_history(self):
        """Cache this creator's per-post last-download dates for row rendering."""
        self._post_history_cache = {}
        db = self._history_db()
        if db is None or not self.current_creator_url:
            return
        try:
            service, creator_id = self._current_creator_identity()
            recorded = db.get_post_times(service, creator_id)
        except Exception:
            return
        for post_id, timestamp in recorded.items():
            date_text = iso_to_local_date(timestamp)
            if date_text:
                self._post_history_cache[str(post_id)] = date_text

    @staticmethod
    def _row_label_text(key, download_date):
        """Return a row label, bolding the bracketed last-download date.

        The row switches to rich text only when it has a date to emphasise,
        so the title and date are escaped: a title containing '<' or '&' must
        still render literally.
        """
        if not download_date:
            return key
        return f"{html.escape(str(key))} <b>[{html.escape(str(download_date))}]</b>"

    def refresh_download_history_ui(self):
        """Re-read the history and restamp the visible rows + creator label."""
        self._load_post_history()
        self._load_creator_history()
        for item, widget in self.post_widget_cache.values():
            post_id = item.data(Qt.UserRole + 1)
            key = getattr(widget, "post_key", None)
            if post_id is None or not key or not hasattr(widget, "label"):
                continue
            date_text = self._post_history_cache.get(str(post_id))
            widget.label.setTextFormat(
                Qt.TextFormat.RichText if date_text else Qt.TextFormat.PlainText
            )
            widget.label.setText(self._row_label_text(key, date_text))

    def _show_info(self, title_key, text_key):
        """Show a translated one-paragraph help dialog."""
        QMessageBox.information(self, translate(title_key), translate(text_key))

    def show_downloader_box_info(self):
        """Explain the post rows shown in the downloader box."""
        self._show_info("downloader_box_info_title", "downloader_box_info_text")

    def show_skip_folder_info(self):
        """Show a dialog explaining what Skip Post Folder does."""
        self._show_info("skip_folder_info_title", "skip_folder_info_text")

    def show_skip_images_info(self):
        """Show a dialog explaining what Skip Images if Compressed does."""
        self._show_info("skip_images_info_title", "skip_images_info_text")

    def _queue_creator_url(self, url_text, refresh=True):
        """Queue one creator URL, returning "added", "duplicate" or "invalid".

        Post URLs collapse to their parent creator and remember their post id,
        so a post link still drives the post-link auto-select.
        """
        # Accept both creator and post URLs; post URLs collapse to the parent
        # creator so the queue only ever holds creator URLs.
        normalized_url, post_id = resolve_creator_url(url_text)
        normalized_url = normalized_url.rstrip("/")

        # Validate URL format (same rules as the detection thread)
        parts = normalized_url.split("/")
        domain_config = get_domain_config(normalized_url)
        if (
            len(parts) < 5
            or domain_config["domain"] not in normalized_url
            or parts[-2] != "user"
        ):
            self.append_log_to_console(
                translate("log_warning", translate("invalid_creator_url", url_text)),
                "WARNING",
            )
            return "invalid"

        # A post link means "just this post"; accumulate them so several post
        # links for one creator all get selected. A plain creator link means
        # "everything", so it drops any earlier restriction.
        post_ids_changed = self._remember_batch_post_id(normalized_url, post_id)

        if any(item[0].rstrip("/") == normalized_url for item in self.creator_queue):
            self.append_log_to_console(
                translate("log_warning", translate("url_already_in_queue")),
                "WARNING",
            )
            # A post link for an already-queued creator still adds its tag.
            if refresh and post_ids_changed:
                self.update_creator_queue_list()
            return "duplicate"

        self.creator_queue.append((normalized_url, False))
        # The profile name is a single small request; ask for it straight away
        # so the row reads as a creator name rather than a bare URL.
        self._request_creator_name(normalized_url)
        if refresh:
            self.update_creator_queue_list(scroll=True)
        self.append_log_to_console(
            translate("log_info", translate("added_to_queue") + f": {normalized_url}"),
            "INFO",
        )
        return "added"

    def _queue_input_behavior(self):
        """Which auto-load mode Settings asks the queue's input row for."""
        settings_tab = getattr(self._parent, "settings_tab", None)
        getter = getattr(settings_tab, "get_queue_input_behavior", None)
        return getter() if callable(getter) else "default"

    def add_creator_to_queue(self, auto_load=True):
        """Commit the URL in the queue's blank row, then empty the field.

        Enter and Space both land here. Adding never fetches by itself: the
        Settings mode decides whether the new creator is then opened. The
        row's eye passes ``auto_load=False`` so it can open the creator once,
        itself, without a second fetch from the mode.
        """
        url_text = self.creator_queue_input.text().strip()
        if not url_text:
            self.append_log_to_console(
                translate("log_error", translate("no_url_entered")), "ERROR"
            )
            return "invalid"

        outcome = self._queue_creator_url(url_text)
        if outcome == "invalid":
            # Keep the text so it can be corrected in place.
            return outcome
        # Added or already queued: the URL was understood either way, so the
        # field empties and stays focused for the next one.
        self.creator_queue_input.clear()
        self.creator_queue_input.setFocus()
        if outcome == "added" and auto_load:
            self._auto_load_queued_creator()
        return outcome

    def add_creator_and_load(self):
        """The blank row's eye: add the URL, then open it whatever the mode."""
        url_text = self.creator_queue_input.text().strip()
        normalized_url = ""
        if url_text:
            normalized_url, _post_id = resolve_creator_url(url_text)
            normalized_url = normalized_url.rstrip("/")

        outcome = self.add_creator_to_queue(auto_load=False)
        if outcome == "added":
            self.check_creator_from_queue(self.creator_queue[-1][0])
        elif outcome == "duplicate":
            # Already queued: still honour the explicit "show me this one".
            self.check_creator_from_queue(normalized_url)

    def _auto_load_queued_creator(self):
        """Open the just-queued creator when Settings asks for it.

        "load_first" only opens while nothing is being viewed, so adding more
        links never yanks the page away from the creator being set up.
        "load_every" opens every creator that is added.
        """
        mode = self._queue_input_behavior()
        if mode == "load_every" or (
            mode == "load_first" and not self.current_creator_url
        ):
            # The fetch disables the queue, input row included; hand focus back
            # to it once the fetch finishes so the next URL can be typed. The
            # flag is set from the result so a refused fetch (one already
            # running, a rejected URL) cannot move focus on some later run.
            self._restore_queue_input_focus = self.check_creator_from_queue(
                self.creator_queue[-1][0]
            )

    def _show_queue_context_menu(self, position):
        """Queue context menu: copy a creator's link or import a .txt file."""
        menu = QMenu(self.creator_queue_list)
        menu.setStyleSheet(MENU_STYLE)
        item = self.creator_queue_list.itemAt(position)
        if item is not None:
            url = item.data(Qt.ItemDataRole.UserRole)
            if url:
                copy_action = menu.addAction(translate("copy_link"))
                copy_action.triggered.connect(
                    lambda _checked=False, link=url: self._copy_queue_link(link)
                )
                menu.addSeparator()
        import_action = menu.addAction(translate("add_links_from_file_title"))
        import_action.triggered.connect(self.add_creators_from_file)
        menu.exec(self.creator_queue_list.mapToGlobal(position))
        menu.deleteLater()

    def _copy_queue_link(self, url):
        """Put a queued creator's URL on the clipboard."""
        QApplication.clipboard().setText(url)
        self.append_log_to_console(
            translate("log_info", translate("link_copied", url)), "INFO"
        )

    def _queue_row_text(self, url):
        """Return ``(label_text, use_rich_text)`` for a queued creator row."""
        requested_post_ids = self._batch_post_ids.get(url.rstrip("/"))
        label_text = url
        if requested_post_ids:
            ids = ", ".join(sorted(str(p) for p in requested_post_ids))
            label_text = f"{url} ({translate('batch_post_link_tag', ids)})"
        creator_name = self._creator_names.get(url.rstrip("/"))
        if creator_name:
            # The name arrives once the creator's profile has been read;
            # bolding it mirrors the last-download date on the post rows, and
            # escaping keeps a name containing markup literal.
            return (
                f"{html.escape(label_text)} " f"<b>[{html.escape(creator_name)}]</b>",
                True,
            )
        return label_text, False

    def _refresh_queue_row(self, url):
        """Update one queue row's label in place; a name just arrived.

        Rebuilding the whole list for a single name costs ~70 ms at 100
        creators and would reset the queue's selection, so only the matching
        label is rewritten.
        """
        key = (url or "").rstrip("/")
        for index in range(self.creator_queue_list.count()):
            item = self.creator_queue_list.item(index)
            item_url = item.data(Qt.ItemDataRole.UserRole)
            if (item_url or "").rstrip("/") != key:
                continue
            widget = self.creator_queue_list.itemWidget(item)
            if widget is None:
                return
            text, rich = self._queue_row_text(item_url)
            widget.label.setTextFormat(
                Qt.TextFormat.RichText if rich else Qt.TextFormat.PlainText
            )
            widget.label.setText(text)
            item.setSizeHint(widget.sizeHint())
            return

    def on_creator_name_found(self, url, name):
        """Cache a creator's display name and refresh its queue row."""
        key = (url or "").rstrip("/")
        name = (name or "").strip()
        if not key or not name or self._creator_names.get(key) == name:
            return
        self._creator_names[key] = name
        self._refresh_queue_row(key)

    def _request_creator_name(self, creator_url):
        """Ask for a queued creator's name, once per URL."""
        key = (creator_url or "").rstrip("/")
        if not key or key in self._creator_names or key in self._name_lookup_wanted:
            return
        self._name_lookup_wanted.add(key)
        self._name_lookup_pending.append(key)
        self._start_name_lookups()

    def _start_name_lookups(self):
        """Start queued name lookups, up to the concurrency cap."""
        while (
            self._name_lookup_pending
            and len(self._name_lookup_threads) < CREATOR_NAME_LOOKUP_CONCURRENCY
        ):
            url = self._name_lookup_pending.pop(0)
            thread = CreatorNameLookupThread(
                url, getattr(self._parent, "settings_tab", None)
            )
            thread.found.connect(self.on_creator_name_found)
            thread.finished.connect(self._on_name_lookup_finished)
            self._name_lookup_threads[url] = thread
            thread.start()

    def stop_name_lookups(self):
        """Stop pending and active profile lookups (the window is closing).

        Lookup threads are deliberately not part of ``active_threads``: that
        list belongs to a download run, and a cancelled run must not delete a
        name lookup and leave a dead entry holding one of the concurrency
        slots.
        """
        self._name_lookup_pending.clear()
        self._name_lookup_wanted.clear()
        for thread in list(self._name_lookup_threads.values()):
            try:
                thread.stop()
            except RuntimeError:
                pass

    def _on_name_lookup_finished(self):
        """Drop a finished lookup and start the next queued one."""
        thread = self.sender()
        if thread is None:
            return
        url = (getattr(thread, "creator_url", "") or "").rstrip("/")
        if self._name_lookup_threads.get(url) is thread:
            self._name_lookup_threads.pop(url, None)
        self._name_lookup_wanted.discard(url)
        if thread in self.active_threads:
            self.active_threads.remove(thread)
        thread.deleteLater()
        self._start_name_lookups()

    def create_view_handler(self, url, checked):
        def handler():
            self.check_creator_from_queue(url)

        return handler

    def create_remove_handler(self, url):
        def handler():
            reply = QMessageBox.question(
                self,
                translate("confirm_removal"),
                translate("confirm_removal_message", url),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                found = False
                for i, (queue_url, _) in enumerate(self.creator_queue):
                    if queue_url == url:
                        del self.creator_queue[i]
                        found = True
                        break
                if found:
                    self._batch_post_ids.pop(url.rstrip("/"), None)
                    self.update_creator_queue_list()
                    self.append_log_to_console(
                        translate("log_info", translate("link_removed", url)), "INFO"
                    )
                    # Clear the view only when the creator being viewed is the
                    # one that was removed. Removing a different link used to
                    # clear (or keep) the list based on the queue's processed
                    # flags, which left a removed creator's posts on screen and
                    # downloadable.
                    if url.rstrip("/") == (self.current_creator_url or "").rstrip("/"):
                        self.creator_post_list.clear()
                        self.post_widget_cache.clear()
                        self.all_detected_posts = []
                        self.posts_to_download = []
                        self.post_url_map = {}
                        self.checked_urls = {}
                        self.all_files_map = {}
                        self._clear_preview_caches()
                        self.current_creator_url = None
                        self._clear_filetype_selection()
                        self._reset_found_extensions()
                        # The creator's saved profile goes with it: hand every
                        # option and filter back to the page default.
                        self._load_config_for_creator()
                        self.update_checked_posts()
                        self.filter_items()
                else:
                    self.append_log_to_console(
                        translate("log_warning", translate("url_not_found", url)),
                        "WARNING",
                    )

        return handler

    def update_creator_queue_list(self, scroll=False):
        """Rebuild the queue rows.

        A rebuild that is not revealing a new entry keeps the queue's own
        scroll position, so a name arriving mid-browse does not jump the list
        back to the top.
        """
        queue_scroll = None
        if not scroll:
            queue_scroll = self.creator_queue_list.verticalScrollBar().value()
        self.creator_queue_list.clear()
        for url, checked in self.creator_queue:
            item = QListWidgetItem()
            # Double-clicking the row (its URL, its gaps) loads the creator;
            # the eye and the ✕ stay one-click buttons of their own.
            widget = _CreatorQueueRow(lambda u=url: self.check_creator_from_queue(u))
            layout = QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)

            view_button = QPushButton(qta.icon("fa5s.eye", color="white"), "")
            view_button.setStyleSheet(
                scoped(
                    "QPushButton",
                    "background: #4A5B7A; padding: 2px; border-radius: 5px; "
                    "min-width: 30px; max-width: 30px; min-height: 30px; "
                    "max-height: 30px;",
                )
            )
            view_button.clicked.connect(self.create_view_handler(url, checked))
            layout.addWidget(view_button)

            # The URL, its post-link tag and the creator's name (once known) are
            # built by one helper so an in-place name refresh cannot drift from
            # a full rebuild.
            label_text, rich_label = self._queue_row_text(url)
            label = QLabel()
            label.setTextFormat(
                Qt.TextFormat.RichText if rich_label else Qt.TextFormat.PlainText
            )
            label.setText(label_text)
            # The window's stylesheet paints every descendant, which put a dark
            # band over the row's selection highlight; a transparent label lets
            # the highlight show through.
            label.setStyleSheet("color: white; background: transparent;")
            label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            # The label is decoration: let double-clicks fall through to the
            # row widget instead of being swallowed by the text.
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(label, stretch=1)

            remove_button = QPushButton(qta.icon("fa5s.times", color="white"), "")
            remove_button.setStyleSheet(
                scoped(
                    "QPushButton",
                    "background: #4A5B7A; padding: 2px; border-radius: 5px; "
                    "min-width: 30px; max-width: 30px; min-height: 30px; "
                    "max-height: 30px;",
                )
            )
            remove_button.clicked.connect(self.create_remove_handler(url))
            layout.addWidget(remove_button)

            widget.setLayout(layout)
            item.setSizeHint(widget.sizeHint())
            # The URL rides on the item so the context menu can copy the link
            # that was right-clicked, even though the row is a child widget.
            item.setData(Qt.ItemDataRole.UserRole, url)
            self.creator_queue_list.addItem(item)
            self.creator_queue_list.setItemWidget(item, widget)
            setattr(widget, "view_button", view_button)
            setattr(widget, "label", label)
            setattr(widget, "remove_button", remove_button)

        if scroll:
            # The newest creator is appended, so it sits directly above the
            # input row. Bring it into view.
            self.creator_queue_list.scrollToBottom()
        elif queue_scroll:
            self.creator_queue_list.verticalScrollBar().setValue(queue_scroll)

    def check_creator_from_queue(self, url):
        """Open a queued creator; return True when a fetch actually started."""
        if not isinstance(url, str):
            self.append_log_to_console(
                translate("log_error", translate("invalid_url_type", type(url))),
                "ERROR",
            )
            return False
        # Refuse before touching any state: this used to clear the whole view
        # first and only then discover a fetch was still running, which left an
        # empty list with the old fetch still writing into it.
        if (
            getattr(self, "post_detection_thread", None) is not None
            and self.post_detection_thread.isRunning()
        ):
            self.append_log_to_console(
                translate("log_warning", translate("post_detection_in_progress")),
                "WARNING",
            )
            return False
        self.append_log_to_console(
            translate("log_info", translate("viewing_creator", url)), "INFO"
        )

        previous_creator_url = self.current_creator_url
        self.current_creator_url = url
        if (previous_creator_url or "").rstrip("/") != str(url).rstrip("/"):
            # Preview caches describe one creator's posts; holding them after
            # switching wastes memory and could show stale records.  Clear the
            # shared thumbnail LRU and the post records together.
            self._clear_preview_caches()
        self.checked_urls.clear()
        self.posts_to_download = []
        self._post_link_selection_pending = False
        self.filtered_posts = []  # Clear filtered posts cache
        self.all_detected_posts = []  # Clear previous creator's posts
        self.post_url_map = {}  # Clear previous creator's post URL mapping
        self.post_dates_map = {}  # Clear previous creator's post dates
        self.post_search_index = {}  # Clear previous creator's search index
        # A refetch of the same creator must not append to the cached copy of
        # its previous fetch (on_posts_batch_received replaces it on the first
        # batch instead).
        self._fetch_batches_started = False
        self._reset_found_extensions()
        # Switch to this creator's saved profile (or back to the default)
        # before the fetch reads the Filters box below, so the fetch uses the
        # restored filters rather than whatever the previous page left behind.
        self._load_config_for_creator()
        # The skip breakdown describes one creator's posts, so start it at
        # zero instead of showing the previous creator's numbers until the
        # first filter pass of the new one lands.
        self._post_skip_stats = {
            "keywords": 0,
            "date": 0,
            "file_count": 0,
            "filetypes": 0,
        }
        self._post_keyword_skip_counts = {}
        self._skip_summary_cache = None
        self._update_download_summary(refresh_skips=True)
        self.current_page = 1  # Reset pagination
        self.total_pages = 1
        # A saved search position belongs to the creator that was open.
        self._search_return_position = None
        self._pending_filter_scroll = None

        # Switch the download-history tracking over to this creator.  Doing it
        # here (rather than only after the posts arrive) means the creator's
        # date shows up even before the post list is populated.
        self._load_creator_history()
        self._load_post_history()

        self.creator_post_list.clear()
        self.post_widget_cache.clear()
        empty_label = getattr(self, "creator_post_empty_label", None)
        if empty_label is not None:
            empty_label.setVisible(False)
        self.update_pagination_controls()  # Reset pagination UI

        # Reset queue status to allow refetching
        for i, (queue_url, _) in enumerate(self.creator_queue):
            if queue_url == url:
                self.creator_queue[i] = (url, False)  # Mark as not processed
                self.update_creator_queue_list()
                break

        # Always attempt to fetch/refetch posts when viewing a creator
        # This allows users to refresh the post list even if already cached
        self.background_task_label.setText(translate("detecting_posts"))
        self.background_task_progress.setRange(0, 0)

        # Disable UI elements during fetching
        self.set_fetching_ui_state(True)

        # Read the Filters box once. The same value goes to the fetch and to
        # every live pass, so what you see can never drift from what a fetch
        # would have produced.
        post_filters, filter_warnings = self._post_filters_from_widgets()
        for key in filter_warnings:
            self.append_log_to_console(
                translate("log_warning", translate(key)),
                "WARNING",
            )

        self.post_detection_thread = PostDetectionThread(
            url,
            self.post_titles_map,
            self._create_thread_settings(),
            post_dates_map=self.post_dates_map,
            post_search_index=self.post_search_index,
            found_extensions=self._found_type_counts,
            post_filters=post_filters,
            # Names are normally fetched when the URL is queued; this is the
            # fallback for a lookup that failed or is still in flight.
            report_creator_name=(
                url.rstrip("/") not in self._creator_names
                and url.rstrip("/") not in self._name_lookup_wanted
            ),
        )
        self.post_detection_thread.finished.connect(self.on_post_detection_finished)
        self.post_detection_thread.posts_batch.connect(self.on_posts_batch_received)
        # Test doubles and older stubs may not carry the optional signal.
        name_signal = getattr(self.post_detection_thread, "creator_name_found", None)
        if name_signal is not None:
            name_signal.connect(self.on_creator_name_found)
        self.post_detection_thread.log.connect(self.append_log_to_console)
        self.post_detection_thread.error.connect(self.on_post_detection_error)
        self.post_detection_thread.finished.connect(self.cleanup_post_detection_thread)
        self.active_threads.append(self.post_detection_thread)
        self.post_detection_thread.start()
        return True

    def cleanup_post_detection_thread(self):
        """Drop the tab's reference to the fetch thread once it is done.

        A *stopped* thread can still be running for a moment, and Qt destroys
        a QThread whose last Python reference goes away while it runs
        ("Destroyed while thread is still running"). Such a thread is parked in
        ``_lingering_threads`` - the reference is what keeps it alive - and
        reaped the next time this runs.
        """
        thread = self.post_detection_thread
        if thread is None:
            return
        if thread in self.active_threads:
            self.active_threads.remove(thread)
        self.post_detection_thread = None
        self._hold_thread_reference(thread)

    def _hold_thread_reference(self, thread):
        """Keep *thread* alive until it has really finished."""
        try:
            if thread.isRunning():
                self._lingering_threads.append(thread)
        except (AttributeError, RuntimeError):  # stub or deleted object
            pass
        self._reap_lingering_threads()

    def _reap_lingering_threads(self):
        """Forget (and dispose of) parked threads that have finished."""
        still_running = []
        for thread in self._lingering_threads:
            try:
                if thread.isRunning():
                    still_running.append(thread)
                else:
                    thread.deleteLater()
            except (AttributeError, RuntimeError):
                pass
        self._lingering_threads = still_running

    def on_post_detection_finished(self, detected_posts):
        # Only update if we haven't been receiving incremental batches
        if self.current_creator_url not in self.all_files_map:
            self.all_files_map[self.current_creator_url] = detected_posts
        # Ensure all_detected_posts is set (should already be set from batches)
        if not self.all_detected_posts:
            self.all_detected_posts = detected_posts
        # Store reference to the detection thread for summary emission later
        self._last_detection_thread = self.post_detection_thread
        self._pending_detection_summary = True
        # The posts are known now, so the extension boxes can reflect what
        # this creator has (a no-op unless the toggle is ticked).
        self._render_creator_ext_checks()
        self.start_population_thread(self.all_detected_posts)

    def on_posts_batch_received(self, batch_posts):
        """Handle incremental batch of posts received during detection"""
        # Append new posts to the existing list
        self.all_detected_posts.extend(batch_posts)

        # The first batch of a fetch replaces the copy the previous view left
        # in all_files_map; later batches append to it. Extending from the
        # first batch onwards is what duplicated a creator's posts on every
        # refetch (the cached fallback then held every post twice).
        if not self._fetch_batches_started:
            self.all_files_map[self.current_creator_url] = list(batch_posts)
            self._fetch_batches_started = True
        else:
            self.all_files_map.setdefault(self.current_creator_url, []).extend(
                batch_posts
            )

        # Update checked_urls for new posts
        for post_title, (post_id, thumbnail_url) in batch_posts:
            self.checked_urls[post_id] = False

        # Trigger incremental filtering to add new posts to UI
        self.filter_items_incremental(batch_posts)

    def _selected_search_scopes(self):
        """Return the scopes ticked in the "Search by" row.

        An empty selection falls back to the title, which is what the search
        bar has always matched against.
        """
        scopes = {
            scope
            for scope, checkbox in self.search_scope_checkboxes.items()
            if checkbox.isChecked()
        }
        return scopes or {"title"}

    def filter_items_incremental(self, batch_posts):
        """Filter and add a batch of posts to the filtered cache incrementally"""
        search_text = self.creator_search_input.text().lower()
        search_scopes = self._selected_search_scopes()
        post_filters, warnings = self._post_filters_from_widgets()
        self._log_filter_warnings(warnings)
        filtered_batch = []

        for post_title, (post_id, thumbnail_url) in batch_posts:
            # Batches now carry every fetched post, so the filters have to
            # be applied here too; otherwise a filtered post would show up
            # until the next full pass.
            facts = self.post_search_index.get(post_id)
            reason, _keyword = post_skip_reason(post_title, facts, post_filters)
            if reason is not None:
                continue
            if post_matches_search(
                post_title,
                post_id,
                search_text,
                search_scopes,
                self.post_search_index,
            ):
                is_checked = self.checked_urls.get(post_id, False)
                filtered_batch.append((post_title, post_id, thumbnail_url, is_checked))

        # Add to filtered posts cache
        self.filtered_posts.extend(filtered_batch)

        # Update pagination info
        self.total_pages = max(
            1,
            (len(self.filtered_posts) + self.posts_per_page - 1) // self.posts_per_page,
        )

        # If we're on the last page and there are more posts to show, add them to current page
        current_page_start = (self.current_page - 1) * self.posts_per_page
        current_page_end = min(
            current_page_start + self.posts_per_page, len(self.filtered_posts)
        )

        if (
            self.current_page == self.total_pages
            or len(self.filtered_posts) <= self.posts_per_page
        ):
            # Add new items to current page display
            start_idx = len(self.filtered_posts) - len(filtered_batch)
            for i in range(
                max(start_idx, current_page_start),
                min(len(self.filtered_posts), current_page_end),
            ):
                post_title, post_id, thumbnail_url, is_checked = self.filtered_posts[i]
                post_date = self.post_dates_map.get(post_id, "Unknown date")
                unique_title = f"{post_title} ({post_date})"
                self.post_url_map[unique_title] = (post_id, thumbnail_url)
                self.add_list_item(unique_title, thumbnail_url, is_checked)

        self.update_pagination_controls()
        self.update_check_all_state()
        self.update_checked_posts()
        self.append_log_to_console(
            translate(
                "log_debug",
                translate("incremental_filtering_added_posts", len(filtered_batch)),
            ),
            "DEBUG",
        )

    def set_fetching_ui_state(self, is_fetching):
        """Enable/disable UI elements during fetching."""
        # Main action buttons
        self.creator_download_btn.setEnabled(not is_fetching)
        self.creator_cancel_btn.setEnabled(is_fetching)

        # Creator queue operations
        self.creator_queue_input.setEnabled(not is_fetching)
        self.creator_queue_input_btn.setEnabled(not is_fetching)
        self.creator_queue_list.setEnabled(not is_fetching)
        if not is_fetching and self._restore_queue_input_focus:
            # An auto-loaded creator just finished fetching: put the cursor
            # back in the blank row for the next URL.
            self._restore_queue_input_focus = False
            self.creator_queue_input.setFocus()

        # Post operations
        self.creator_search_input.setEnabled(not is_fetching)
        self.creator_check_all.setEnabled(not is_fetching)
        self.creator_check_all_all.setEnabled(not is_fetching)
        self.creator_post_list.setEnabled(not is_fetching)

        # Inline skip-keywords filter
        self.skip_keywords_edit.setEnabled(not is_fetching)
        for checkbox in self.skip_scope_checkboxes.values():
            checkbox.setEnabled(not is_fetching)
        self.skip_keywords_help_btn.setEnabled(not is_fetching)
        self.file_skip_keywords_edit.setEnabled(not is_fetching)
        self.file_skip_keywords_help_btn.setEnabled(not is_fetching)
        self.date_from_edit.setEnabled(not is_fetching)
        self.date_to_edit.setEnabled(not is_fetching)
        self.date_filter_help_btn.setEnabled(not is_fetching)
        # Inline file-count filter
        self.file_count_from_edit.setEnabled(not is_fetching)
        self.file_count_to_edit.setEnabled(not is_fetching)
        self.file_count_keep_compressed_check.setEnabled(not is_fetching)
        self.file_count_help_btn.setEnabled(not is_fetching)
        # Search scopes
        for checkbox in self.search_scope_checkboxes.values():
            checkbox.setEnabled(not is_fetching)
        # The extension grid feeds the "no selected filetypes" filter, so it is
        # part of the Filters box: locked with the rest of it while a fetch
        # rewrites the list underneath.
        for checkbox in getattr(self, "creator_ext_checks", {}).values():
            checkbox.setEnabled(not is_fetching)
        filetype_filter = getattr(self, "filter_no_selected_filetypes_check", None)
        if filetype_filter is not None:
            filetype_filter.setEnabled(not is_fetching)
        # The fetch froze its copy of "Download Post Text" when it started, and
        # that value decides whether text-only posts are filtered out.
        text_option = getattr(self, "creator_download_text_check", None)
        if text_option is not None:
            text_option.setEnabled(not is_fetching)

        # Pagination controls
        self.prev_page_btn.setEnabled(not is_fetching and self.current_page > 1)
        self.next_page_btn.setEnabled(
            not is_fetching and self.current_page < self.total_pages
        )

        # Post list info button
        self.creator_box_info_btn.setEnabled(not is_fetching)

        # Tab switching (disable other tabs during fetching)
        if self._parent and hasattr(self._parent, "tabs"):
            for i in range(self._parent.tabs.count()):
                if i != self._parent.tabs.currentIndex():  # Keep current tab enabled
                    self._parent.tabs.setTabEnabled(i, not is_fetching)

    def set_downloading_ui_state(self, is_downloading):
        """Lock/unlock ALL UI controls during an active download.

        Only the Cancel button, the log controls and the (greyed) retry button
        remain clickable while downloading.
        """
        enabled = not is_downloading

        # Action buttons
        self.creator_download_btn.setEnabled(enabled)
        self.creator_cancel_btn.setEnabled(is_downloading)
        self._refresh_retry_button()

        # Queue input area
        self.creator_queue_input.setEnabled(enabled)
        self.creator_queue_input_btn.setEnabled(enabled)
        self.creator_queue_list.setEnabled(enabled)

        # Category checkboxes
        self.creator_main_check.setEnabled(enabled)
        self.creator_attachments_check.setEnabled(enabled)
        self.creator_content_check.setEnabled(enabled)

        # Options
        self.creator_download_text_check.setEnabled(enabled)

        # Skip-folder toggle + dropdown
        self.creator_skip_folder_check.setEnabled(enabled)
        self.creator_skip_folder_combo.setEnabled(enabled)
        self.creator_skip_folder_info_btn.setEnabled(enabled)
        self.creator_force_compressed_folder_check.setEnabled(enabled)
        self.creator_skip_images_check.setEnabled(enabled)
        self.creator_skip_images_info_btn.setEnabled(enabled)

        # Post selection
        self.creator_search_input.setEnabled(enabled)
        self.creator_check_all.setEnabled(enabled)
        self.creator_check_all_all.setEnabled(enabled)
        self.creator_post_list.setEnabled(enabled)
        self.creator_box_info_btn.setEnabled(enabled)

        # Inline skip-keywords filter
        self.skip_keywords_edit.setEnabled(enabled)
        for checkbox in self.skip_scope_checkboxes.values():
            checkbox.setEnabled(enabled)
        self.skip_keywords_help_btn.setEnabled(enabled)
        self.file_skip_keywords_edit.setEnabled(enabled)
        self.file_skip_keywords_help_btn.setEnabled(enabled)
        self.date_filter_help_btn.setEnabled(enabled)
        self.date_from_edit.setEnabled(enabled)
        self.date_to_edit.setEnabled(enabled)
        self.file_count_from_edit.setEnabled(enabled)
        self.file_count_to_edit.setEnabled(enabled)
        self.file_count_keep_compressed_check.setEnabled(enabled)
        self.file_count_help_btn.setEnabled(enabled)
        for checkbox in self.search_scope_checkboxes.values():
            checkbox.setEnabled(enabled)
        # The download workers read a snapshot taken when the run started, so
        # leaving these clickable would only mislead: the ticks would not apply
        # to the run in flight.
        for checkbox in getattr(self, "creator_ext_checks", {}).values():
            checkbox.setEnabled(enabled)
        filetype_filter = getattr(self, "filter_no_selected_filetypes_check", None)
        if filetype_filter is not None:
            filetype_filter.setEnabled(enabled)

        # Pagination
        self.prev_page_btn.setEnabled(enabled and self.current_page > 1)
        self.next_page_btn.setEnabled(enabled and self.current_page < self.total_pages)

        # The config buttons describe the page, not the run in flight.
        self._refresh_config_buttons()

        # Tabs: disable all other tabs (keep current) + settings tab
        if self._parent and hasattr(self._parent, "tabs"):
            for i in range(self._parent.tabs.count()):
                if i != self._parent.tabs.currentIndex():
                    self._parent.tabs.setTabEnabled(i, enabled)
        if self._parent and hasattr(self._parent, "status_label"):
            self._parent.status_label.setText(
                translate("preparing_files") if is_downloading else translate("idle")
            )

    def prev_page(self):
        """Go to previous page"""
        if self.current_page > 1:
            self.current_page -= 1
            self.display_current_page()

    def next_page(self):
        """Go to next page"""
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.display_current_page()

    def _update_post_list_empty_state(self):
        """Show why the post list is empty, or hide the hint.

        Only when there are posts to show: a creator with no posts at all
        is a different situation and keeps the plain empty list. With the
        filetype filter on and nothing ticked, no post can match, so the hint
        names that instead of blaming the filters in general.
        """
        label = getattr(self, "creator_post_empty_label", None)
        if label is None:
            return
        empty = bool(self.all_detected_posts) and not self.filtered_posts
        if empty:
            required = self._required_filetypes()
            if required is not None and not required:
                text = translate("supported_filetypes_not_present")
            else:
                text = translate("no_posts_match_filters")
            if label.text() != text:
                label.setText(text)
        label.setVisible(empty)

    def display_current_page(self, preserve_scroll=False, scroll_value=None):
        """Display the current page of posts.

        Filter and search passes call this with *preserve_scroll* so the list
        stays where the user was reading instead of jumping back to the top;
        paging leaves it off so a new page starts at the top. *scroll_value*
        overrides what is restored (a search start or a search clear knows
        exactly where the viewport belongs).
        """
        if scroll_value is None and preserve_scroll:
            scroll_value = self.creator_post_list.verticalScrollBar().value()
        self._update_post_list_empty_state()
        self.creator_post_list.clear()
        self.post_widget_cache.clear()

        start_idx = (self.current_page - 1) * self.posts_per_page
        end_idx = min(start_idx + self.posts_per_page, len(self.filtered_posts))

        for i in range(start_idx, end_idx):
            post_title, post_id, thumbnail_url, is_checked = self.filtered_posts[i]
            post_date = self.post_dates_map.get(post_id, "Unknown date")
            unique_title = f"{post_title} ({post_date})"
            self.post_url_map[unique_title] = (post_id, thumbnail_url)
            self.add_list_item(unique_title, thumbnail_url, is_checked)

        if scroll_value is not None:
            # Qt clamps automatically when the rebuilt list is shorter.
            self.creator_post_list.verticalScrollBar().setValue(scroll_value)

        self.update_pagination_controls()
        self.update_check_all_state()
        self.append_log_to_console(
            translate(
                "log_debug",
                translate(
                    "displayed_page_posts",
                    self.current_page,
                    len(self.filtered_posts[start_idx:end_idx]),
                ),
            ),
            "DEBUG",
        )

    def update_pagination_controls(self):
        """Update pagination UI controls.

        Pagination buttons stay disabled while a download is active so
        that the user cannot navigate away from the current page.
        """
        if self.downloading or self.total_pages <= 1:
            self.page_label.setText(
                ""
                if self.total_pages <= 1
                else translate("page_info", self.current_page, self.total_pages)
            )
            self.prev_page_btn.setEnabled(False)
            self.next_page_btn.setEnabled(False)
        else:
            self.page_label.setText(
                translate("page_info", self.current_page, self.total_pages)
            )
            self.prev_page_btn.setEnabled(self.current_page > 1)
            self.next_page_btn.setEnabled(self.current_page < self.total_pages)

    def start_population_thread(self, detected_posts):
        self.background_task_label.setText(translate("populating_posts"))
        self.background_task_progress.setRange(0, 0)
        self.post_population_thread = PostPopulationThread(
            detected_posts, post_dates_map=self.post_dates_map
        )
        self.post_population_thread.finished.connect(self.on_post_population_finished)
        self.post_population_thread.finished.connect(
            self.cleanup_post_population_thread
        )
        self.post_population_thread.log.connect(self.append_log_to_console)
        self.active_threads.append(self.post_population_thread)
        self.post_population_thread.start()

    def cleanup_post_population_thread(self):
        """Drop the finished population thread from active_threads.

        Leaving it behind kept the tab permanently "busy", which made the retry
        action refuse to start with "A download is already running".
        """
        thread = self.post_population_thread
        if thread is None:
            return
        if thread in self.active_threads:
            self.active_threads.remove(thread)
        self.post_population_thread = None
        try:
            thread.deleteLater()
        except (AttributeError, RuntimeError):
            pass  # not a QThread any more, or already deleted

    def on_post_population_finished(self, post_url_map, all_detected_posts):
        self.post_url_map = post_url_map
        self.all_detected_posts = all_detected_posts
        # Load this creator's per-post last-download dates before any row is
        # rendered, so the list does not redraw when the data arrives.
        self._load_post_history()
        for post_title, (post_id, thumbnail_url) in self.all_detected_posts:
            self.checked_urls[post_id] = False
        for i, (queue_url, _) in enumerate(self.creator_queue):
            if queue_url == self.current_creator_url:
                self.creator_queue[i] = (
                    self.current_creator_url,
                    True,
                )  # Mark as processed
                self.update_creator_queue_list()
                break
        self.filter_items()
        self.set_fetching_ui_state(False)  # Re-enable UI when fetching is complete
        self.append_log_to_console(
            translate(
                "log_debug",
                translate(
                    "populated_posts_for_creator",
                    len(self.all_detected_posts),
                    self.current_creator_url,
                ),
            ),
            "DEBUG",
        )
        self.background_task_progress.setRange(0, 100)
        self.background_task_progress.setValue(0)
        self.background_task_label.setText(translate("idle"))

        # If this creator was queued from a post link, select that post as soon
        # as its posts are loaded - not only during a batch download. The
        # filtered list is rebuilt asynchronously, so flag it for
        # on_filter_finished to re-apply (and reveal the page the post is on)
        # once the rows actually exist.
        self._post_link_selection_pending = bool(
            self._batch_post_ids.get((self.current_creator_url or "").rstrip("/"))
        )
        if self._post_link_selection_pending:
            self._apply_post_link_selection()

    def on_post_detection_error(self, error_message):
        self.append_log_to_console(translate("log_error", error_message), "ERROR")

        # If fetching failed, try to use cached posts as fallback
        if self.current_creator_url in self.all_files_map:
            self.append_log_to_console(
                translate(
                    "log_info",
                    translate("using_cached_posts_fallback", self.current_creator_url),
                ),
                "INFO",
            )
            self.all_detected_posts = self.all_files_map.get(
                self.current_creator_url, []
            )
            self.start_population_thread(self.all_detected_posts)
        else:
            self.set_fetching_ui_state(False)  # Re-enable UI on error
            self.background_task_progress.setRange(0, 100)
            self.background_task_progress.setValue(0)
            self.background_task_label.setText(translate("idle"))

        if self.post_detection_thread is not None:
            self.cleanup_post_detection_thread()

    def start_creator_download(self):
        # Download is a single-creator action: it downloads exactly the posts
        # the user has ticked for the creator currently being viewed. It never
        # re-fetches posts, never auto-selects anything, and never walks the
        # queue - the queue is a list of links to inspect, nothing more.
        if not self.creator_queue:
            self.append_log_to_console(
                translate("log_warning", translate("no_creators_queue")), "WARNING"
            )
            return
        if not self.current_creator_url:
            self.append_log_to_console(
                translate("log_warning", translate("no_creator_viewed")), "WARNING"
            )
            return
        if not self.posts_to_download:
            self.append_log_to_console(
                translate("log_warning", translate("no_posts_selected")), "WARNING"
            )
            return

        self.downloading = True
        self._run_finished = False
        self.set_downloading_ui_state(True)
        if self._parent and hasattr(self._parent, "status_label"):
            self._parent.status_label.setText(translate("preparing_files"))
        self.creator_download_btn.setEnabled(False)
        self.creator_cancel_btn.setEnabled(True)
        self.creator_overall_progress.setValue(0)
        self.total_posts_to_download = len(self.posts_to_download)
        self.completed_posts.clear()
        self.completed_files.clear()
        self.failed_files.clear()
        # Fresh run: forget the previous run's failures (hiding the retry
        # button) but keep the post-filter skip counts in the summary.
        self._reset_download_summary(keep_post_stats=True)
        self.total_files_to_download = 0
        self.creator_overall_progress_label.setText(
            translate("overall_progress", 0, 0, 0, self.total_posts_to_download)
        )
        self.current_file_index = -1
        self.creator_file_progress.setValue(0)
        self.creator_file_progress_label.setText(translate("file_progress", 0))
        self.update_progress_bar_style()

        self.background_task_label.setText(translate("preparing_files"))
        self.background_task_progress.setRange(0, 100)
        self.background_task_progress.setValue(0)

        self.append_log_to_console(
            translate(
                "log_info", translate("posts_to_download_num", self.posts_to_download)
            ),
            "INFO",
        )
        self.append_log_to_console(
            translate(
                "log_info",
                translate("preparing_files_creator", self.current_creator_url),
            ),
            "INFO",
        )
        self.prepare_files_for_download([self.current_creator_url])

    def _remember_batch_post_id(self, creator_url, post_id):
        """Record (or clear) the post-link restriction for a creator URL.

        A post id adds to the set for that creator; passing ``None`` clears the
        restriction, because a plain creator link means "all posts". Returns
        True when the stored state actually changed.
        """
        creator_url = (creator_url or "").rstrip("/")
        if post_id:
            known_post_ids = self._batch_post_ids.setdefault(creator_url, set())
            if str(post_id) not in known_post_ids:
                known_post_ids.add(str(post_id))
                return True
            return False
        return self._batch_post_ids.pop(creator_url, None) is not None

    def _apply_post_link_selection(self):
        """Apply this creator's post-link restriction, if any.

        Marks the requested posts checked, re-stamps the cached rows and moves
        to the page holding the first requested post. Idempotent and does not
        render, so it is safe to re-apply after the post list is rebuilt.
        Returns the selected post ids (empty list when nothing matched).
        """
        requested_post_ids = self._batch_post_ids.get(
            (self.current_creator_url or "").rstrip("/")
        )
        if not requested_post_ids:
            return []
        matching = [
            post_id
            for _title, (post_id, _thumb) in self.all_detected_posts
            if str(post_id) in requested_post_ids
        ]
        for post_id in matching:
            self.checked_urls[post_id] = True
        self._sync_filtered_posts_checked()
        visible_ids = {
            post_id for _title, post_id, _thumb, _checked in self.filtered_posts
        }
        hidden = [post_id for post_id in matching if post_id not in visible_ids]
        if hidden:
            self.append_log_to_console(
                translate(
                    "log_warning",
                    translate("queued_post_hidden_by_filters", len(hidden)),
                ),
                "WARNING",
            )
        # The tick stays, but a hidden post is not downloaded: the shared
        # recompute above would say that again, so let this warning stand.
        self.update_checked_posts(announce_hidden=False)
        self._goto_page_for_post_ids(requested_post_ids)
        return matching

    def _sync_filtered_posts_checked(self):
        """Re-stamp the cached rows' checked flag from checked_urls.

        Each row renders its checkbox from the cached tuple, so updating
        checked_urls alone does not change what the user sees.
        """
        self.filtered_posts = [
            (
                title,
                post_id,
                thumbnail_url,
                self.checked_urls.get(post_id, is_checked),
            )
            for title, post_id, thumbnail_url, is_checked in self.filtered_posts
        ]

    def _goto_page_for_post_ids(self, post_ids):
        """Move to the page containing the first of the given post ids."""
        wanted = {str(post_id) for post_id in post_ids}
        for index, (_title, post_id, _thumb, _checked) in enumerate(
            self.filtered_posts
        ):
            if str(post_id) in wanted:
                self.current_page = index // self.posts_per_page + 1
                return

    def prepare_files_for_download(self, urls):
        if (
            self.file_preparation_thread is not None
            and self.file_preparation_thread.isRunning()
        ):
            self.append_log_to_console(
                translate("log_warning", translate("file_preparation_in_progress")),
                "WARNING",
            )
            return

        if not self.current_creator_url:
            self.append_log_to_console(
                translate("log_warning", translate("no_creator_viewed")), "WARNING"
            )
            self.creator_download_finished()
            return
        current_creator_posts = {
            post_id
            for _, (post_id, _) in self.all_files_map.get(self.current_creator_url, [])
        }
        post_ids = [
            post_id
            for post_id in self.posts_to_download
            if post_id in current_creator_posts
        ]
        if set(post_ids) != set(self.posts_to_download):
            self.append_log_to_console(
                translate(
                    "log_error",
                    translate("post_id_mismatch", self.posts_to_download, post_ids),
                ),
                "ERROR",
            )

        if not post_ids:
            self.append_log_to_console(
                translate("log_warning", translate("no_posts_available")), "WARNING"
            )
            self.background_task_progress.setRange(0, 100)
            self.background_task_progress.setValue(0)
            self.background_task_label.setText(translate("idle"))
            self.creator_download_finished()
            return

        file_skip_keywords = self._file_skip_keywords_from_widgets()
        _lenient_posts, lenient_files, lenient_punctuation = (
            self._keyword_matching_modes()
        )

        self.file_preparation_thread = FilePreparationThread(
            post_ids,
            self.all_files_map,
            self.creator_ext_checks,
            self.creator_main_check.isChecked(),
            self.creator_attachments_check.isChecked(),
            self.creator_content_check.isChecked(),
            self._create_thread_settings(),
            max_concurrent=5,
            file_skip_keywords=file_skip_keywords,
            file_skip_lenient=lenient_files,
            lenient_punctuation=lenient_punctuation,
            skip_images_if_compressed=(self.creator_skip_images_check.isChecked()),
            # Read on the GUI thread; the workers never touch the boxes.
            allowed_extensions=self._selected_extensions(),
        )
        self.file_preparation_thread.progress.connect(self.update_background_progress)
        self.file_preparation_thread.finished.connect(
            lambda files, files_map: self.on_file_preparation_finished(
                urls, files, files_map
            )
        )
        self.file_preparation_thread.log.connect(self.append_log_to_console)
        # Drop the thread from active_threads as soon as it finishes: a stale
        # entry left the tab permanently "busy" and made the retry action
        # refuse to start ("A download is already running"). The lambda above
        # runs first and still reads the thread's skip counters.
        self.file_preparation_thread.finished.connect(
            self.cleanup_file_preparation_thread
        )
        self.active_threads.append(self.file_preparation_thread)
        self.file_preparation_thread.start()

    def cleanup_file_preparation_thread(self):
        """Clean up the file preparation thread after it finishes."""
        if (
            self.file_preparation_thread is not None
            and self.file_preparation_thread in self.active_threads
        ):
            self.active_threads.remove(self.file_preparation_thread)
            self.file_preparation_thread.deleteLater()
        self.file_preparation_thread = None

    def update_background_progress(self, value):
        self.background_task_progress.setValue(value)

    def on_file_preparation_finished(self, urls, files_to_download, files_to_posts_map):
        self.total_files_to_download = len(files_to_download)
        # Store file-skip info from the FilePreparationThread so it can be
        # emitted as the LAST line in creator_download_finished().
        self._file_skip_count = getattr(
            self.file_preparation_thread, "_files_skipped_count", 0
        )
        self._file_skip_keywords = getattr(
            self.file_preparation_thread, "file_skip_keywords", []
        )
        self._images_skipped_count = getattr(
            self.file_preparation_thread, "_images_skipped_count", 0
        )
        self._file_keyword_skip_counts = dict(
            getattr(self.file_preparation_thread, "_file_skip_counts", {}) or {}
        )
        self._update_download_summary(refresh_skips=True)
        self.append_log_to_console(
            translate(
                "log_debug",
                translate("prepared_files_for_download", self.total_files_to_download),
            ),
            "DEBUG",
        )
        self.background_task_progress.setRange(0, 100)
        self.background_task_progress.setValue(0)
        self.background_task_label.setText(translate("idle"))

        if not files_to_download:
            self.append_log_to_console(
                translate("log_warning", translate("no_files_detected")), "WARNING"
            )
            self.creator_download_finished()
            return

        self._start_download_thread(
            files_to_download,
            files_to_posts_map,
            urls[0],
        )
        return

    def _post_stamp_maps(self):
        """{post_date} and {post_time} values per post id.

        The download thread only ever sees file URLs, so the stamps come from
        the search index the fetch already filled: each post's parsed publish
        datetime sits under ``"published"``. Both maps are built in one pass so
        the two placeholders cannot drift apart.

        The post list itself is (title, (post_id, thumb)) tuples, so reading
        the posts there yielded no stamps at all — the placeholders rendered
        empty for every file.
        """
        dates = {}
        times = {}
        index = self.post_search_index or {}
        for post_id, facts in index.items():
            if not isinstance(facts, dict):
                continue
            published = facts.get("published")
            if not hasattr(published, "strftime"):
                # No usable datetime: leave the stamps out so the placeholders
                # render empty rather than carrying "Unknown date" into a name.
                continue
            dates[str(post_id)] = published.strftime("%Y-%m-%d")
            times[str(post_id)] = published.strftime("%H%M")
        return dates, times

    def _start_download_thread(
        self,
        files_to_download,
        files_to_posts_map,
        creator_url=None,
        file_numbers=None,
        post_file_counts=None,
    ):
        """Create and start a CreatorDownloadThread for the current creator.

        Shared by the normal download path and by ``retry_failed_downloads()``
        so both wire the thread up identically.
        """
        creator_url = creator_url or self.current_creator_url
        self._last_run_creator_url = creator_url
        # The folder button follows the run in flight, so it starts greyed.
        self._current_creator_folder = None
        self._refresh_open_folder_button()
        self.files_to_posts_map = dict(files_to_posts_map)
        selected_posts = list(dict.fromkeys(files_to_posts_map.values()))

        # {file_number} and {post_file_count} are decided once, here, from the
        # full file list. A retry passes the previous run's maps so the failed
        # files keep the numbers (and the post's real count) they had; deriving
        # them inside the thread counted only what was handed to it.
        if file_numbers is None:
            counts = {}
            file_numbers = {}
            for file_url in files_to_download:
                post_id = files_to_posts_map.get(file_url)
                counts[post_id] = counts.get(post_id, 0) + 1
                file_numbers[file_url] = counts[post_id]
            post_file_counts = dict(counts)
        self._last_run_file_numbers = dict(file_numbers)
        self._last_run_post_file_counts = dict(post_file_counts or {})

        url = (creator_url or "").rstrip("/")
        parts = url.split("/")
        if len(parts) >= 3:
            service = parts[-3]
            creator_id = parts[-1]
            # Clean service and creator_id from potential query params
            if "?" in service:
                service = service.split("?")[0]
            if "?" in creator_id:
                creator_id = creator_id.split("?")[0]
        else:
            # Fallback if URL structure is unexpected
            service = "unknown_service"
            creator_id = "unknown_creator"

        self.creator_overall_progress_label.setText(
            translate(
                "overall_progress",
                0,
                self.total_files_to_download,
                0,
                self.total_posts_to_download,
            )
        )
        settings = self._create_thread_settings()
        post_dates, post_times = self._post_stamp_maps()
        thread = CreatorDownloadThread(
            service,
            creator_id,
            (
                self._parent.download_folder
                if self._parent and hasattr(self._parent, "download_folder")
                else ""
            ),
            selected_posts,
            files_to_download,
            files_to_posts_map,
            # The thread logs through its `log` signal; it never needs the
            # console widget (the argument is kept for compatibility).
            None,
            self.other_files_dir,
            self.post_titles_map,
            settings,
            settings.simultaneous_downloads,
            download_text=self.creator_download_text_check.isChecked(),
            skip_folder_enabled=self.creator_skip_folder_check.isChecked(),
            skip_folder_threshold=self.creator_skip_folder_combo.currentData(),
            force_folder_for_compressed=(
                self.creator_force_compressed_folder_check.isChecked()
            ),
            post_dates_map=post_dates,
            post_times_map=post_times,
            file_numbers=file_numbers,
            post_file_counts=post_file_counts,
        )
        thread.file_progress.connect(self.update_creator_file_progress)
        thread.file_completed.connect(self.update_file_completion)
        thread.post_completed.connect(self.update_post_completion)
        thread.creator_folder_ready.connect(self._on_creator_folder_ready)
        thread.log.connect(self.append_log_to_console)
        thread.finished.connect(lambda: self.cleanup_thread(thread))
        self.active_threads.append(thread)
        self._download_thread = thread
        thread.start()

    def cleanup_thread(self, thread):
        """Clean up a download thread and finish when every file is attempted."""
        # Transfer failed file from thread to tab if present
        try:
            thread_failed = getattr(thread, "failed_files", None)
            if thread_failed:
                try:
                    with self.failed_files_lock:
                        if isinstance(thread_failed, dict):
                            self.failed_files.update(thread_failed)
                        else:
                            for k, v in dict(thread_failed).items():
                                self.failed_files[k] = v
                    self.append_log_to_console(
                        translate(
                            "log_debug",
                            translate(
                                "transferred_from",
                                len(thread_failed),
                                thread.__class__.__name__,
                            ),
                        ),
                        "DEBUG",
                    )
                except Exception:
                    pass
        except Exception:
            pass
        if thread in self.active_threads:
            self.active_threads.remove(thread)
            self.append_log_to_console(
                translate(
                    "log_debug", translate("remove_thread", thread.__class__.__name__)
                ),
                "DEBUG",
            )

        # Ensure the native thread has fully exited before we let the object
        # be garbage-collected — otherwise Qt prints
        # "QThread: Destroyed while thread is still running" and crashes.
        try:
            if thread.isRunning():
                thread.wait(5000)
            thread.deleteLater()
        except RuntimeError:
            pass  # C++ object already deleted

        # Only the run in flight may finalise itself: a superseded thread that
        # unwinds late must not touch the state of the run that replaced it.
        if thread is not getattr(self, "_download_thread", None):
            return
        self._download_thread = None

        # Check if all files for the current creator have been attempted
        if (
            self.total_files_to_download > 0
            and len(self.completed_files) + len(self.failed_files)
            >= self.total_files_to_download
        ):
            self.append_log_to_console(
                translate("log_debug", translate("all_files_attempted_for_creator")),
                "DEBUG",
            )
            # Clear any remaining active threads
            for t in self.active_threads[:]:
                try:
                    if t.isRunning():
                        t.terminate()
                        t.wait()
                        self.append_log_to_console(
                            translate(
                                "log_info",
                                translate(
                                    "terminated_lingering_thread", t.__class__.__name__
                                ),
                            ),
                            "INFO",
                        )
                    self.active_threads.remove(t)
                    t.deleteLater()
                except RuntimeError:
                    self.append_log_to_console(
                        translate(
                            "log_warning",
                            translate("thread_already_deleted", t.__class__.__name__),
                        ),
                        "WARNING",
                    )
            self.active_threads.clear()
            self.creator_download_finished()
        elif not self.active_threads:
            self.append_log_to_console(
                translate("log_debug", translate("no_more_active_threads")), "DEBUG"
            )
            self.creator_download_finished()
        else:
            self.append_log_to_console(
                translate(
                    "log_debug",
                    translate(
                        "waiting_for_remaining_files",
                        len(self.completed_files),
                        self.total_files_to_download,
                        len(self.failed_files),
                        len(self.active_threads),
                    ),
                ),
                "DEBUG",
            )

        # The run's thread is really gone now, so the retry button may unlock
        # even when creator_download_finished() already ran and bailed out.
        self._refresh_retry_button()
        # Same beat for the config buttons: they are greyed while a run owns
        # the page, and this is the moment that is reliably over.
        self._refresh_config_buttons()

    def cancel_creator_download(self):
        if not self.active_threads:
            self.append_log_to_console(
                translate("log_warning", translate("no_active_downloads_to_cancel")),
                "WARNING",
            )
            return

        # Check if we're cancelling fetching or downloading
        is_fetching = (
            hasattr(self, "post_detection_thread")
            and self.post_detection_thread is not None
            and self.post_detection_thread.isRunning()
        )

        if is_fetching:
            # Cancelling fetching - stop the detection thread and keep selected posts
            self.append_log_to_console(
                translate("log_warning", translate("cancelling_post_detection")),
                "WARNING",
            )
            if self.post_detection_thread and hasattr(
                self.post_detection_thread, "stop"
            ):
                self.post_detection_thread.stop()
            self.cleanup_post_detection_thread()  # Clean up the thread
            self.set_fetching_ui_state(False)  # Re-enable UI immediately
            self.background_task_progress.setRange(0, 100)
            self.background_task_progress.setValue(0)
            self.background_task_label.setText(translate("idle"))
            # Keep everything that was fetched. Cancelling a fetch means "stop
            # loading", not "throw away the pages already here": pruning the
            # list to the ticked posts emptied it completely when nothing was
            # ticked, and forced a refetch to get back to where the user was.
            fetched = [
                post
                for post in self.all_detected_posts
                if post[1][0] in set(self.posts_to_download)
            ]
            if self.current_creator_url:
                self.all_files_map[self.current_creator_url] = list(
                    self.all_detected_posts
                )
            # Refresh the display
            self.display_current_page()
            self.update_pagination_controls()
            self.append_log_to_console(
                translate(
                    "log_info",
                    f"Kept {len(self.all_detected_posts)} fetched posts "
                    f"({len(fetched)} selected) after cancelling detection",
                ),
                "INFO",
            )
        else:
            # Cancelling downloading
            self.append_log_to_console(
                translate("log_warning", translate("all_downloads_cancelled")),
                "WARNING",
            )
            self.background_task_label.setText(translate("cancelling_downloads"))
            self.background_task_progress.setRange(0, 0)

            # Start cancellation thread to handle cleanup.
            # Store separately — do NOT add to active_threads because
            # on_cancellation_finished deletes everything in that list
            # and deleting the CancellationThread while its system thread
            # is still tearing down causes "Destroyed while running".
            self._cancellation_thread = CancellationThread(self.active_threads[:])
            self._cancellation_thread.finished.connect(self.on_cancellation_finished)
            self._cancellation_thread.log.connect(self.append_log_to_console)
            self._cancellation_thread.start()

    def on_cancellation_finished(self):
        # The cancelled run is final from here on: a later
        # creator_download_finished() must not recompute its stats.
        self._run_finished = True
        threads_to_delete = self.active_threads[:]
        self.active_threads = []
        for thread in threads_to_delete:
            try:
                # Ensure the thread has fully exited before scheduling deletion.
                # Without this, deleteLater can destroy the QThread while the
                # underlying system thread is still tearing down.
                if thread.isRunning():
                    thread.wait(5000)
                self.append_log_to_console(
                    translate(
                        "log_debug",
                        translate("deleting_thread", thread.__class__.__name__),
                    ),
                    "DEBUG",
                )
                thread.deleteLater()
            except RuntimeError:
                self.append_log_to_console(
                    translate(
                        "log_warning",
                        translate("thread_already_deleted", thread.__class__.__name__),
                    ),
                    "WARNING",
                )

        # Clean up the cancellation thread itself (stored separately)
        if self._cancellation_thread is not None:
            self._cancellation_thread.wait(2000)
            self._cancellation_thread.deleteLater()
            self._cancellation_thread = None

        self.creator_file_progress.setStyleSheet(
            "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; background: #2A3B5A; } QProgressBar::chunk { background: #D4A017; }"
        )
        self.creator_overall_progress.setStyleSheet(
            "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; background: #2A3B5A; } QProgressBar::chunk { background: #D4A017; }"
        )
        self.creator_file_progress_label.setText(translate("downloads_terminated"))
        self.creator_overall_progress_label.setText(translate("downloads_terminated"))
        self.downloading = False
        self._download_thread = None
        # Keep the failures and stats of the cancelled run: a cancel usually
        # leaves plenty to retry.
        self._remember_run_failures()
        self._update_download_summary(len(self.completed_files), len(self.failed_files))
        self.set_downloading_ui_state(False)
        self.total_files_to_download = 0
        self.completed_files.clear()
        self.failed_files.clear()
        self.completed_posts.clear()
        self.current_file_index = -1
        self.background_task_progress.setRange(0, 100)
        self.background_task_progress.setValue(0)
        self.background_task_label.setText(translate("idle"))
        self.file_preparation_thread = None
        self.post_detection_thread = None
        self.post_population_thread = None
        self.filter_thread = None
        self.checkbox_toggle_thread = None

    def update_creator_file_progress(self, file_index, progress):
        if self.current_file_index == file_index or self.current_file_index == -1:
            self.current_file_index = file_index
            self.creator_file_progress.setValue(progress)
            self.creator_file_progress_label.setText(
                translate("file_progress", progress)
            )

    def update_file_completion(self, file_index, file_url, success):
        """Update file completion status and check overall progress."""
        with self.completed_files_lock, self.failed_files_lock:
            if success:
                if file_url not in self.completed_files:
                    self.completed_files.add(file_url)
                    self.append_log_to_console(
                        translate(
                            "log_debug",
                            translate(
                                "file_completed",
                                file_url,
                                len(self.completed_files),
                                self.total_files_to_download,
                            ),
                        ),
                        "DEBUG",
                    )
            else:
                if file_url not in self.failed_files:
                    # Find the CreatorDownloadThread to get the error message
                    error_message = "Unknown error"
                    for thread in self.active_threads:
                        if isinstance(thread, CreatorDownloadThread):
                            error_message = thread.failed_files.get(
                                file_url, "Unknown error"
                            )
                            break
                    self.failed_files[file_url] = error_message
                    self.append_log_to_console(
                        translate(
                            "log_debug",
                            translate("file_failed", file_url, len(self.failed_files)),
                        ),
                        "DEBUG",
                    )
            self.update_overall_progress()
            if (
                self.total_files_to_download > 0
                and len(self.completed_files) + len(self.failed_files)
                >= self.total_files_to_download
            ):
                self.append_log_to_console(
                    translate("log_debug", translate("all_files_attempted")), "DEBUG"
                )
                self.creator_download_finished()
        if self.current_file_index == file_index:
            self.current_file_index = -1
            self.creator_file_progress.setValue(0)
            self.creator_file_progress_label.setText(translate("file_progress", 0))

    def update_overall_progress(self):
        """Update the overall progress bar and label."""
        if self.total_files_to_download > 0:
            completed_count = len(self.completed_files)
            attempted_count = completed_count + len(self.failed_files)
            percentage = int((attempted_count / self.total_files_to_download) * 100)
            self.creator_overall_progress.setValue(percentage)
            self._update_download_summary(completed_count, len(self.failed_files))

            self.creator_overall_progress_label.setText(
                translate(
                    "overall_progress",
                    completed_count,
                    self.total_files_to_download,
                    len(self.completed_posts),
                    self.total_posts_to_download,
                )
            )
        else:
            self.creator_overall_progress.setValue(0)
            self.creator_overall_progress_label.setText(
                translate(
                    "overall_progress",
                    0,
                    0,
                    len(self.completed_posts),
                    self.total_posts_to_download,
                )
            )

    def update_post_completion(self, post_id):
        """Update post completion status and check overall progress."""
        self.completed_posts.add(post_id)
        self.append_log_to_console(
            translate("log_info", translate("post_fully_downloaded", post_id)), "INFO"
        )
        self.update_overall_progress()

        if len(
            self.completed_posts
        ) == self.total_posts_to_download and self.total_files_to_download == len(
            self.completed_files
        ):
            self.append_log_to_console(
                translate("log_debug", translate("all_posts_and_files_completed")),
                "DEBUG",
            )
            # self.creator_download_finished()

    def creator_download_finished(self):
        """Reset UI state after download completes or is cancelled."""
        if self._run_finished:
            # cleanup_thread runs after the run may already have finalised
            # itself; a second pass would re-render the stats from the cleared
            # counters (Downloaded/Failed back to 0) and hide the failures.
            return
        self._run_finished = True
        self.downloading = False
        # Snapshot the failures and surface the run stats before the counters
        # are cleared below: they feed the summary block and the retry button.
        self._remember_run_failures()
        self._update_download_summary(len(self.completed_files), len(self.failed_files))

        # Log summary of failed files
        if self.failed_files:
            self.append_log_to_console(
                translate(
                    "log_warning",
                    translate(
                        "download_completed_with_failed_files", len(self.failed_files)
                    ),
                ),
                "WARNING",
            )
            for file_url, error in self.failed_files.items():
                self.append_log_to_console(
                    translate(
                        "log_error",
                        translate("download_file_failed_with_error", file_url, error),
                    ),
                    "ERROR",
                )

        self.append_log_to_console(
            translate("log_info", translate("download_process_completed")), "INFO"
        )

        # Emit file-level skip-keyword summary as the VERY LAST line so
        # it never gets buried behind subsequent messages.
        file_skip_kws = getattr(self, "_file_skip_keywords", [])
        if file_skip_kws:
            self.append_log_to_console(
                translate(
                    "log_info",
                    translate(
                        "files_skipped_by_keyword",
                        getattr(self, "_file_skip_count", 0),
                        ", ".join(file_skip_kws),
                    ),
                ),
                "INFO",
            )

        # Always show Downloads Complete, even if some files failed
        self.creator_file_progress.setStyleSheet(
            "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; background: #2A3B5A; } QProgressBar::chunk { background: green; }"
        )
        self.creator_overall_progress.setStyleSheet(
            "QProgressBar { border: 1px solid #4A5B7A; border-radius: 5px; background: #2A3B5A; } QProgressBar::chunk { background: green; }"
        )
        self.creator_file_progress_label.setText(translate("downloads_complete"))
        self.creator_overall_progress_label.setText(translate("downloads_complete"))

        self.total_files_to_download = 0
        self.completed_files.clear()
        self.failed_files.clear()
        self.completed_posts.clear()
        self.current_file_index = -1
        self.background_task_progress.setRange(0, 100)
        self.background_task_progress.setValue(0)
        self.background_task_label.setText(translate("idle"))
        self.file_preparation_thread = None
        self.post_detection_thread = None
        self.post_population_thread = None
        self.filter_thread = None
        self.checkbox_toggle_thread = None

        # Fully restore the UI. The creator queue is deliberately left as-is:
        # finishing a download must never remove or alter queued creators.
        self.set_downloading_ui_state(False)

        # Reflect the freshly written download dates in the rows and in the
        # "last downloaded from creator" label.
        self.refresh_download_history_ui()

    def show_skip_keywords_help(self):
        """Show help text explaining the inline skip-keywords post filter."""
        self._show_info(
            "skip_posts_keywords_help_title", "skip_posts_keywords_help_text"
        )

    def show_file_skip_keywords_help(self):
        """Show help text explaining the inline skip-keywords file filter."""
        self._show_info(
            "skip_files_keywords_help_title", "skip_files_keywords_help_text"
        )

    def show_date_filter_help(self):
        """Show help text explaining the post date range filter."""
        self._show_info("date_filter_help_title", "date_filter_help_text")

    def show_file_count_help(self):
        """Show help text explaining the post file-count range filter."""
        self._show_info("file_count_help_title", "file_count_help_text")

    def show_filter_no_selected_filetypes_help(self):
        """Show help text explaining the filetype post filter."""
        self._show_info(
            "filter_no_selected_filetypes_help_title",
            "filter_no_selected_filetypes_help_text",
        )

    def open_logs(self):
        """Open the full logs window, reusing it when it is already open.

        The window is the only view of the log — the tab keeps no console of
        its own — so opening always replays the buffered lines from the start.
        """
        window = getattr(self, "logs_window", None)
        if window is None or not window.isVisible():
            self.logs_window = LogsWindow(self)
            self.logs_window.show()
        else:
            window.raise_()
            window.activateWindow()
            window.update_logs_content()

    def toggle_check_all(self, state):
        if (
            self.checkbox_toggle_thread is not None
            and self.checkbox_toggle_thread.isRunning()
        ):
            self.append_log_to_console(
                translate(
                    "log_warning", translate("checkbox_toggle_already_in_progress")
                ),
                "WARNING",
            )
            return

        # Get the currently visible posts. The rows themselves carry the post
        # id (two posts can share a title and date, and the title-keyed caches
        # then hold only the last of them), so build the list from the list
        # widget rather than from post_widget_cache.
        visible_posts = []
        for index in range(self.creator_post_list.count()):
            item = self.creator_post_list.item(index)
            if item is None or item.isHidden():
                continue
            widget = self.creator_post_list.itemWidget(item)
            post_id = getattr(widget, "post_id", None) if widget is not None else None
            if not post_id:
                continue
            post_title = getattr(widget, "post_key", None) or item.text()
            _pid, thumbnail_url = self.post_url_map.get(post_title, (None, None))
            visible_posts.append((post_title, (post_id, thumbnail_url)))

        if not visible_posts:
            self.append_log_to_console(
                translate("log_warning", translate("no_visible_posts_to_toggle")),
                "WARNING",
            )
            return

        self.background_task_label.setText(translate("updating_checkboxes"))
        self.background_task_progress.setRange(0, 0)
        self.checkbox_toggle_thread = CheckboxToggleThread(
            visible_posts, self.checked_urls, state
        )
        self.checkbox_toggle_thread.finished.connect(self.on_toggle_check_all_finished)
        self.checkbox_toggle_thread.log.connect(self.append_log_to_console)
        self.checkbox_toggle_thread.finished.connect(
            self.cleanup_checkbox_toggle_thread
        )
        self.active_threads.append(self.checkbox_toggle_thread)
        self.checkbox_toggle_thread.start()

    def cleanup_checkbox_toggle_thread(self):
        """Clean up the checkbox toggle thread after it finishes."""
        if self.checkbox_toggle_thread in self.active_threads:
            self.active_threads.remove(self.checkbox_toggle_thread)
        if self.checkbox_toggle_thread:
            self.checkbox_toggle_thread.deleteLater()
            self.checkbox_toggle_thread = None

    def toggle_check_all_all(self, state):
        if (
            self.checkbox_toggle_thread is not None
            and self.checkbox_toggle_thread.isRunning()
        ):
            self.append_log_to_console(
                translate(
                    "log_warning", translate("checkbox_toggle_already_in_progress")
                ),
                "WARNING",
            )
            return

        # Use all detected posts instead of just visible ones
        if not self.all_detected_posts:
            self.append_log_to_console(
                translate("log_warning", translate("no_posts_to_toggle")), "WARNING"
            )
            return

        self.background_task_label.setText(translate("updating_checkboxes"))
        self.background_task_progress.setRange(0, 0)
        self.checkbox_toggle_thread = CheckboxToggleThread(
            self.all_detected_posts, self.checked_urls, state
        )
        self.checkbox_toggle_thread.finished.connect(self.on_toggle_check_all_finished)
        self.checkbox_toggle_thread.log.connect(self.append_log_to_console)
        self.checkbox_toggle_thread.finished.connect(
            self.cleanup_checkbox_toggle_thread
        )
        self.active_threads.append(self.checkbox_toggle_thread)
        self.checkbox_toggle_thread.start()

    def on_toggle_check_all_finished(self, checked_urls, posts_to_download):
        self.checked_urls = checked_urls
        self.posts_to_download = posts_to_download
        self.filter_items()
        self.background_task_progress.setRange(0, 100)
        self.background_task_progress.setValue(0)
        self.background_task_label.setText(translate("idle"))
        visible_count = sum(
            1
            for i in range(self.creator_post_list.count())
            if (item := self.creator_post_list.item(i)) and not item.isHidden()
        )
        self.append_log_to_console(
            translate(
                "log_debug",
                translate(
                    "checkbox_toggle_finished",
                    len(self.posts_to_download),
                    visible_count,
                ),
            ),
            "DEBUG",
        )

    def update_checked_posts(self, announce_hidden=True):
        """Work out which posts the Download button acts on.

        Only posts that are ticked AND currently listed count, so a filter
        that hides a post also keeps it out of the download. The tick is left
        alone, so clearing the filter brings the post back still ticked.
        """
        self.posts_to_download = []
        seen_ids = set()
        if not self.current_creator_url:
            self.append_log_to_console(
                translate("log_warning", translate("no_current_creator_url_set")),
                "WARNING",
            )
            return
        visible_ids = {
            post_id for _title, post_id, _thumb, _checked in self.filtered_posts
        }
        ticked_ids = [
            post_id for post_id, is_checked in self.checked_urls.items() if is_checked
        ]
        for post_id in ticked_ids:
            if post_id in visible_ids and post_id not in seen_ids:
                self.posts_to_download.append(post_id)
                seen_ids.add(post_id)
        hidden = [post_id for post_id in ticked_ids if post_id not in visible_ids]
        if hidden and announce_hidden:
            self.append_log_to_console(
                translate(
                    "log_info",
                    translate("ticked_posts_hidden_by_filters", len(hidden)),
                ),
                "INFO",
            )
        self.creator_post_count_label.setText(
            translate("posts_count", len(self.posts_to_download))
        )
        self.append_log_to_console(
            translate(
                "log_debug",
                translate(
                    "updated_checked_posts_count",
                    len(self.posts_to_download),
                    len(self.checked_urls),
                    len(self.all_detected_posts),
                    self.posts_to_download,
                ),
            ),
            "DEBUG",
        )

    def _on_search_text_changed(self):
        """Run a search from its first page, and put the reader back after.

        Typing the first character saves the page and scroll offset and starts
        the results on page 1, where a new search belongs. Clearing the box
        restores that position. Filter changes and manual paging never touch
        the saved position, so there is no guessing about when to remember and
        when to restore: only empty -> text and text -> empty do anything.
        """
        if self.creator_search_input.text().strip():
            if self._search_return_position is None:
                self._search_return_position = (
                    self.current_page,
                    self.creator_post_list.verticalScrollBar().value(),
                )
                self.current_page = 1
                self._pending_filter_scroll = 0
        else:
            position = self._search_return_position
            self._search_return_position = None
            if position is not None:
                self.current_page = position[0]
                self._pending_filter_scroll = position[1]
        self.filter_items()

    def filter_items(self):
        if self.filter_thread is not None and self.filter_thread.isRunning():
            self._filter_refresh_pending = True
            self.append_log_to_console(
                translate("log_debug", translate("filtering_already_in_progress")),
                "DEBUG",
            )
            return
        # This pass will pick up the current search text and scopes, so any
        # deferral recorded before it started is satisfied.
        self._filter_refresh_pending = False
        self.background_task_label.setText(translate("filtering_posts"))
        self.background_task_progress.setRange(0, 0)
        post_filters, warnings = self._post_filters_from_widgets()
        self._log_filter_warnings(warnings)
        _lenient_posts, lenient_files, lenient_punctuation = (
            self._keyword_matching_modes()
        )
        self.filter_thread = FilterThread(
            self.all_detected_posts,
            self.checked_urls,
            self.creator_search_input.text(),
            search_scopes=self._selected_search_scopes(),
            post_search_index=self.post_search_index,
            post_filters=post_filters,
            creator_url=self.current_creator_url,
            file_skip_keywords=self._file_skip_keywords_from_widgets(),
            file_skip_lenient=lenient_files,
            lenient_punctuation=lenient_punctuation,
        )
        self.filter_thread.finished.connect(self.on_filter_finished)
        self.filter_thread.finished.connect(self.cleanup_filter_thread)
        self.active_threads.append(self.filter_thread)
        self.filter_thread.start()

    def on_filter_finished(self, filtered_items):
        # A pass started for one creator can land after the user has moved to
        # another; showing it would paint the previous creator's rows into a
        # list that was just cleared for someone else.
        thread = getattr(self, "filter_thread", None)
        pass_creator = getattr(thread, "creator_url", None)
        if pass_creator is not None and pass_creator != self.current_creator_url:
            self.append_log_to_console(
                translate("log_debug", translate("discarded_stale_filter_pass")),
                "DEBUG",
            )
            # This pass owned the busy indicator ("Filtering…"). Since it is
            # being thrown away, nothing else will clear it, and the bar would
            # sit there spinning for the rest of the session.
            self.background_task_progress.setRange(0, 100)
            self.background_task_progress.setValue(0)
            self.background_task_label.setText(translate("idle"))
            return
        # Store filtered posts for pagination
        self.filtered_posts = filtered_items
        self.total_pages = max(
            1,
            (len(self.filtered_posts) + self.posts_per_page - 1) // self.posts_per_page,
        )

        # Only reset to page 1 if we have more than one page, otherwise keep current page
        if self.current_page > self.total_pages:
            # Clamp, do not jump to the first page: the current one may still
            # be valid after a filter change.
            self.current_page = self.total_pages

        # FilterThread snapshots checked_urls when it starts, so the rows it
        # produces can miss a selection made while it was running (batch
        # auto-select). Re-stamp from the live checked_urls and re-apply any
        # post-link restriction before rendering, so the choice always shows.
        self._sync_filtered_posts_checked()
        if self._post_link_selection_pending:
            self._post_link_selection_pending = False
            self._apply_post_link_selection()

        # Display current page, keeping the viewport where the reader was:
        # applying a filter or typing a search must not throw the list back to
        # the top of the page. A search start/clear supplies the exact offset.
        scroll_override = self._pending_filter_scroll
        self._pending_filter_scroll = None
        self.display_current_page(preserve_scroll=True, scroll_value=scroll_override)

        self.update_check_all_state()
        self.update_checked_posts()
        self.background_task_progress.setRange(0, 100)
        self.background_task_progress.setValue(0)
        self.background_task_label.setText(translate("idle"))
        self.append_log_to_console(
            translate(
                "log_debug",
                translate("filtering_completed_displayed_posts", len(filtered_items)),
            ),
            "DEBUG",
        )
        # Surface which post filters dropped how many posts, next to the
        # progress bars instead of only in the log.
        # File-keyword skips are counted by the pass over the listed posts, so
        # they follow the list just like the post-level numbers do.
        if thread is not None and hasattr(thread, "file_keyword_skipped_count"):
            self._file_skip_count = thread.file_keyword_skipped_count
            self._file_keyword_skip_counts = dict(thread.file_keyword_skip_counts)

        # The filter pass owns the numbers now: they describe the list as it
        # is filtered right now, not as it was filtered during the fetch.
        self._refresh_skip_summary_from_filter(
            getattr(self, "filter_thread", None)
            or getattr(self, "_last_detection_thread", None)
        )
        self._log_facts_missing()

        # Emit skip-keywords summary INFO lines LAST — after all detection,
        # population, and filtering logs are done — so they appear at the
        # very end of the log.
        if getattr(self, "_pending_detection_summary", False):
            self._pending_detection_summary = False
            detection_thread = getattr(self, "_last_detection_thread", None)
            if detection_thread is not None:
                filtered_count = getattr(detection_thread, "filtered_count", 0)
                total_detected = getattr(detection_thread, "total_detected", 0)
                filters_used = getattr(detection_thread, "post_filters", None)
                skip_kws = list(getattr(filters_used, "skip_keywords", ()) or ())
                keyword_skipped_count = getattr(
                    detection_thread, "keyword_skipped_count", filtered_count
                )
                date_skipped_count = getattr(detection_thread, "date_skipped_count", 0)
                self.append_log_to_console(
                    translate(
                        "log_info",
                        translate(
                            "total_posts_fetched_for_creator",
                            self.current_creator_url or "",
                            total_detected,
                            filtered_count,
                        ),
                    ),
                    "INFO",
                )
                if skip_kws and keyword_skipped_count:
                    self.append_log_to_console(
                        translate(
                            "log_info",
                            translate(
                                "posts_skipped_by_keyword",
                                keyword_skipped_count,
                                ", ".join(skip_kws),
                            ),
                        ),
                        "INFO",
                    )
                if date_skipped_count:
                    self.append_log_to_console(
                        translate(
                            "log_info",
                            translate(
                                "posts_skipped_by_date_filter", date_skipped_count
                            ),
                        ),
                        "INFO",
                    )
                file_count_skipped_count = getattr(
                    detection_thread, "file_count_skipped_count", 0
                )
                if file_count_skipped_count:
                    self.append_log_to_console(
                        translate(
                            "log_info",
                            translate(
                                "posts_skipped_by_file_count_filter",
                                file_count_skipped_count,
                            ),
                        ),
                        "INFO",
                    )
                filetype_skipped_count = getattr(
                    detection_thread, "filetype_skipped_count", 0
                )
                if filetype_skipped_count:
                    self.append_log_to_console(
                        translate(
                            "log_info",
                            translate(
                                "posts_skipped_by_filetypes_filter",
                                filetype_skipped_count,
                            ),
                        ),
                        "INFO",
                    )

        # A search-scope toggle (or fast typing) that arrived while the filter
        # pass was running was deferred; cleanup_filter_thread() applies it.

    def cleanup_filter_thread(self):
        """Clean up the filter thread after it finishes."""
        if self.filter_thread is not None:
            if self.filter_thread in self.active_threads:
                self.active_threads.remove(self.filter_thread)
            self.filter_thread.deleteLater()
            self.filter_thread = None
        # Apply any search/scope change that arrived while that pass was
        # running, so the list never shows a stale result.
        if getattr(self, "_filter_refresh_pending", False):
            self._filter_refresh_pending = False
            self.filter_items()

    def add_list_item(self, text, url, is_checked):
        item = QListWidgetItem()
        item.setData(Qt.UserRole, url)
        post_id = self.post_url_map[text][0]
        item.setData(Qt.UserRole + 1, post_id)
        widget = QWidget()
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        check_box = QCheckBox()
        check_box.setStyleSheet("color: white;")
        check_box.setChecked(is_checked)
        # The row's own post id is bound here rather than looked up from the
        # title on click: two posts with the same title and date share a key,
        # and the lookup then returned whichever one won the dict.
        check_box.clicked.connect(
            lambda: self.toggle_checkbox_state(text, post_id, widget)
        )
        layout.addWidget(check_box)

        # *text* already ends with the post's publish date in parentheses, so
        # the last-download date goes straight after it in square brackets —
        # and only when the post actually has one. That date is bolded, since
        # it is the one part of the row that changes between runs.
        download_date = self._post_history_cache.get(str(post_id))
        label = QLabel()
        label.setTextFormat(
            Qt.TextFormat.RichText if download_date else Qt.TextFormat.PlainText
        )
        label.setText(self._row_label_text(text, download_date))
        label.setStyleSheet("color: white;")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label, stretch=1)

        widget.setLayout(layout)
        item.setSizeHint(widget.sizeHint())
        self.creator_post_list.addItem(item)
        self.creator_post_list.setItemWidget(item, widget)
        widget.check_box = check_box
        widget.label = label
        # The undecorated title doubles as the post_url_map / cache key, so
        # keep it even though the label text may carry a date suffix.
        widget.post_key = text
        widget.post_id = post_id
        # Rows are child widgets, so the list view does not always receive the
        # double-click itself; handle it here too (see _on_row_double_click).
        widget.mouseDoubleClickEvent = (
            lambda event, row=item: self._on_row_double_click(row, event)
        )
        widget.setStyleSheet("background-color: #2A3B5A; border-radius: 5px;")

        # Cache the widget for O(1) lookups
        self.post_widget_cache[text] = (item, widget)

    def toggle_checkbox_state(self, post_title, post_id=None, source_widget=None):
        self.background_task_label.setText(translate("toggling_checkbox"))
        self.background_task_progress.setRange(0, 0)

        # A row that knows its own id (the normal case) passes it in, which
        # keeps the toggle attached to the post the user actually clicked even
        # when two posts share a title and publish date.
        if post_id:
            base_post_id = post_id
        else:
            base_post_id, _ = self.post_url_map.get(post_title, (None, None))
        if not base_post_id:
            self.append_log_to_console(
                translate(
                    "log_error", translate("no_post_id_found_for_title", post_title)
                ),
                "ERROR",
            )
            self.background_task_progress.setRange(0, 100)
            self.background_task_progress.setValue(0)
            self.background_task_label.setText(translate("idle"))
            return

        # Determine new state based on the clicked item
        current_state = self.checked_urls.get(base_post_id, False)
        new_state = not current_state

        # Check if the clicked item is part of the selection
        base_item, _ = self.post_widget_cache.get(post_title, (None, None))
        selected_items = self.creator_post_list.selectedItems()

        widgets_to_update = []
        if base_item and base_item in selected_items:
            # Apply to all selected items
            for item in selected_items:
                w = self.creator_post_list.itemWidget(item)
                if w:
                    widgets_to_update.append(w)
        elif source_widget is not None:
            # The row that was clicked knows which post it belongs to, so use
            # it directly: resolving the row by title is ambiguous whenever two
            # posts share a title and date.
            widgets_to_update.append(source_widget)
        else:
            # Apply only to single item
            w = self.get_widget_for_post_title(post_title)
            if w:
                widgets_to_update.append(w)

        count = 0
        for widget in widgets_to_update:
            if hasattr(widget, "label"):
                # The label may carry a "[last downloaded]" suffix, so prefer
                # the undecorated key stored when the row was built.
                title = getattr(widget, "post_key", widget.label.text())
                row_post_id = getattr(widget, "post_id", None)
                if not row_post_id:
                    row_post_id, _ = self.post_url_map.get(title, (None, None))
                if row_post_id:
                    self.checked_urls[row_post_id] = new_state
                    widget.check_box.blockSignals(True)
                    widget.check_box.setChecked(new_state)
                    widget.check_box.blockSignals(False)
                    count += 1

        self.update_checked_posts()
        self.update_check_all_state()
        self.append_log_to_console(
            translate(
                "log_debug",
                translate(
                    "checkbox_toggled_for_post", post_title, base_post_id, new_state
                )
                + f" (Applied to {count} items)",
            ),
            "DEBUG",
        )
        self.background_task_progress.setRange(0, 100)
        self.background_task_progress.setValue(0)
        self.background_task_label.setText(translate("idle"))

    def get_widget_for_post_title(self, post_title):
        # O(1) lookup instead of O(n) iteration
        cached = self.post_widget_cache.get(post_title)
        if cached:
            return cached[1]  # Return widget
        return None

    def update_check_all_state(self):
        # Update page checkbox - only iterate visible items from cache
        visible_checked = []
        for post_title, (item, widget) in self.post_widget_cache.items():
            if not item.isHidden():
                visible_checked.append(widget.check_box.isChecked())

        all_visible_checked = all(visible_checked) and len(visible_checked) > 0
        self.creator_check_all.blockSignals(True)
        self.creator_check_all.setChecked(all_visible_checked)
        self.creator_check_all.blockSignals(False)

        # Update all checkbox - check all detected posts
        all_posts_checked = (
            all(
                self.checked_urls.get(post_id, False)
                for post_title, (post_id, thumbnail_url) in self.all_detected_posts
            )
            and len(self.all_detected_posts) > 0
        )
        self.creator_check_all_all.blockSignals(True)
        self.creator_check_all_all.setChecked(all_posts_checked)
        self.creator_check_all_all.blockSignals(False)

        self.append_log_to_console(
            translate(
                "log_debug", translate("check_all_state_updated", all_visible_checked)
            ),
            "DEBUG",
        )

    def _on_row_double_click(self, item, event):
        """Handle a double-click on a post row.

        Accepting the event stops it propagating to the list view, which would
        otherwise open a second preview for the same gesture.
        """
        event.accept()
        self.preview_post(item)

    def preview_post(self, item):
        """Open the full post preview for a list row (double-click action).

        The row's stored post id is what matters: a post can hold images in
        its attachments even when its representative file is a video or
        missing, so the old single-image gate no longer applies here.
        """
        if item is None:
            return
        post_id = item.data(Qt.UserRole + 1)
        thumbnail_url = item.data(Qt.UserRole)
        if not post_id:
            # A row without an id (older data, or a test fixture): fall back
            # to the single-image preview when there is an image to show.
            if thumbnail_url and _looks_like_image(thumbnail_url):
                modal = ImageModal(
                    str(thumbnail_url),
                    self,
                    settings_tab=getattr(self._parent, "settings_tab", None),
                )
                try:
                    modal.exec()
                finally:
                    delete_later = getattr(modal, "deleteLater", None)
                    if delete_later is not None:
                        delete_later()
            return
        creator_url = getattr(self, "current_creator_url", None)
        if not creator_url:
            self.append_log_to_console(
                translate("log_warning", translate("no_current_creator_url_set")),
                "WARNING",
            )
            return
        settings_tab = getattr(self._parent, "settings_tab", None)
        post_data = self._cached_post_preview_data(creator_url, post_id)
        max_retries = 1
        if settings_tab is not None and hasattr(
            settings_tab, "get_post_data_max_retries"
        ):
            try:
                max_retries = min(
                    max(1, int(settings_tab.get_post_data_max_retries())), 3
                )
            except (TypeError, ValueError):
                max_retries = 1
        dialog = PostPreviewDialog(
            str(post_id),
            creator_url,
            self,
            settings_tab=settings_tab,
            post_data=post_data,
            max_retries=max_retries,
            thread_registry=self._preview_fetch_threads,
            image_cache=getattr(self, "_preview_image_cache", None),
        )
        dialog.post_loaded.connect(
            lambda pid, post, cu=creator_url: self._remember_post_preview_data(
                pid, post, cu
            )
        )
        try:
            dialog.exec()
        finally:
            # The dialog is a Qt child of this tab; without this it would stay
            # alive (with its rows and loader) for the rest of the session.
            delete_later = getattr(dialog, "deleteLater", None)
            if delete_later is not None:
                delete_later()

    def _remember_post_preview_data(self, post_id, post, creator_url=None):
        """Cache a fetched post for the next time its preview is opened."""
        creator_url = creator_url or getattr(self, "current_creator_url", None)
        if not creator_url:
            return
        key = self._preview_cache_key(creator_url, post_id)
        self._post_preview_cache[key] = post
        self._post_preview_cache.move_to_end(key)
        while len(self._post_preview_cache) > POST_PREVIEW_CACHE_LIMIT:
            self._post_preview_cache.popitem(last=False)

    @staticmethod
    def _preview_cache_key(creator_url, post_id):
        """Normalise the creator URL so trailing slashes share one entry."""
        return (str(creator_url or "").rstrip("/"), str(post_id))

    def _cached_post_preview_data(self, creator_url, post_id):
        """Return a cached post record, marking it most recently used."""
        key = self._preview_cache_key(creator_url, post_id)
        post = self._post_preview_cache.get(key)
        if post is not None:
            self._post_preview_cache.move_to_end(key)
        return post

    def _clear_preview_caches(self):
        """Drop cached post records and preview image bytes."""
        post_cache = getattr(self, "_post_preview_cache", None)
        if post_cache is not None:
            post_cache.clear()
        image_cache = getattr(self, "_preview_image_cache", None)
        if image_cache is not None:
            image_cache.clear()

    def on_selection_changed(self):
        # Reset previous styles
        if hasattr(self, "previous_selected_widgets"):
            for w in self.previous_selected_widgets:
                try:
                    w.setStyleSheet("background-color: #2A3B5A; border-radius: 5px;")
                except RuntimeError:
                    pass

        self.previous_selected_widgets = []
        selected_items = self.creator_post_list.selectedItems()
        for item in selected_items:
            widget = self.creator_post_list.itemWidget(item)
            if widget:
                widget.setStyleSheet("background-color: #4A5B7A; border-radius: 5px;")
                self.previous_selected_widgets.append(widget)

    # ------------------------------------------------------------------
    # Logging
    #
    # Lines go into ``self._log_lines`` (a plain list) and the full LogsWindow
    # is the only view over it. Nothing touches a widget while logging except
    # the button's line count, which is what used to make every resize crawl
    # when a console held thousands of lines.
    # ------------------------------------------------------------------

    def log_line_count(self):
        """Number of lines currently held in the log store."""
        return len(self._log_lines)

    def log_next_index(self):
        """Absolute index just past the newest line."""
        return self._log_dropped + self.log_line_count()

    def log_lines_from(self, index):
        """Return ``(message, colour)`` pairs from absolute *index* onwards.

        Indices stay absolute across the store's line cap, so a slow view keeps
        working instead of silently freezing once old lines are trimmed.
        """
        start = max(0, index - self._log_dropped)
        return list(self._log_lines[start:])

    def clear_log(self):
        """Drop the stored log and every view of it."""
        self._log_lines.clear()
        self._log_dropped = 0
        window = getattr(self, "logs_window", None)
        if window is not None:
            window.logs_display.clear()
            window._shown = 0
        self._update_log_button_text()

    def _update_log_button_text(self):
        """Re-text the log button: plain "Log", or a line count if it has one."""
        button = getattr(self, "creator_log_btn", None)
        if button is None:
            return
        count = len(self._log_lines)
        button.setText(
            translate("log_panel_toggle_count", count)
            if count
            else translate("log_panel_toggle")
        )
        button.setToolTip(translate("open_log_tooltip"))

    def append_log_to_console(self, message, level="INFO"):
        level = str(level).upper()
        # Debug lines describe the program to itself: skip them entirely
        # unless verbose logging is on, so they never eat into the line cap.
        if level == "DEBUG" and not self._verbose_logging:
            return
        color = LOG_LEVEL_COLORS.get(level, LOG_DEFAULT_COLOR)
        self._log_lines.append((message, color))
        if len(self._log_lines) > self._log_line_limit:
            dropped = len(self._log_lines) - self._log_line_limit
            del self._log_lines[:dropped]
            self._log_dropped += dropped

        # The button's count is the only live view logging touches, and a
        # download can log hundreds of lines a second: throttle the relabel.
        if not self._log_counter_timer.isActive():
            self._log_counter_timer.start()

        window = getattr(self, "logs_window", None)
        if window is not None and window.isVisible():
            window.update_logs_content()

    # ------------------------------------------------------------------
    # Run summary + retry
    # ------------------------------------------------------------------

    def _skip_breakdown(self):
        """Return ``[(label, count), ...]`` for the post-level filters.

        The order mirrors the Filters box top to bottom, so the block reads as
        a count for each filter in the order they are set. These follow the
        loaded list live; the file-level counters live in
        :meth:`_file_skip_breakdown`.
        """
        stats = getattr(self, "_post_skip_stats", {})
        return [
            (
                translate("summary_skip_post_keywords", stats.get("keywords", 0)),
                stats.get("keywords", 0),
            ),
            (
                translate("summary_skip_post_date", stats.get("date", 0)),
                stats.get("date", 0),
            ),
            (
                translate("summary_skip_post_file_count", stats.get("file_count", 0)),
                stats.get("file_count", 0),
            ),
            (
                translate("summary_skip_post_filetypes", stats.get("filetypes", 0)),
                stats.get("filetypes", 0),
            ),
        ]

    def _file_skip_breakdown(self):
        """Return ``[(label, count), ...]`` for the file-level filters.

        These count files, not posts, and are only decided when a download
        prepares them, so they move on a run rather than on a list change.
        """
        file_skips = getattr(self, "_file_skip_count", 0)
        images = getattr(self, "_images_skipped_count", 0)
        return [
            (translate("summary_skip_files", file_skips), file_skips),
            (translate("summary_skip_images", images), images),
        ]

    @staticmethod
    def _keyword_skip_lines(counts):
        """Return ``"  keyword: count"`` lines, most frequent first."""
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
        return [f"  {keyword}: {count}" for keyword, count in ordered]

    def _on_filetype_filter_changed(self, *_args):
        """Re-filter after a tick that the filetype filter depends on.

        The extension grid and "Download Post Text" both drive only "Filter
        posts with no selected filetypes": a tick while that box is clear
        cannot change which posts are listed, and rebuilding up to 200 rows for
        it was pure churn. A tick during a fetch is left to the fetch, which
        owns the list and runs its own pass; those inputs are disabled then.
        """
        checkbox = getattr(self, "filter_no_selected_filetypes_check", None)
        if checkbox is None or not checkbox.isChecked():
            return
        thread = getattr(self, "post_detection_thread", None)
        if thread is not None and thread.isRunning():
            return
        self.filter_items()

    def _schedule_filter_refresh(self):
        """Re-run the filter pass once a filter edit settles.

        Text fields change on every keystroke and each pass walks every post,
        so the timer is restarted rather than firing once per character. A
        fetch in progress owns the list and runs its own pass at the end.
        """
        thread = getattr(self, "post_detection_thread", None)
        if thread is not None and thread.isRunning():
            return
        if not self.all_detected_posts:
            # Nothing is loaded yet, so there is nothing to filter; the
            # fetch runs its own pass as soon as it finishes.
            return
        self._filter_debounce.start()

    def _connect_live_filters(self):
        """Make the Filters box re-filter the loaded list as it changes.

        Every post filter reads the facts stored during the fetch, so a change
        costs a filter pass instead of another fetch. Text fields are
        debounced; checkboxes and dates apply straight away.
        """
        self._filter_debounce = QTimer(self)
        self._filter_debounce.setSingleShot(True)
        self._filter_debounce.setInterval(350)
        self._filter_debounce.timeout.connect(self.filter_items)

        for editor in (
            self.skip_keywords_edit,
            self.date_from_edit,
            self.date_to_edit,
            self.file_count_from_edit,
            self.file_count_to_edit,
        ):
            editor.textChanged.connect(self._schedule_filter_refresh)

        for checkbox in self.skip_scope_checkboxes.values():
            checkbox.stateChanged.connect(self.filter_items)
        self.file_count_keep_compressed_check.stateChanged.connect(self.filter_items)
        self.filter_no_selected_filetypes_check.stateChanged.connect(self.filter_items)
        # Both feed the filetype rule, so they only re-filter while it is on.
        self.creator_download_text_check.stateChanged.connect(
            self._on_filetype_filter_changed
        )

    def _log_filter_warnings(self, warnings):
        """Say once when a filter entry cannot be read.

        The fetch has always warned about these; a live pass used to drop
        them, so a bogus date or count silently filtered nothing. Repeats
        are suppressed until the entry parses again.
        """
        previous = getattr(self, "_live_filter_warnings", set())
        for key in warnings:
            if key in previous:
                continue
            self.append_log_to_console(
                translate("log_warning", translate(key)),
                "WARNING",
            )
        self._live_filter_warnings = set(warnings)

    def _file_skip_keywords_from_widgets(self):
        """Return the parsed "Skip Files Containing" keywords."""
        raw = self.file_skip_keywords_edit.text().strip()
        if not raw:
            return []
        return [kw.strip() for kw in raw.split(",") if kw.strip()]

    def _keyword_matching_modes(self):
        """Return ``(posts_lenient, files_lenient, lenient_punctuation)``.

        Both switches live in Settings now. A missing getter (tests, no
        parent) falls back to the defaults, so the tab behaves exactly as it
        did before the settings existed.
        """
        settings_tab = getattr(self._parent, "settings_tab", None)
        mode_getter = getattr(settings_tab, "get_lenient_keyword_matching", None)
        mode = mode_getter() if callable(mode_getter) else "off"
        if mode not in ("off", "posts", "files", "both"):
            mode = "off"
        rules_getter = getattr(settings_tab, "get_punctuation_matching_rules", None)
        rules = rules_getter() if callable(rules_getter) else "default"
        return (
            mode in ("posts", "both"),
            mode in ("files", "both"),
            rules == "lenient",
        )

    def _post_filters_from_widgets(self):
        """Return ``(PostFilters, warnings)`` for the current Filters box.

        *warnings* holds the translation keys of entries that could not be
        read (a half-typed date, a non-numeric file count). The fetch logs
        them; a live pass stays quiet, because a bound that is still being
        typed should not nag on every keystroke.
        """
        raw_keywords = self.skip_keywords_edit.text().strip()
        if raw_keywords:
            skip_keywords = [kw.strip() for kw in raw_keywords.split(",") if kw.strip()]
        else:
            skip_keywords = []
        lenient_posts, _lenient_files, lenient_punctuation = (
            self._keyword_matching_modes()
        )

        warnings = []
        date_after = parse_filter_date(self.date_from_edit.text())
        if self.date_from_edit.text().strip() and date_after is None:
            warnings.append("invalid_date_from_ignored")
        date_before = parse_filter_date(self.date_to_edit.text())
        if self.date_to_edit.text().strip() and date_before is None:
            warnings.append("invalid_date_to_ignored")
        if date_after and date_before and date_after > date_before:
            date_after, date_before = date_before, date_after

        file_count_min = parse_filter_count(self.file_count_from_edit.text())
        if self.file_count_from_edit.text().strip() and file_count_min is None:
            warnings.append("invalid_file_count_ignored")
        file_count_max = parse_filter_count(self.file_count_to_edit.text())
        if self.file_count_to_edit.text().strip() and file_count_max is None:
            warnings.append("invalid_file_count_ignored")
        if (
            file_count_min is not None
            and file_count_max is not None
            and file_count_min > file_count_max
        ):
            file_count_min, file_count_max = file_count_max, file_count_min

        filters = PostFilters(
            skip_keywords=tuple(skip_keywords),
            skip_scopes=frozenset(
                scope
                for scope, checkbox in self.skip_scope_checkboxes.items()
                if checkbox.isChecked()
            ),
            lenient_keywords=lenient_posts,
            lenient_punctuation=lenient_punctuation,
            date_after=date_after,
            date_before=date_before,
            file_count_min=file_count_min,
            file_count_max=file_count_max,
            keep_compressed=self.file_count_keep_compressed_check.isChecked(),
            required_filetypes=self._required_filetypes(),
            download_post_text=self.creator_download_text_check.isChecked(),
        )
        return filters, warnings

    def _selected_extensions(self):
        """Return the ticked file-extension boxes as a plain list.

        Called on the GUI thread so download workers can be handed a snapshot
        instead of reading checkboxes from a foreign thread.
        """
        return [
            str(ext).lower()
            for ext, box in getattr(self, "creator_ext_checks", {}).items()
            if box.isChecked()
        ]

    def _clear_filetype_selection(self):
        """Untick every filetype box without firing a pass per box.

        Used when the view is reset (clearing the queue): a tick that survives
        a creator it was meant for is a filter nobody asked for any more.
        """
        for box in getattr(self, "creator_ext_checks", {}).values():
            if box.isChecked():
                box.blockSignals(True)
                box.setChecked(False)
                box.blockSignals(False)
        self._render_creator_ext_checks()

    def _required_filetypes(self):
        """Return the filetypes the post filter must find.

        None while "Filter posts without selected filetypes" is off. An empty
        frozenset means the filter is on with nothing ticked: there is no type
        any post could hold, so the list is deliberately empty rather than
        showing everything.
        """
        checkbox = getattr(self, "filter_no_selected_filetypes_check", None)
        if checkbox is None or not checkbox.isChecked():
            return None
        return frozenset(
            ext.lower()
            for ext, box in getattr(self, "creator_ext_checks", {}).items()
            if box.isChecked()
        )

    def _reset_found_extensions(self):
        """Forget the file types collected for the previous creator.

        The collected types describe one creator's posts, so they must never
        outlive it: an empty view showing the last creator's types would keep
        extension boxes hidden for files that no longer exist.
        """
        self._found_type_counts = {}
        self._render_creator_ext_checks()

    def _render_creator_ext_checks(self):
        """Re-lay the file-extension boxes, hiding unused types.

        With "Filetype Display" set to "Show found only", boxes for extensions
        this creator has no files of are dropped from the grid, so the list
        reflects the creator instead of the whole catalogue; "Show found only
        (with counts)" also appends each type's file count. A
        ticked box is always kept: hiding an active filter would silently
        change what gets downloaded. Before detection has filled the shared
        tally there is nothing to compare against, so every box stays visible.
        """
        layout = getattr(self, "_creator_ext_layout", None)
        if layout is None:
            return
        mode = getattr(self, "_found_filetypes_mode", "off")
        only_found = mode != "off"
        show_counts = mode == "on_with_count"
        found = getattr(self, "_found_type_counts", None) or {}
        base_labels = getattr(self, "_creator_ext_base_labels", {})

        # Empty the grid first; the dict still owns the checkboxes.
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setVisible(False)

        row = 0
        column = 0
        shown = 0
        for ext, checkbox in self.creator_ext_checks.items():
            unused = ext not in found and not checkbox.isChecked()
            if only_found and unused:
                continue
            label = base_labels.get(ext, checkbox.text())
            if show_counts and ext in found:
                checkbox.setText(f"{label} ({found[ext]})")
            elif label:
                checkbox.setText(label)
            checkbox.setVisible(True)
            layout.addWidget(checkbox, row, column)
            column += 1
            shown += 1
            if column == 5:
                column = 0
                row += 1

        # An enabled filter with nothing to compare against shows no boxes at
        # all rather than the whole catalogue, with a hint saying why.
        empty_label = getattr(self, "creator_ext_empty_label", None)
        if empty_label is not None:
            empty_label.setVisible(shown == 0)
            if shown == 0:
                layout.addWidget(empty_label, 0, 0, 1, 5)

    def _skip_tooltip(self):
        """Tooltip listing how many posts each skip keyword dropped."""
        lines = []
        if self._post_keyword_skip_counts:
            lines.append(translate("skip_tooltip_post_keywords"))
            lines.extend(self._keyword_skip_lines(self._post_keyword_skip_counts))
        return "\n".join(lines) if lines else translate("skip_tooltip_no_keywords")

    def _file_skip_tooltip(self):
        """Tooltip for the file row: keyword counts, then what is per-run.

        The keyword part mirrors the posts tooltip, including the "no skips"
        line, so both rows read the same way.
        """
        if self._file_keyword_skip_counts:
            lines = [translate("skip_tooltip_file_keywords")]
            lines.extend(self._keyword_skip_lines(self._file_keyword_skip_counts))
        else:
            lines = [translate("skip_tooltip_no_keywords")]
        lines.append(translate("skip_tooltip_files_note"))
        return "\n".join(lines)

    def _skip_line(self, total_key, breakdown):
        """Render one summary row, with the colour it deserves."""
        total = sum(count for _label, count in breakdown)
        parts = [translate(total_key, total)]
        parts.append(" · ".join(label for label, _count in breakdown))
        return " &nbsp; ".join(parts), self._skip_colour(total)

    def _skip_colour(self, total):
        """Green once something was skipped, sand when nothing was, else white.

        White is the resting state: there is no list yet, so nothing has been
        determined.
        """
        if not self.all_detected_posts:
            return "white"
        return "#7BD88F" if total else "#E5C07B"

    def _failed_post_count(self):
        """How many distinct posts the run's failed files belong to."""
        failed = getattr(self, "failed_files", None) or {}
        if not failed:
            return 0
        for mapping in (
            getattr(self, "files_to_posts_map", None) or {},
            getattr(self, "_last_run_files_to_posts_map", None) or {},
        ):
            posts = {mapping[url] for url in failed if url in mapping}
            if posts:
                return len(posts)
        return 0

    def _update_download_summary(
        self, completed=None, failed=None, refresh_skips=False
    ):
        """Refresh the stat block under the progress bars.

        The skip breakdown only changes when a filter or the file preparation
        runs, so it is cached and reused for the per-file progress updates.
        """
        if completed is None:
            completed = len(self.completed_files)
        if failed is None:
            failed = len(self.failed_files)

        failed_text = translate("summary_failed", failed)
        if failed:
            # One post with several failed files used to read like the same file
            # counted again and again: name the post count as well.
            failed_posts = self._failed_post_count()
            if failed_posts:
                failed_text = translate(
                    (
                        "summary_failed_files_one_post"
                        if failed_posts == 1
                        else "summary_failed_files_posts"
                    ),
                    failed,
                    failed_posts,
                )

        self.creator_download_summary_label.setText(
            " &nbsp; ".join(
                [
                    "<span style='color:#7BD88F'>{}</span>".format(
                        translate("summary_downloaded", completed)
                    ),
                    "<span style='color:{}'>{}</span>".format(
                        "#E06C75" if failed else "#7BD88F", failed_text
                    ),
                ]
            )
        )

        if refresh_skips or self._skip_summary_cache is None:
            # Always list every filter, zeros included, so each row is
            # readable even before anything has been skipped.
            self._skip_summary_cache = {
                "posts": self._skip_line(
                    "summary_skipped_posts", self._skip_breakdown()
                )
                + (self._skip_tooltip(),),
                "files": self._skip_line(
                    "summary_skipped_files", self._file_skip_breakdown()
                )
                + (self._file_skip_tooltip(),),
            }

        for label, key in (
            (self.creator_skip_summary_label, "posts"),
            (self.creator_skip_files_label, "files"),
        ):
            text, colour, tip = self._skip_summary_cache[key]
            label.setText(text)
            label.setToolTip(tip)
            sheet = f"color: {colour};"
            if label.styleSheet() != sheet:
                label.setStyleSheet(sheet)

    def _reset_download_summary(self, keep_post_stats=False, keep_run_failures=False):
        """Reset the run stats.

        *keep_post_stats* keeps the per-filter post counts (they describe the
        loaded list, not the run). *keep_run_failures* keeps the last run's
        failures so Retry Failed Downloads survives, which matters when a
        settings change - not a new run - is what triggers the reset.
        """
        self._skip_summary_cache = None
        if not keep_run_failures:
            self._file_skip_count = 0
            self._images_skipped_count = 0
            self._last_run_failed_files = {}
            self._last_run_files_to_posts_map = {}
        self._refresh_retry_button()

        if not keep_post_stats:
            # A new download keeps the post-filter skip counts: they describe
            # the post list, not the run.
            self._post_skip_stats = {
                "keywords": 0,
                "date": 0,
                "file_count": 0,
                "filetypes": 0,
            }
            self._post_keyword_skip_counts = {}
        if not keep_run_failures:
            self._file_keyword_skip_counts = {}

        # Re-render rather than blank the block: the skip breakdown stays
        # visible at all times, showing zeros when nothing has been skipped.
        self._update_download_summary(refresh_skips=True)

    def _download_in_progress(self):
        """True while a download run is genuinely in flight.

        The ``downloading`` flag alone is not enough: it is cleared as soon as
        the last file reports back, which can be a beat before the
        CreatorDownloadThread itself finishes.
        """
        thread = getattr(self, "_download_thread", None)
        if thread is not None:
            try:
                if thread.isRunning():
                    return True
            except RuntimeError:  # C++ object already deleted
                pass
        return bool(getattr(self, "downloading", False))

    def _refresh_retry_button(self):
        """Grey the retry button out unless the last run left retryable work."""
        button = getattr(self, "creator_retry_failed_btn", None)
        if button is None:
            return
        retryable = len(getattr(self, "_last_run_files_to_posts_map", {}))
        button.setText(translate("retry_failed_downloads"))
        button.setEnabled(retryable > 0 and not self._download_in_progress())
        button.setToolTip(
            translate("retry_failed_downloads_tooltip")
            if retryable
            else translate("retry_unavailable")
        )

    def _refresh_open_folder_button(self):
        """Grey the folder button out until this run's creator folder exists."""
        button = getattr(self, "creator_open_folder_btn", None)
        if button is None:
            return
        folder = getattr(self, "_current_creator_folder", None)
        ready = bool(folder) and os.path.isdir(folder)
        button.setText(translate("open_creator_folder"))
        button.setEnabled(ready)
        button.setToolTip(
            translate("open_creator_folder_tooltip")
            if ready
            else translate("open_creator_folder_waiting")
        )

    def _on_creator_folder_ready(self, folder):
        """The run just confirmed (and created) its creator folder."""
        self._current_creator_folder = folder
        self._refresh_open_folder_button()

    def _open_creator_folder(self):
        """Open this run's creator folder in the system file browser."""
        folder = getattr(self, "_current_creator_folder", None)
        if not folder:
            return
        if not os.path.isdir(folder):
            # Deleted or moved while the app was running.
            self.append_log_to_console(
                translate(
                    "log_warning", translate("open_creator_folder_missing", folder)
                ),
                "WARNING",
            )
            self._current_creator_folder = None
            self._refresh_open_folder_button()
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _remember_run_failures(self):
        """Snapshot the failures of the run about to be reset, for retrying."""
        self._last_run_failed_files = dict(self.failed_files)
        known_map = getattr(self, "files_to_posts_map", {})
        self._last_run_files_to_posts_map = {
            url: known_map[url]
            for url in self._last_run_failed_files
            if url in known_map
        }
        self._refresh_retry_button()

    def _refresh_skip_summary_from_filter(self, detection_thread):
        """Copy the post-filter skip counters into the summary block."""
        self._post_skip_stats = {
            "keywords": getattr(detection_thread, "keyword_skipped_count", 0),
            "date": getattr(detection_thread, "date_skipped_count", 0),
            "file_count": getattr(detection_thread, "file_count_skipped_count", 0),
            "filetypes": getattr(detection_thread, "filetype_skipped_count", 0),
        }
        self._post_keyword_skip_counts = dict(
            getattr(detection_thread, "keyword_skip_counts", {}) or {}
        )
        self._update_download_summary(refresh_skips=True)

    def _log_facts_missing(self):
        """Say when some posts have no stored details to filter on.

        That only happens when a failed fetch fell back to the in-memory list,
        which never held post payloads. Those posts are kept rather than
        dropped, so say it once per change instead of quietly listing
        everything.
        """
        thread = getattr(self, "filter_thread", None)
        missing = getattr(thread, "facts_missing_count", 0) if thread else 0
        if missing and missing != getattr(self, "_last_facts_missing", 0):
            self.append_log_to_console(
                translate(
                    "log_info",
                    translate("posts_without_details_not_filtered", missing),
                ),
                "INFO",
            )
        self._last_facts_missing = missing

    def retry_failed_downloads(self):
        """Re-download only the files that failed in the last run."""
        if self._download_in_progress():
            self.append_log_to_console(
                translate("log_warning", translate("retry_already_downloading")),
                "WARNING",
            )
            return

        failed = dict(getattr(self, "_last_run_failed_files", {}))
        known_map = getattr(self, "_last_run_files_to_posts_map", {})
        files_map = {url: known_map[url] for url in failed if url in known_map}
        if not failed or not files_map:
            self.append_log_to_console(
                translate("log_warning", translate("retry_unavailable")), "WARNING"
            )
            self._refresh_retry_button()
            return

        files_to_retry = list(files_map)
        self.downloading = True
        self._run_finished = False
        self.set_downloading_ui_state(True)
        self._refresh_retry_button()
        self.total_files_to_download = len(files_to_retry)
        self.total_posts_to_download = len(set(files_map.values()))
        self.completed_files.clear()
        self.failed_files.clear()
        self.completed_posts.clear()
        self.current_file_index = -1
        self.creator_file_progress.setValue(0)
        self.creator_file_progress_label.setText(translate("file_progress", 0))
        self.creator_overall_progress.setValue(0)
        self.update_progress_bar_style()
        self._update_download_summary(0, 0)
        self.append_log_to_console(
            translate(
                "log_warning", translate("retrying_failed_files", len(files_to_retry))
            ),
            "WARNING",
        )
        self._start_download_thread(
            files_to_retry,
            files_map,
            getattr(self, "_last_run_creator_url", None),
            # Reuse the numbers the first run decided for these files.
            file_numbers=dict(getattr(self, "_last_run_file_numbers", {})),
            post_file_counts=dict(getattr(self, "_last_run_post_file_counts", {})),
        )

    def add_creators_from_file(self):
        """Open a text file and add all links line by line to the queue"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            translate("select_links_file"),
            "",
            "Text Files (*.txt);;All Files (*)",
        )

        if not file_path:
            return

        try:
            with open(file_path, "r", encoding="utf-8") as file:
                lines = file.readlines()

            added_count = 0
            skipped_count = 0

            for line in lines:
                original_url = line.strip()

                # Skip empty lines
                if not original_url:
                    continue

                # Same normalisation, validation and duplicate rule as the
                # queue's input row; the list is rebuilt once at the end.
                if self._queue_creator_url(original_url, refresh=False) == "added":
                    added_count += 1
                else:
                    skipped_count += 1

            self.update_creator_queue_list(scroll=True)

            # Show summary message
            summary = translate("bulk_add_summary", added_count, skipped_count)
            self.append_log_to_console(translate("log_info", summary), "INFO")
            QMessageBox.information(self, translate("bulk_add_complete"), summary)

        except Exception as e:
            error_msg = translate("file_read_error", str(e))
            self.append_log_to_console(translate("log_error", error_msg), "ERROR")
            QMessageBox.critical(self, translate("file_read_error_title"), error_msg)


class CancellationThread(_StoppableThread, QThread):
    finished = pyqtSignal()
    log = pyqtSignal(str, str)

    def __init__(self, threads):
        super().__init__()
        self.threads = threads
        self.is_running = True

    def run(self):
        if not self.is_running:
            return
        self.log.emit(
            translate("log_info", translate("starting_cancellation_of_active_threads")),
            "INFO",
        )
        # Signal all threads to stop
        for thread in self.threads:
            if hasattr(thread, "stop"):
                try:
                    thread.stop()
                    self.log.emit(
                        translate(
                            "log_debug",
                            translate(
                                "signaled_stop_for_thread", thread.__class__.__name__
                            ),
                        ),
                        "DEBUG",
                    )
                except RuntimeError:
                    self.log.emit(
                        translate(
                            "log_warning",
                            translate(
                                "thread_already_deleted", thread.__class__.__name__
                            ),
                        ),
                        "WARNING",
                    )

        # Wait for threads to exit gracefully
        timeout = 5.0  # Maximum wait time in seconds
        start_time = time.time()
        while (
            any(
                thread.isRunning()
                for thread in self.threads
                if hasattr(thread, "isRunning")
            )
            and time.time() - start_time < timeout
        ):
            try:
                time.sleep(0.1)  # Short sleep to avoid freezing
            except RuntimeError:
                self.log.emit(
                    translate(
                        "log_warning",
                        translate("thread_deleted_during_cancellation_wait"),
                    ),
                    "WARNING",
                )

        # Log any threads that are still running
        for thread in self.threads:
            try:
                if hasattr(thread, "isRunning") and thread.isRunning():
                    self.log.emit(
                        translate(
                            "log_warning",
                            translate(
                                "thread_not_exited_gracefully",
                                thread.__class__.__name__,
                            ),
                        ),
                        "WARNING",
                    )
                    try:
                        thread.terminate()
                        thread.wait()
                        self.log.emit(
                            translate(
                                "log_info",
                                translate(
                                    "terminated_thread", thread.__class__.__name__
                                ),
                            ),
                            "INFO",
                        )
                    except RuntimeError:
                        self.log.emit(
                            translate(
                                "log_warning",
                                translate(
                                    "thread_already_deleted_during_termination",
                                    thread.__class__.__name__,
                                ),
                            ),
                            "WARNING",
                        )
            except RuntimeError:
                self.log.emit(
                    translate(
                        "log_warning",
                        translate("thread_already_deleted", thread.__class__.__name__),
                    ),
                    "WARNING",
                )

        self.log.emit(
            translate("log_info", translate("cancellation_process_completed")), "INFO"
        )

        if self.is_running:
            self.finished.emit()
