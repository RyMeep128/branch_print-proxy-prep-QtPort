import base64
import hashlib
import json
import os
from collections import OrderedDict
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

from config import CFG
from constants import cwd
from image import image_from_bytes
import util

GOOGLE_DRIVE_IMAGE_API_URL = (
    "https://script.google.com/macros/s/"
    "AKfycbw8laScKBfxda2Wb0g63gkYDBdy8NWNxINoC4xDOwnCQ3JMFdruam1MdmNmN4wI5k4/exec"
)

MPCFILL_SOURCE_IDS = (
    list(range(1, 44))
    + list(range(45, 100))
    + list(range(101, 122))
    + list(range(123, 132))
    + list(range(133, 208))
    + list(range(209, 255))
    + list(range(256, 279))
)


@dataclass(frozen=True)
class CardContext:
    filename: str
    query: str
    display_name: str
    set_code: str | None = None
    collector_number: str | None = None


@dataclass(frozen=True)
class HighResCandidate:
    identifier: str
    name: str
    dpi: int
    extension: str
    download_link: str
    small_thumbnail_url: str
    medium_thumbnail_url: str
    source_id: int
    source_name: str


@dataclass(frozen=True)
class HighResSearchPage:
    candidates: list[HighResCandidate]
    total_count: int
    page_start: int
    page_size: int


@dataclass(frozen=True)
class BacksideMatch:
    filename: str
    candidate: HighResCandidate


class _ApproximateLRUCache:
    def __init__(self, max_bytes_getter: Callable[[], int], ttl_seconds_getter: Callable[[], int]):
        self._entries: OrderedDict[tuple, tuple[float, object, int]] = OrderedDict()
        self._current_bytes = 0
        self._max_bytes_getter = max_bytes_getter
        self._ttl_seconds_getter = ttl_seconds_getter

    def clear(self):
        self._entries.clear()
        self._current_bytes = 0

    def get(self, key: tuple):
        now = time.time()
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value, size = entry
        if now >= expires_at:
            del self._entries[key]
            self._current_bytes -= size
            return None
        self._entries.move_to_end(key)
        return value

    def set(self, key: tuple, value, size: int):
        expires_at = time.time() + max(1, int(self._ttl_seconds_getter()))
        old = self._entries.pop(key, None)
        if old is not None:
            self._current_bytes -= old[2]
        self._entries[key] = (expires_at, value, max(0, int(size)))
        self._entries.move_to_end(key)
        self._current_bytes += max(0, int(size))
        self._evict_if_needed()

    def _evict_if_needed(self):
        self._purge_expired()
        max_bytes = max(1, int(self._max_bytes_getter()))
        while self._current_bytes > max_bytes and self._entries:
            _key, (_expires_at, _value, size) = self._entries.popitem(last=False)
            self._current_bytes -= size

    def _purge_expired(self):
        now = time.time()
        expired_keys = [
            key for key, (expires_at, _value, _size) in self._entries.items()
            if now >= expires_at
        ]
        for key in expired_keys:
            _expires_at, _value, size = self._entries.pop(key)
            self._current_bytes -= size


def _ttl_seconds() -> int:
    return max(1, int(getattr(CFG, "HighResCacheTTLSeconds", 60 * 60)))


def _search_cache_limit_bytes() -> int:
    return max(1, int(getattr(CFG, "HighResSearchCacheMemoryMB", 24)) * 1024 * 1024)


def _image_cache_limit_bytes() -> int:
    return max(1, int(getattr(CFG, "HighResImageCacheMemoryMB", 64)) * 1024 * 1024)


_SEARCH_PAGE_CACHE = _ApproximateLRUCache(_search_cache_limit_bytes, _ttl_seconds)
_IMAGE_CACHE = _ApproximateLRUCache(_image_cache_limit_bytes, _ttl_seconds)
_DOUBLE_FACE_CONTEXT_CACHE = _ApproximateLRUCache(lambda: 1024 * 1024, _ttl_seconds)


