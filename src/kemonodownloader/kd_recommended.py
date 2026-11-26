"""Find the words and tags that repeat across a creator's loaded posts.

The Creator tab already holds every fact this module needs: titles come from
its post rows, and tags, descriptions and file names come from the per-post
index it built while fetching.  A scan is therefore local -- no request is
made -- and nothing here needs Qt, so the counting rules can be tested on
their own.

A phrase is a run of word tokens taken from one field of one post.  Tokens
only join a phrase when the text between them is whitespace, so every phrase
is a literal substring of the field it came from.  That keeps a suggested
keyword usable by the tab's existing literal search and skip matchers.
Tags are used as whole values: a tag *is* the phrase the user means.

Counting is per post, not per occurrence: a word repeated ten times in one
description, or present in both the title and a tag, still counts once.
The raw occurrence total is reported alongside it as ``mentions``.
"""

import os
import re
import unicodedata
from collections import Counter
from typing import NamedTuple

# One post's description can be very long.  Only the first few hundred tokens
# are scanned: titles and tags carry the signal, and the cap keeps a library
# of huge HTML bodies from turning a refresh into a visible wait.
MAX_TOKENS_PER_FIELD = 400

SCOPES = frozenset({"title", "tags", "description", "filenames"})
DEFAULT_SCOPES = frozenset({"title", "tags"})

# Unicode word characters, underscore excluded.  An apostrophe stays inside a
# word, so "don't" is one token instead of the orphan "don" plus "t".
_WORD_RE = re.compile(r"[^\W_]+(?:['\u2019][^\W_]+)*")

# Links, e-mail addresses and @handles carry no keyword signal.  They are
# replaced with a sentence break so no phrase can span them.
_URL_RE = re.compile(
    r"(?:https?://|ftp://|www\.)\S+|\b[\w.+-]+@[\w-]+\.[\w.-]+\b|(?<!\w)@\w+",
    re.IGNORECASE,
)

# CamelCase and acronym boundaries used by file names: BlackCat -> Black Cat,
# JPArt -> JP Art.
_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")

# Only the Latin combining diacriticals are folded.  Stripping every combining
# mark would break Japanese kana: the dakuten turns ブ into フ.
_LATIN_DIACRITICS_RE = re.compile(r"[\u0300-\u036f]")

# Function words that make a keyword useless for filtering.  Matching is done
# on the normalized key, so the apostrophe spelling is the straight one.
STOPWORDS = frozenset(
    """
    a about after again against all also am an and any are as at be because
    been before being below between both but by can could did do does doing
    down during each few for from further had has have having he her here hers
    herself him himself his how i if in into is it its itself just me more most
    my myself no nor not now of off on once only or other our ours ourselves
    out over own same she should so some such than that the their theirs them
    themselves then there these they this those through to too under until up
    very was we were what when where which while who whom why will with would
    you your yours yourself yourselves
    don't doesn't didn't isn't aren't wasn't weren't can't couldn't won't
    wouldn't shouldn't hasn't haven't hadn't mustn't needn't i'm i've i'll i'd
    you're you've you'll you'd he's she's it's we're we've they're they've
    that's there's what's let's
    """.split()
)


class RecommendedKeyword(NamedTuple):
    """One repeated keyword.

    ``keyword`` is the most common original spelling and ``match_key`` is the
    case-folded key the spellings were counted under (for a file name phrase
    the two differ: ``BlackCat`` is displayed, ``black cat`` is the key).
    ``count`` is the number of posts the keyword appears in and ``mentions``
    is the raw occurrence total.  ``variants`` holds every spelling seen for
    the key, so a caller applying the keyword can match all of them.
    """

    keyword: str
    count: int
    mentions: int
    scopes: frozenset
    match_key: str
    variants: tuple = ()


def normalize_key(value, ignore_accents=False):
    """Return the case-folded grouping key for *value*.

    NFKC folds width/compatibility variants, casefold handles case, and the
    optional accent fold merges ``café`` with ``cafe``.  The original spelling
    is kept separately for display and for applying the keyword.
    """
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u2019", "'").casefold()
    if ignore_accents:
        text = _fold_latin_accents(text)
    return re.sub(r"\s+", " ", text).strip()


