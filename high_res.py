import base64
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable


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


def build_card_context(card_name: str, print_dict: dict) -> CardContext:
    metadata = print_dict.get("card_metadata", {}).get(card_name, {})
    query = metadata.get("name") or _guess_name_from_filename(card_name)
    return CardContext(
        filename=card_name,
        query=query,
        display_name=query,
        set_code=metadata.get("set_code"),
        collector_number=metadata.get("collector_number"),
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
    return HighResSearchPage(
        candidates=candidates,
        total_count=int(response.get("count", len(candidates))),
        page_start=max(0, int(page_start)),
        page_size=max(1, int(page_size)),
    )


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
            return fetch_bytes(download_link)
        except Exception:
            pass

    url = GOOGLE_DRIVE_IMAGE_API_URL + "?" + urllib.parse.urlencode({"id": identifier})
    response = fetch_text(url).strip()
    try:
        return base64.b64decode(response, validate=True)
    except Exception as exc:  # pragma: no cover - defensive
        raise ValueError(
            "The high-res image download failed from MPCFill and the Google Drive "
            "fallback did not return valid image data."
        ) from exc


def fetch_preview_bytes(
    url: str, fetch_bytes: Callable[[str], bytes] | None = None
) -> bytes:
    fetch_bytes = fetch_bytes or _fetch_bytes
    return fetch_bytes(url)


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
    lookup_url = _build_scryfall_lookup_url(front_context)
    card_data = fetch_json(lookup_url)
    faces = card_data.get("card_faces") or []
    if len(faces) < 2:
        return None

    back_face_name = faces[1].get("name")
    if not back_face_name:
        return None

    return CardContext(
        filename=backside_name,
        query=back_face_name,
        display_name=back_face_name,
        set_code=front_context.set_code,
        collector_number=front_context.collector_number,
    )


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

    img_cache_path = print_dict.get("img_cache")
    if img_cache_path and os.path.exists(img_cache_path):
        try:
            with open(img_cache_path, "r") as fp:
                cache_data = json.load(fp)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            cache_data = None

        if isinstance(cache_data, dict) and card_name in cache_data:
            del cache_data[card_name]
            try:
                with open(img_cache_path, "w") as fp:
                    json.dump(cache_data, fp, ensure_ascii=False)
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
    path = os.path.join(image_dir, card_name)
    with open(path, "wb") as fp:
        fp.write(image_bytes)

    invalidate_cached_card_artifacts(print_dict, image_dir, card_name)

    if backside_match is not None:
        backside_bytes = download_high_res_image(
            backside_match.candidate.identifier,
            backside_match.candidate.download_link,
            fetch_bytes,
            fetch_text,
        )
        back_path = os.path.join(image_dir, backside_match.filename)
        with open(back_path, "wb") as fp:
            fp.write(backside_bytes)
        invalidate_cached_card_artifacts(print_dict, image_dir, backside_match.filename)

    overrides = print_dict.setdefault("high_res_front_overrides", {})
    overrides[card_name] = {
        "identifier": candidate.identifier,
        "name": candidate.name,
        "dpi": candidate.dpi,
        "extension": candidate.extension,
        "download_link": candidate.download_link,
        "source_id": candidate.source_id,
        "source_name": candidate.source_name,
        "small_thumbnail_url": candidate.small_thumbnail_url,
        "medium_thumbnail_url": candidate.medium_thumbnail_url,
        "back_identifier": (
            backside_match.candidate.identifier if backside_match is not None else None
        ),
        "back_download_link": (
            backside_match.candidate.download_link if backside_match is not None else None
        ),
    }