def _high_res_cache_root() -> str:
    return os.path.join(cwd, ".high_res_cache")


def _high_res_cache_dir(kind: str) -> str:
    return os.path.join(_high_res_cache_root(), kind)


def _ensure_cache_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _cache_filename_for_key(key: tuple) -> str:
    payload = json.dumps(key, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _disk_cache_paths(kind: str, key: tuple) -> tuple[str, str]:
    cache_dir = _high_res_cache_dir(kind)
    cache_name = _cache_filename_for_key(key)
    return (
        os.path.join(cache_dir, cache_name + ".json"),
        os.path.join(cache_dir, cache_name + ".bin"),
    )


def _purge_disk_cache_file(metadata_path: str, data_path: str | None = None):
    for path in [metadata_path, data_path]:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _read_disk_json_cache(kind: str, key: tuple):
    metadata_path, data_path = _disk_cache_paths(kind, key)
    if not os.path.exists(metadata_path):
        return None

    try:
        with open(metadata_path, "r", encoding="utf-8") as fp:
            metadata = json.load(fp)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        _purge_disk_cache_file(metadata_path, data_path)
        return None

    expires_at = metadata.get("expires_at")
    if not isinstance(expires_at, (int, float)) or time.time() >= float(expires_at):
        _purge_disk_cache_file(metadata_path, data_path)
        return None

    return metadata.get("payload")


def _write_disk_json_cache(kind: str, key: tuple, payload):
    cache_dir = _high_res_cache_dir(kind)
    _ensure_cache_dir(cache_dir)
    metadata_path, _data_path = _disk_cache_paths(kind, key)
    metadata = {
        "expires_at": time.time() + _ttl_seconds(),
        "payload": payload,
    }
    try:
        util.write_json_atomic(metadata_path, metadata, ensure_ascii=False)
    except OSError:
        pass


def _read_disk_bytes_cache(kind: str, key: tuple) -> bytes | None:
    metadata_path, data_path = _disk_cache_paths(kind, key)
    if not os.path.exists(metadata_path) or not os.path.exists(data_path):
        _purge_disk_cache_file(metadata_path, data_path)
        return None

    try:
        with open(metadata_path, "r", encoding="utf-8") as fp:
            metadata = json.load(fp)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        _purge_disk_cache_file(metadata_path, data_path)
        return None

    expires_at = metadata.get("expires_at")
    if not isinstance(expires_at, (int, float)) or time.time() >= float(expires_at):
        _purge_disk_cache_file(metadata_path, data_path)
        return None

    try:
        with open(data_path, "rb") as fp:
            return fp.read()
    except OSError:
        _purge_disk_cache_file(metadata_path, data_path)
        return None


def _write_disk_bytes_cache(kind: str, key: tuple, payload: bytes):
    cache_dir = _high_res_cache_dir(kind)
    _ensure_cache_dir(cache_dir)
    metadata_path, data_path = _disk_cache_paths(kind, key)
    try:
        with open(data_path, "wb") as fp:
            fp.write(payload)
        util.write_json_atomic(
            metadata_path,
            {"expires_at": time.time() + _ttl_seconds()},
        )
    except OSError:
        _purge_disk_cache_file(metadata_path, data_path)


def _clear_disk_cache(kind: str):
    cache_dir = _high_res_cache_dir(kind)
    if not os.path.exists(cache_dir):
        return
    for entry in os.listdir(cache_dir):
        path = os.path.join(cache_dir, entry)
        if os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass


def _build_search_cache_key(
    backend_url: str,
    query: str,
    min_dpi: int,
    max_dpi: int,
    page_start: int,
    page_size: int,
    source_ids: list[int] | None,
) -> tuple:
    return (
        _standardize_url(backend_url).strip().lower(),
        query.strip().casefold(),
        int(min_dpi),
        int(max_dpi),
        int(page_start),
        int(page_size),
        tuple(source_ids or MPCFILL_SOURCE_IDS),
    )


def clear_search_cache():
    _SEARCH_PAGE_CACHE.clear()
    _clear_disk_cache("search")


def clear_image_cache():
    _IMAGE_CACHE.clear()
    _clear_disk_cache("image")


def clear_double_face_cache():
    _DOUBLE_FACE_CONTEXT_CACHE.clear()


def clear_all_high_res_caches():
    clear_search_cache()
    clear_image_cache()
    clear_double_face_cache()


def _page_size_bytes(page: "HighResSearchPage") -> int:
    payload = _search_page_payload(page)
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _search_page_payload(page: "HighResSearchPage") -> dict:
    return {
        "total_count": page.total_count,
        "page_start": page.page_start,
        "page_size": page.page_size,
        "candidates": [
            {
                "identifier": candidate.identifier,
                "name": candidate.name,
                "dpi": candidate.dpi,
                "extension": candidate.extension,
                "download_link": candidate.download_link,
                "small_thumbnail_url": candidate.small_thumbnail_url,
                "medium_thumbnail_url": candidate.medium_thumbnail_url,
                "source_id": candidate.source_id,
                "source_name": candidate.source_name,
            }
            for candidate in page.candidates
        ],
    }


def _search_page_from_payload(payload: dict) -> "HighResSearchPage":
    return HighResSearchPage(
        candidates=[
            HighResCandidate(
                identifier=candidate["identifier"],
                name=candidate["name"],
                dpi=int(candidate.get("dpi", 0)),
                extension=candidate.get("extension", "png"),
                download_link=candidate.get("download_link", ""),
                small_thumbnail_url=candidate.get("small_thumbnail_url", ""),
                medium_thumbnail_url=candidate.get("medium_thumbnail_url", ""),
                source_id=int(candidate.get("source_id", 0)),
                source_name=candidate.get("source_name", ""),
            )
            for candidate in payload.get("candidates", [])
            if candidate.get("identifier")
        ],
        total_count=int(payload.get("total_count", 0)),
        page_start=max(0, int(payload.get("page_start", 0))),
        page_size=max(1, int(payload.get("page_size", 60))),
    )


def _image_cache_key(kind: str, url: str) -> tuple:
    return (kind, url)


def get_cached_thumbnail_bytes(url: str) -> bytes | None:
    key = _image_cache_key("thumbnail", url)
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached

    cached = _read_disk_bytes_cache("image", key)
    if cached is not None:
        _IMAGE_CACHE.set(key, cached, len(cached))
    return cached


def get_cached_preview_bytes(url: str) -> bytes | None:
    key = _image_cache_key("preview", url)
    cached = _IMAGE_CACHE.get(key)
    if cached is not None:
        return cached

    cached = _read_disk_bytes_cache("image", key)
    if cached is not None:
        _IMAGE_CACHE.set(key, cached, len(cached))
    return cached


def _cache_image_bytes(kind: str, url: str, data: bytes):
    key = _image_cache_key(kind, url)
    _IMAGE_CACHE.set(key, data, len(data))
    _write_disk_bytes_cache("image", key, data)


def _standardize_url(url: str) -> str:
    match = re.search(r"^(https?://)?(.*?)(?:/.*)?$", url.strip())
    if match is None:
        return url
    scheme = match.group(1) or "https://"
    body = match.group(2) or ""
    return scheme + body


def get_backend_host(url: str) -> str:
    return urllib.parse.urlparse(_standardize_url(url)).netloc.lower()


def format_backend_url(base_url: str, route_url: str) -> str:
    return urllib.parse.urljoin(_standardize_url(base_url), route_url)


def _fetch_json(
    url: str, body: dict | None = None, headers: dict[str, str] | None = None
) -> dict:
    request_body = None
    request_headers = {
        "Accept": "application/json, text/plain, */*",
        "User-Agent": "PrintProxyPrep/1.0",
        **(headers or {}),
    }
    if body is not None:
        request_body = json.dumps(body).encode("utf-8")
        request_headers = {
            "Content-Type": "application/json",
            **request_headers,
        }
    request = urllib.request.Request(url, data=request_body, headers=request_headers)
    with urllib.request.urlopen(request) as response:
        raw = response.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            snippet = raw[:200].strip().replace("\r", " ").replace("\n", " ")
            if not snippet:
                snippet = "<empty response>"
            raise ValueError(
                f"Expected JSON from {url}, but got non-JSON content: {snippet}"
            ) from exc


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PrintProxyPrep/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request) as response:
        return response.read().decode("utf-8")