def _fold_latin_accents(value):
    """Strip Latin combining diacritics without touching kana."""
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = _LATIN_DIACRITICS_RE.sub("", decomposed)
    return unicodedata.normalize("NFC", stripped)


def _token_spans(text):
    """Return ``(surface, start, end)`` for every word token in *text*."""
    return [
        (match.group(), match.start(), match.end()) for match in _WORD_RE.finditer(text)
    ]


def _chains(spans, text):
    """Split tokens into phrases: only whitespace may sit between words.

    Punctuation is therefore a hard boundary (``sci-fi`` never becomes
    ``sci fi``), and a dropped token (a pure number, a single character)
    ends the current chain so ``page 3 art`` does not become ``page art``.
    """
    chains = []
    current = []
    for index, (token, start, end) in enumerate(spans):
        if index and text[spans[index - 1][2] : start].strip():
            chains.append(current)
            current = []
        if len(token) >= 2 and not token.isdigit():
            current.append((token, start, end))
        else:
            chains.append(current)
            current = []
    chains.append(current)
    return [chain for chain in chains if chain]


def _phrase_is_noise(keys, ignore_common_words):
    """True when a stopword sits at a phrase edge (or is the whole phrase)."""
    if not ignore_common_words:
        return False
    if len(keys) == 1:
        return keys[0] in STOPWORDS
    return keys[0] in STOPWORDS or keys[-1] in STOPWORDS


def _window_candidates(text, chains, max_words, ignore_common_words, ignore_accents):
    """Yield ``(surface, key)`` for every 1..max_words window in *chains*."""
    for chain in chains:
        for size in range(1, max_words + 1):
            for index in range(len(chain) - size + 1):
                window = chain[index : index + size]
                keys = [
                    normalize_key(token, ignore_accents)
                    for token, _start, _end in window
                ]
                if _phrase_is_noise(keys, ignore_common_words):
                    continue
                surface = text[window[0][1] : window[-1][2]]
                yield surface, " ".join(keys)


def _text_candidates(text, max_words, ignore_common_words, ignore_accents):
    """Yield the title/description phrases of one field."""
    cleaned = _URL_RE.sub(" . ", str(text or ""))
    spans = _token_spans(cleaned)[:MAX_TOKENS_PER_FIELD]
    yield from _window_candidates(
        cleaned,
        _chains(spans, cleaned),
        max_words,
        ignore_common_words,
        ignore_accents,
    )


def _filename_stem(name):
    """Return a file name without its extension; ignore query strings."""
    path = str(name or "").split("?")[0].strip()
    return os.path.splitext(path)[0]


def _camel_pieces(run, offset):
    """Split one alphanumeric run at camel/acronym boundaries.

    Offsets stay absolute within the stem, so a phrase's surface can be cut
    straight out of the original name and still match it literally.
    """
    pieces = []
    start = 0
    for match in _CAMEL_BOUNDARY_RE.finditer(run):
        cut = match.start()
        if cut > start:
            pieces.append((run[start:cut], offset + start, offset + cut))
        start = cut
    if start < len(run):
        pieces.append((run[start:], offset + start, offset + len(run)))
    return pieces


def _filename_candidates(names, max_words, ignore_common_words, ignore_accents):
    """Yield the phrases of every file name, one stem at a time."""
    for name in names or ():
        stem = _filename_stem(name)
        if not stem:
            continue
        chains = []
        for run in _WORD_RE.finditer(stem):
            chains.extend(_chains(_camel_pieces(run.group(), run.start()), stem))
        yield from _window_candidates(
            stem,
            chains,
            max_words,
            ignore_common_words,
            ignore_accents,
        )


