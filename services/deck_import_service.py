from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Callable

import deck_import
import high_res

from models import ProjectState, as_project_state
from . import high_res_service, project_service


@dataclass
class DeckImportWorkflowResult:
    state: ProjectState
    import_result: deck_import.ImportResult


@dataclass(frozen=True)
class ScryfallCardCandidate:
    name: str
    set_code: str | None
    set_name: str | None
    collector_number: str | None
    scryfall_id: str
    preview_url: str
    thumbnail_url: str
    filename: str
    art_context: high_res.CardContext
    card_data: dict


@dataclass(frozen=True)
class ScryfallCardSearchPage:
    candidates: list[ScryfallCardCandidate]
    total_count: int
    page_start: int
    page_size: int


@dataclass
class SingleCardImportWorkflowResult:
    state: ProjectState
    selected_card: ScryfallCardCandidate
    filename: str
    backside_filename: str | None
    art_candidate: high_res.HighResCandidate | None = None
    art_source: str | None = None


def import_decklist(*args, **kwargs):
    return deck_import.import_decklist(*args, **kwargs)


def import_archidekt_url(*args, **kwargs):
    return deck_import.import_archidekt_url(*args, **kwargs)


def read_decklist_file(path: str) -> str:
    return deck_import.read_decklist_file(path)


def is_archidekt_url(value: str) -> bool:
    return deck_import.is_archidekt_url(value)


def _front_face_name(card_data: dict) -> str:
    faces = card_data.get("card_faces") or []
    if faces:
        return faces[0].get("name") or card_data.get("name", "card")
    return card_data.get("name", "card")


def _extract_preview_urls(card_data: dict) -> tuple[str, str]:
    image_uris = card_data.get("image_uris")
    if image_uris:
        return (
            image_uris.get("normal") or image_uris.get("large") or image_uris.get("png") or "",
            image_uris.get("small") or image_uris.get("normal") or image_uris.get("large") or "",
        )

    for face in card_data.get("card_faces") or []:
        image_uris = face.get("image_uris")
        if image_uris:
            return (
                image_uris.get("normal") or image_uris.get("large") or image_uris.get("png") or "",
                image_uris.get("small") or image_uris.get("normal") or image_uris.get("large") or "",
            )
    return "", ""


def _build_card_candidate(card_data: dict) -> ScryfallCardCandidate:
    face_urls = deck_import.extract_face_image_urls(card_data)
    front_name = _front_face_name(card_data)
    if len(face_urls) >= 2:
        filename = deck_import.build_face_image_filename(card_data, front_name, hidden=False)
    else:
        filename = deck_import.build_image_filename(card_data)

    preview_url, thumbnail_url = _extract_preview_urls(card_data)
    card_name = card_data.get("name") or front_name
    return ScryfallCardCandidate(
        name=card_name,
        set_code=card_data.get("set"),
        set_name=card_data.get("set_name"),
        collector_number=str(card_data.get("collector_number") or "") or None,
        scryfall_id=str(card_data.get("id") or filename),
        preview_url=preview_url,
        thumbnail_url=thumbnail_url,
        filename=filename,
        art_context=high_res.CardContext(
            filename=filename,
            query=card_name,
            display_name=card_name,
            set_code=card_data.get("set"),
            collector_number=str(card_data.get("collector_number") or "") or None,
        ),
        card_data=card_data,
    )


def _matches_set_filter(card_data: dict, set_filter: str | None) -> bool:
    needle = (set_filter or "").strip().casefold()
    if not needle:
        return True
    set_code = str(card_data.get("set") or "").casefold()
    set_name = str(card_data.get("set_name") or "").casefold()
    return set_code == needle or needle in set_name


def _fetch_scryfall_search_payloads(
    query: str,
    fetch_json: Callable[[str], dict],
) -> list[dict]:
    url = "https://api.scryfall.com/cards/search?" + urllib.parse.urlencode(
        {"q": query, "unique": "prints"}
    )
    payloads: list[dict] = []
    seen_ids: set[str] = set()
    while url:
        payload = fetch_json(url)
        if payload.get("object") == "error":
            details = payload.get("details")
            if details and "No cards found" in details:
                return []
            raise ValueError(details or "Scryfall card search failed.")
        if payload.get("object") != "list":
            raise ValueError("Scryfall card search failed.")
        for card_data in payload.get("data") or []:
            card_id = str(card_data.get("id") or "")
            if card_id and card_id in seen_ids:
                continue
            if card_id:
                seen_ids.add(card_id)
            payloads.append(card_data)
        url = payload.get("next_page") if payload.get("has_more") else None
    return payloads