def _fetch_bytes(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "PrintProxyPrep/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(request) as response:
        return response.read()


def _validate_downloaded_image_bytes(data: bytes) -> bytes:
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError("Downloaded high-res image data was not bytes.")

    normalized = bytes(data)
    if len(normalized) == 0:
        raise ValueError("Downloaded high-res image data was empty.")

    try:
        decoded = image_from_bytes(normalized)
    except Exception as exc:
        raise ValueError("Downloaded high-res image data was not a valid image.") from exc

    if decoded is None or getattr(decoded, "size", 0) == 0:
        raise ValueError("Downloaded high-res image data was not a valid image.")

    return normalized


def build_card_context(card_name: str, print_dict: dict) -> CardContext:
    metadata = print_dict.get("card_metadata", {}).get(card_name, {})
    override = print_dict.get("high_res_front_overrides", {}).get(card_name, {})
    parsed_filename = _parse_scryfall_filename(card_name)
    query = (
        _normalize_card_query_name(metadata.get("name"))
        or _normalize_override_name(override.get("name"))
        or (parsed_filename["name"] if parsed_filename is not None else None)
        or _guess_name_from_filename(card_name)
    )
    return CardContext(
        filename=card_name,
        query=query,
        display_name=query,
        set_code=metadata.get("set_code")
        or (parsed_filename["set_code"] if parsed_filename is not None else None),
        collector_number=metadata.get("collector_number")
        or (
            parsed_filename["collector_number"]
            if parsed_filename is not None
            else None
        ),
    )


def validate_backend_url(backend_url: str):
    normalized = _standardize_url(backend_url).strip()
    if not normalized:
        raise ValueError(
            "No high-res backend is configured. Set `HighRes.BackendURL` in "
            "`config.ini` to the MPCFill base URL, such as `https://mpcfill.com/`."
        )
    return normalized


def _guess_name_from_filename(card_name: str) -> str:
    stem = os.path.splitext(os.path.basename(card_name))[0]
    match = re.match(r"^(?:__)?(?:scryfall|mpc)_[^_]+_[^_]+_(.+)$", stem)
    if match is not None:
        stem = match.group(1)
    stem = stem.replace("-", " ").strip("_ ")
    return re.sub(r"\s+", " ", stem).strip().title() or card_name


def _parse_scryfall_filename(card_name: str) -> dict | None:
    stem = os.path.splitext(os.path.basename(card_name))[0]
    match = re.match(r"^(?:__)?scryfall_([^_]+)_([^_]+)_(.+)$", stem)
    if match is None:
        return None

    return {
        "set_code": match.group(1).lower(),
        "collector_number": match.group(2),
        "name": match.group(3).replace("-", " ").strip("_ ").replace("  ", " ").title(),
    }


def _normalize_override_name(value: str | None) -> str | None:
    normalized = _normalize_card_query_name(value)
    if not normalized:
        return None

    normalized = re.sub(
        r"\s+\[[^\]]+\]\s+\{[^}]+\}\s+\(\d+\)\s*$", "", normalized
    )
    normalized = re.sub(
        r"\s+\((?:normal|borderless|extended art|showcase|retro frame|full art|alt art|anime|foil|etched foil)\)\s*$",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


def _normalize_card_query_name(value: str | None) -> str | None:
    if not value:
        return None

    normalized = value.strip()
    if "//" in normalized:
        normalized = normalized.split("//", 1)[0].strip()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized or None


def build_search_payload(
    query: str,
    min_dpi: int,
    max_dpi: int,
    page_size: int = 60,
    page_start: int = 0,
    source_ids: list[int] | None = None,
) -> dict:
    active_source_ids = source_ids or MPCFILL_SOURCE_IDS
    return {
        "cardTypes": [],
        "pageSize": page_size,
        "pageStart": max(0, int(page_start)),
        "searchSettings": {
            "searchTypeSettings": {
                "fuzzySearch": True,
                "filterCardbacks": False,
            },
            "sourceSettings": {
                "sources": [[source_id, True] for source_id in active_source_ids],
            },
            "filterSettings": {
                "minimumDPI": max(0, int(min_dpi)),
                "maximumDPI": max(max(0, int(min_dpi)), int(max_dpi)),
                "maximumSize": 30,
                "languages": [],
                "includesTags": [],
                "excludesTags": ["NSFW"],
            },
        },
        "sortBy": "dateCreatedDescending",
        "query": query,
    }


def search_high_res_page(
    context: CardContext,
    backend_url: str,
    min_dpi: int,
    max_dpi: int,
    page_start: int = 0,
    page_size: int = 60,
    source_ids: list[int] | None = None,
    fetch_json: Callable[[str, dict | None, dict[str, str] | None], dict] | None = None,
) -> HighResSearchPage:
    validate_backend_url(backend_url)
    fetch_json = fetch_json or _fetch_json
    cache_key = _build_search_cache_key(
        backend_url,
        context.query,
        min_dpi,
        max_dpi,
        page_start,
        page_size,
        source_ids,
    )
    now = time.time()
    if fetch_json is _fetch_json:
        cached_page = _SEARCH_PAGE_CACHE.get(cache_key)
        if cached_page is not None:
            return cached_page
        cached_payload = _read_disk_json_cache("search", cache_key)
        if cached_payload is not None:
            cached_page = _search_page_from_payload(cached_payload)
            _SEARCH_PAGE_CACHE.set(cache_key, cached_page, _page_size_bytes(cached_page))
            return cached_page

    payload = build_search_payload(
        context.query,
        min_dpi,
        max_dpi,
        page_size=page_size,
        page_start=page_start,
        source_ids=source_ids,
    )
    url = format_backend_url(backend_url, "2/exploreSearch/")
    response = fetch_json(url, payload)
    cards = response.get("cards", [])
    candidates = [
        HighResCandidate(
            identifier=card["identifier"],
            name=card["name"],
            dpi=int(card.get("dpi", 0)),
            extension=card.get("extension", "png"),
            download_link=card.get("downloadLink", ""),
            small_thumbnail_url=card.get("smallThumbnailUrl", ""),
            medium_thumbnail_url=card.get("mediumThumbnailUrl", ""),
            source_id=int(card.get("sourceId", 0)),
            source_name=card.get("sourceName", ""),
        )
        for card in cards
        if card.get("identifier")
    ]
    result = HighResSearchPage(
        candidates=candidates,
        total_count=int(response.get("count", len(candidates))),
        page_start=max(0, int(page_start)),
        page_size=max(1, int(page_size)),
    )
    if fetch_json is _fetch_json:
        _SEARCH_PAGE_CACHE.set(cache_key, result, _page_size_bytes(result))
        _write_disk_json_cache("search", cache_key, _search_page_payload(result))
    return result


def search_high_res_candidates(
    context: CardContext,
    backend_url: str,
    min_dpi: int,
    max_dpi: int,
    page_start: int = 0,
    page_size: int = 60,
    source_ids: list[int] | None = None,
    fetch_json: Callable[[str, dict | None, dict[str, str] | None], dict] | None = None,
) -> list[HighResCandidate]:
    return search_high_res_page(
        context,
        backend_url,
        min_dpi,
        max_dpi,
        page_start=page_start,
        page_size=page_size,
        source_ids=source_ids,
        fetch_json=fetch_json,
    ).candidates


def download_high_res_image(
    identifier: str,
    download_link: str = "",
    fetch_bytes: Callable[[str], bytes] | None = None,
    fetch_text: Callable[[str], str] | None = None,
) -> bytes:
    fetch_bytes = fetch_bytes or _fetch_bytes
    fetch_text = fetch_text or _fetch_text
    if download_link:
        try:
            return _validate_downloaded_image_bytes(fetch_bytes(download_link))
        except Exception:
            pass

    url = GOOGLE_DRIVE_IMAGE_API_URL + "?" + urllib.parse.urlencode({"id": identifier})
    response = fetch_text(url).strip()
    try:
        decoded = base64.b64decode(response, validate=True)
        return _validate_downloaded_image_bytes(decoded)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(
            "The selected high-res image could not be downloaded as a valid image file."
        ) from exc


def fetch_preview_bytes(
    url: str,
    fetch_bytes: Callable[[str], bytes] | None = None,
    cache_kind: str = "preview",
) -> bytes:
    fetch_bytes = fetch_bytes or _fetch_bytes
    if not url:
        return b""

    cached = None
    if fetch_bytes is _fetch_bytes:
        if cache_kind == "thumbnail":
            cached = get_cached_thumbnail_bytes(url)
        else:
            cached = get_cached_preview_bytes(url)
        if cached is not None:
            return cached

    data = fetch_bytes(url)
    if fetch_bytes is _fetch_bytes:
        _cache_image_bytes(cache_kind, url, data)
    return data


def _build_scryfall_lookup_url(context: CardContext) -> str:
    if context.set_code and context.collector_number:
        return (
            "https://api.scryfall.com/cards/"
            f"{urllib.parse.quote(context.set_code)}/"
            f"{urllib.parse.quote(context.collector_number)}"
        )
    return "https://api.scryfall.com/cards/named?" + urllib.parse.urlencode(
        {"exact": context.display_name}
    )


def get_double_faced_back_context(
    print_dict: dict,
    card_name: str,
    front_context: CardContext,
    fetch_json: Callable[[str, dict | None, dict[str, str] | None], dict] | None = None,
) -> CardContext | None:
    backside_name = print_dict.get("backsides", {}).get(card_name)
    if not backside_name or not backside_name.startswith("__scryfall_"):
        return None

    fetch_json = fetch_json or _fetch_json
    cache_key = (
        card_name,
        backside_name,
        front_context.display_name.casefold(),
        front_context.set_code or "",
        front_context.collector_number or "",
    )
    if fetch_json is _fetch_json:
        cached_context = _DOUBLE_FACE_CONTEXT_CACHE.get(cache_key)
        if cached_context is not None:
            return cached_context

    lookup_url = _build_scryfall_lookup_url(front_context)
    card_data = fetch_json(lookup_url)
    faces = card_data.get("card_faces") or []
    if len(faces) < 2:
        return None

    back_face_name = faces[1].get("name")
    if not back_face_name:
        return None

    result = CardContext(
        filename=backside_name,
        query=back_face_name,
        display_name=back_face_name,
        set_code=front_context.set_code,
        collector_number=front_context.collector_number,
    )
    if fetch_json is _fetch_json:
        _DOUBLE_FACE_CONTEXT_CACHE.set(cache_key, result, len(back_face_name.encode("utf-8")) + 128)
    return result


def _normalize_search_name(value: str) -> str:
    lowered = value.casefold()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def find_matching_backside_candidate(
    front_candidate: HighResCandidate,
    back_context: CardContext,
    backend_url: str,
    fetch_json: Callable[[str, dict | None, dict[str, str] | None], dict] | None = None,
) -> HighResCandidate | None:
    fetch_json = fetch_json or _fetch_json
    candidates = search_high_res_candidates(
        back_context,
        backend_url,
        max(0, front_candidate.dpi - 1),
        front_candidate.dpi + 1,
        source_ids=[front_candidate.source_id],
        fetch_json=fetch_json,
    )
    if not candidates:
        candidates = search_high_res_candidates(
            back_context,
            backend_url,
            0,
            5000,
            source_ids=[front_candidate.source_id],
            fetch_json=fetch_json,
        )
    if not candidates:
        return None

    target_name = _normalize_search_name(back_context.display_name)

    def sort_key(candidate: HighResCandidate):
        candidate_name = _normalize_search_name(candidate.name)
        exact_name = target_name in candidate_name or candidate_name.startswith(target_name)
        exact_dpi = candidate.dpi == front_candidate.dpi
        return (0 if exact_name else 1, 0 if exact_dpi else 1, candidate.name)

    return sorted(candidates, key=sort_key)[0]


def invalidate_cached_card_artifacts(print_dict: dict, image_dir: str, card_name: str):
    crop_dir = os.path.join(image_dir, "crop")
    if os.path.exists(crop_dir):
        for root, _dirs, files in os.walk(crop_dir):
            for file_name in files:
                if file_name == card_name:
                    try:
                        os.remove(os.path.join(root, file_name))
                    except OSError:
                        pass

    cache_data = None
    img_cache_path = print_dict.get("img_cache")
    if img_cache_path and os.path.exists(img_cache_path):
        try:
            with open(img_cache_path, "r", encoding="utf-8") as fp:
                cache_data = json.load(fp)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            cache_data = None

    if isinstance(cache_data, dict) and card_name in cache_data:
        del cache_data[card_name]
        try:
            util.write_json_atomic(img_cache_path, cache_data, ensure_ascii=False)
        except OSError:
            pass


def maybe_find_matching_backside(
    print_dict: dict,
    card_name: str,
    front_context: CardContext,
    front_candidate: HighResCandidate,
    backend_url: str,
    fetch_json: Callable[[str, dict | None, dict[str, str] | None], dict] | None = None,
) -> BacksideMatch | None:
    back_context = get_double_faced_back_context(
        print_dict,
        card_name,
        front_context,
        fetch_json=fetch_json,
    )
    if back_context is None:
        return None

    candidate = find_matching_backside_candidate(
        front_candidate,
        back_context,
        backend_url,
        fetch_json=fetch_json,
    )
    if candidate is None:
        return None

    return BacksideMatch(filename=back_context.filename, candidate=candidate)


def apply_high_res_candidate(
    print_dict: dict,
    image_dir: str,
    card_name: str,
    candidate: HighResCandidate,
    backside_match: BacksideMatch | None = None,
    fetch_bytes: Callable[[str], bytes] | None = None,
    fetch_text: Callable[[str], str] | None = None,
):
    image_bytes = download_high_res_image(
        candidate.identifier,
        candidate.download_link,
        fetch_bytes,
        fetch_text,
    )
    backside_bytes = None

    if backside_match is not None:
        backside_bytes = download_high_res_image(
            backside_match.candidate.identifier,
            backside_match.candidate.download_link,
            fetch_bytes,
            fetch_text,
        )

    path = os.path.join(image_dir, card_name)
    with open(path, "wb") as fp:
        fp.write(image_bytes)
    invalidate_cached_card_artifacts(print_dict, image_dir, card_name)

    if backside_match is not None and backside_bytes is not None:
        back_path = os.path.join(image_dir, backside_match.filename)
        with open(back_path, "wb") as fp:
            fp.write(backside_bytes)
        invalidate_cached_card_artifacts(print_dict, image_dir, backside_match.filename)

    overrides = print_dict.setdefault("high_res_front_overrides", {})
    override = {
        "identifier": candidate.identifier,
        "name": candidate.name,
        "dpi": candidate.dpi,
        "extension": candidate.extension,
        "download_link": candidate.download_link,
        "source_id": candidate.source_id,
        "source_name": candidate.source_name,
        "small_thumbnail_url": candidate.small_thumbnail_url,
        "medium_thumbnail_url": candidate.medium_thumbnail_url,
    }
    if backside_match is not None:
        override["back_identifier"] = backside_match.candidate.identifier
        override["back_download_link"] = backside_match.candidate.download_link
    overrides[card_name] = override