def _tag_candidates(facts):
    """Yield one phrase per tag value, exactly as the site returned it."""
    tags = facts.get("tag_list")
    if tags is None:
        # The index stores the legacy fallback as space-joined lower-case tags.
        tags = str(facts.get("tags") or "").split()
    elif isinstance(tags, str):
        tags = tags.split(",")
    for tag in tags or ():
        surface = str(tag).strip()
        if surface:
            yield surface, normalize_key(surface)


def _ordered_variants(counter):
    """Every spelling seen for one key, most common first."""
    ordered = sorted(
        counter.items(), key=lambda item: (-item[1], item[0].casefold(), item[0])
    )
    return tuple(surface for surface, _amount in ordered)


def count_recommended_keywords(
    post_rows,
    post_search_index=None,
    scopes=None,
    min_count=2,
    max_words=3,
    ignore_common_words=True,
    ignore_accents=False,
    limit=300,
    cancel=None,
):
    """Return the keywords repeated across *post_rows*.

    ``post_rows`` is an iterable of ``(post_id, title)`` pairs and
    ``post_search_index`` is the tab's ``post_id -> facts`` mapping.  Only
    posts with an index entry can contribute non-title facts; a title alone
    still counts, which is why posts without details are not skipped.

    ``min_count`` is an inclusive lower bound on the number of distinct posts
    a keyword must appear in.  ``limit`` caps the returned list; ``None`` or 0
    returns every match.  *cancel* is polled between posts so a worker can
    abandon a scan quickly; an abandoned scan returns an empty list.
    """
    index = post_search_index if isinstance(post_search_index, dict) else {}
    wanted = {str(scope) for scope in (scopes or ())} & SCOPES
    if not wanted:
        wanted = {"title"}
    max_words = max(1, int(max_words or 1))
    min_count = max(1, int(min_count or 1))

    post_counts = Counter()
    mention_counts = Counter()
    surfaces = {}
    hit_scopes = {}
    seen_post_ids = set()

    for post_id, title in post_rows:
        if cancel is not None and cancel():
            return []
        post_key = str(post_id)
        if post_key in seen_post_ids:
            continue
        seen_post_ids.add(post_key)
        facts = index.get(str(post_id))
        if not isinstance(facts, dict):
            facts = index.get(post_id)
        if not isinstance(facts, dict):
            facts = {}

        candidates = []
        if "title" in wanted:
            text = str(title or "").strip()
            # A post with no title arrives as the API fallback "Post <id>";
            # counting that would make "post" look like the most common word
            # in the whole view.
            if text and text.casefold() != f"post {post_id}".casefold():
                candidates.extend(
                    (surface, key, "title")
                    for surface, key in _text_candidates(
                        text, max_words, ignore_common_words, ignore_accents
                    )
                )
        if "description" in wanted:
            candidates.extend(
                (surface, key, "description")
                for surface, key in _text_candidates(
                    facts.get("description") or "",
                    max_words,
                    ignore_common_words,
                    ignore_accents,
                )
            )
        if "filenames" in wanted:
            candidates.extend(
                (surface, key, "filenames")
                for surface, key in _filename_candidates(
                    facts.get("filenames_list") or (),
                    max_words,
                    ignore_common_words,
                    ignore_accents,
                )
            )
        if "tags" in wanted:
            candidates.extend(
                (surface, key, "tags") for surface, key in _tag_candidates(facts)
            )

        seen = set()
        for surface, key, scope in candidates:
            mention_counts[key] += 1
            if key in seen:
                continue
            seen.add(key)
            post_counts[key] += 1
            surfaces.setdefault(key, Counter())[surface] += 1
            hit_scopes.setdefault(key, set()).add(scope)

    results = []
    for key, count in post_counts.items():
        if count < min_count:
            continue
        variants = _ordered_variants(surfaces.get(key))
        results.append(
            RecommendedKeyword(
                variants[0],
                count,
                mention_counts[key],
                frozenset(hit_scopes.get(key, ())),
                key,
                variants,
            )
        )

    results.sort(
        key=lambda item: (
            -item.count,
            -len(item.match_key.split()),
            item.match_key,
        )
    )
    if limit:
        return results[: max(0, int(limit))]
    return results