def search_scryfall_card_page(
    name_query: str,
    set_filter: str | None = None,
    page_start: int = 0,
    page_size: int = 60,
    fetch_json: Callable[[str], dict] | None = None,
) -> ScryfallCardSearchPage:
    normalized_query = name_query.strip()
    if not normalized_query:
        raise ValueError("Enter a card name to search Scryfall.")

    fetch_json = fetch_json or deck_import._fetch_json
    exact_query = f'!"{normalized_query}"'
    payloads = _fetch_scryfall_search_payloads(exact_query, fetch_json)
    if not payloads:
        payloads = _fetch_scryfall_search_payloads(normalized_query, fetch_json)

    filtered = [
        _build_card_candidate(card_data)
        for card_data in payloads
        if _matches_set_filter(card_data, set_filter)
    ]
    total_count = len(filtered)
    if page_start < 0:
        page_start = 0
    page_end = max(page_start, page_start + max(1, page_size))
    return ScryfallCardSearchPage(
        candidates=filtered[page_start:page_end],
        total_count=total_count,
        page_start=page_start,
        page_size=page_size,
    )


def apply_import_result(state: ProjectState, import_result: deck_import.ImportResult) -> ProjectState:
    state = as_project_state(state)
    for imported_card in import_result.imported:
        state.apply_imported_card(
            imported_card.filename,
            imported_card.entry.count,
            {
                "name": imported_card.entry.name,
                "set_code": imported_card.entry.set_code,
                "collector_number": imported_card.entry.collector_number,
            },
        )
    for front_name, back_name in import_result.backside_pairs.items():
        state.set_backside(front_name, back_name)
    return state


def import_into_project(
    state: ProjectState,
    img_dict: dict,
    image_dir: str,
    print_fn: Callable[[str], None],
    deck_text: str = "",
    archidekt_url: str = "",
    warn_fn: Callable[[str, str], None] | None = None,
) -> DeckImportWorkflowResult:
    state = as_project_state(state)
    if archidekt_url:
        import_result = deck_import.import_archidekt_url(
            archidekt_url,
            image_dir,
            print_fn,
        )
    else:
        import_result = deck_import.import_decklist(
            deck_text,
            image_dir,
            print_fn,
        )

    if import_result.imported:
        apply_import_result(state, import_result)
        print_fn("Refreshing project...")
        project_service.refresh_after_image_changes(state, img_dict, print_fn, warn_fn)

    return DeckImportWorkflowResult(state=state, import_result=import_result)


def import_single_card_into_project(
    state: ProjectState,
    img_dict: dict,
    image_dir: str,
    selected_card: ScryfallCardCandidate,
    print_fn: Callable[[str], None],
    warn_fn: Callable[[str, str], None] | None = None,
    art_candidate: high_res.HighResCandidate | None = None,
    art_source: str | None = None,
    backend_url: str = "",
    fetch_json: Callable[[str], dict] | None = None,
    fetch_bytes: Callable[[str], bytes] | None = None,
) -> SingleCardImportWorkflowResult:
    state = as_project_state(state)
    fetch_json = fetch_json or deck_import._fetch_json
    fetch_bytes = fetch_bytes or deck_import._fetch_bytes

    entry = deck_import.DeckEntry(
        count=1,
        name=selected_card.name,
        set_code=selected_card.set_code,
        collector_number=selected_card.collector_number,
    )
    card_data = deck_import.resolve_card(entry, fetch_json)
    imported_card, backside_name = deck_import.download_card_image_set(
        card_data,
        entry,
        image_dir,
        print_fn,
        fetch_bytes,
    )
    state.apply_imported_card(
        imported_card.filename,
        1,
        {
            "name": entry.name,
            "set_code": entry.set_code,
            "collector_number": entry.collector_number,
        },
    )
    if backside_name is not None:
        state.set_backside(imported_card.filename, backside_name)

    print_fn("Refreshing project...")
    project_service.refresh_after_image_changes(state, img_dict, print_fn, warn_fn)

    normalized_art_source = (art_source or getattr(art_candidate, "art_source", "") or "").strip() or None
    if art_candidate is not None:
        high_res_service.apply_candidate_to_project(
            state,
            img_dict,
            imported_card.filename,
            art_candidate,
            normalized_art_source or art_candidate.art_source,
            backend_url,
            print_fn,
            warn_fn,
        )

    return SingleCardImportWorkflowResult(
        state=state,
        selected_card=selected_card,
        filename=imported_card.filename,
        backside_filename=backside_name,
        art_candidate=art_candidate,
        art_source=normalized_art_source,
    )
