from services import deck_import_service
from models import ProjectState
import deck_import
import high_res


def test_import_into_project_applies_cards_before_refresh(monkeypatch):
    seen_cards_during_refresh = []

    monkeypatch.setattr(
        deck_import,
        "import_decklist",
        lambda deck_text, image_dir, print_fn: deck_import.ImportResult(
            imported=[
                deck_import.ImportedCard(
                    entry=deck_import.DeckEntry(count=1, name="Plains"),
                    filename="scryfall_lea_232_plains.png",
                )
            ],
            unmatched_lines=[],
            failed_cards=[],
            backside_pairs={},
        ),
    )

    def fake_refresh(state, img_dict, print_fn, warn_fn=None):
        seen_cards_during_refresh.append(dict(state.cards))
        img_dict["scryfall_lea_232_plains.png"] = {"data": "b''", "size": (1, 1)}
        return state

    monkeypatch.setattr(
        deck_import_service.project_service,
        "refresh_after_image_changes",
        fake_refresh,
    )

    state = ProjectState()
    img_dict = {}

    result = deck_import_service.import_into_project(
        state,
        img_dict,
        "images",
        lambda _message: None,
        deck_text="1 Plains",
    )

    assert seen_cards_during_refresh == [{"scryfall_lea_232_plains.png": 1}]
    assert result.state.cards == {"scryfall_lea_232_plains.png": 1}
    assert "scryfall_lea_232_plains.png" in img_dict


def test_search_scryfall_card_page_filters_by_set_name(monkeypatch):
    calls = []

    def fake_fetch_json(url):
        calls.append(url)
        return {
            "object": "list",
            "data": [
                {
                    "id": "a",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "image_uris": {"small": "small-a", "normal": "normal-a"},
                },
                {
                    "id": "b",
                    "name": "Lightning Bolt",
                    "set": "m11",
                    "set_name": "Magic 2011",
                    "collector_number": "146",
                    "image_uris": {"small": "small-b", "normal": "normal-b"},
                },
            ],
            "has_more": False,
        }

    page = deck_import_service.search_scryfall_card_page(
        "Lightning Bolt",
        set_filter="alpha",
        fetch_json=fake_fetch_json,
    )

    assert len(page.candidates) == 1
    assert page.total_count == 1
    assert page.candidates[0].set_code == "lea"
    assert page.candidates[0].art_context.filename == "scryfall_lea_161_lightning-bolt.png"
    assert 'q=%21%22Lightning+Bolt%22' in calls[0]


def test_search_scryfall_card_page_falls_back_to_broad_query(monkeypatch):
    calls = []

    def fake_fetch_json(url):
        calls.append(url)
        if 'q=%21%22Bolt%22' in url:
            return {"object": "error", "details": "No cards found matching that query."}
        return {
            "object": "list",
            "data": [
                {
                    "id": "bolt",
                    "name": "Lightning Bolt",
                    "set": "lea",
                    "set_name": "Limited Edition Alpha",
                    "collector_number": "161",
                    "image_uris": {"small": "small", "normal": "normal"},
                }
            ],
            "has_more": False,
        }

    page = deck_import_service.search_scryfall_card_page(
        "Bolt",
        fetch_json=fake_fetch_json,
    )

    assert len(page.candidates) == 1
    assert page.candidates[0].name == "Lightning Bolt"
    assert len(calls) == 2
    assert 'q=Bolt' in calls[1]


def test_import_single_card_into_project_uses_default_art_and_refresh(monkeypatch):
    selected_card = deck_import_service.ScryfallCardCandidate(
        name="Plains",
        set_code="lea",
        set_name="Limited Edition Alpha",
        collector_number="232",
        scryfall_id="card-1",
        preview_url="preview",
        thumbnail_url="thumb",
        filename="scryfall_lea_232_plains.png",
        art_context=high_res.CardContext(
            filename="scryfall_lea_232_plains.png",
            query="Plains",
            display_name="Plains",
            set_code="lea",
            collector_number="232",
        ),
        card_data={},
    )

    monkeypatch.setattr(
        deck_import,
        "resolve_card",
        lambda entry, fetch_json: {
            "name": entry.name,
            "set": entry.set_code,
            "collector_number": entry.collector_number,
            "image_uris": {"png": "https://img.test/plains.png"},
        },
    )
    monkeypatch.setattr(
        deck_import,
        "download_card_image_set",
        lambda card_data, entry, image_dir, print_fn, fetch_bytes: (
            deck_import.ImportedCard(entry=entry, filename="scryfall_lea_232_plains.png"),
            None,
        ),
    )

    refresh_calls = []

    def fake_refresh(state, img_dict, print_fn, warn_fn=None):
        refresh_calls.append(dict(state.cards))
        img_dict["scryfall_lea_232_plains.png"] = {"data": "b''", "size": (1, 1)}
        return state

    monkeypatch.setattr(
        deck_import_service.project_service,
        "refresh_after_image_changes",
        fake_refresh,
    )

    applied_art_calls = []
    monkeypatch.setattr(
        deck_import_service.high_res_service,
        "apply_candidate_to_project",
        lambda *args, **kwargs: applied_art_calls.append((args, kwargs)),
    )

    state = ProjectState()
    img_dict = {}
    result = deck_import_service.import_single_card_into_project(
        state,
        img_dict,
        "images",
        selected_card,
        lambda _message: None,
    )

    assert result.filename == "scryfall_lea_232_plains.png"
    assert result.backside_filename is None
    assert state.cards == {"scryfall_lea_232_plains.png": 1}
    assert state.get_card_metadata("scryfall_lea_232_plains.png") == {
        "name": "Plains",
        "set_code": "lea",
        "collector_number": "232",
    }
    assert refresh_calls == [{"scryfall_lea_232_plains.png": 1}]
    assert applied_art_calls == []


def test_import_single_card_into_project_applies_optional_art_and_backside(monkeypatch):
    selected_card = deck_import_service.ScryfallCardCandidate(
        name="Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
        set_code="neo",
        set_name="Kamigawa: Neon Dynasty",
        collector_number="141",
        scryfall_id="card-2",
        preview_url="preview",
        thumbnail_url="thumb",
        filename="scryfall_neo_141_fable-of-the-mirror-breaker.png",
        art_context=high_res.CardContext(
            filename="scryfall_neo_141_fable-of-the-mirror-breaker.png",
            query="Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
            display_name="Fable of the Mirror-Breaker // Reflection of Kiki-Jiki",
            set_code="neo",
            collector_number="141",
        ),
        card_data={},
    )
    art_candidate = high_res.HighResCandidate(
        identifier="art-1",
        name=selected_card.name,
        dpi=600,
        extension="png",
        download_link="https://art.test/front.png",
        small_thumbnail_url="thumb",
        medium_thumbnail_url="preview",
        source_id=1,
        source_name="MPCFill",
        art_source="mpcfill",
    )

    monkeypatch.setattr(
        deck_import,
        "resolve_card",
        lambda entry, fetch_json: {
            "name": entry.name,
            "set": entry.set_code,
            "collector_number": entry.collector_number,
            "card_faces": [
                {"name": "Fable of the Mirror-Breaker", "image_uris": {"png": "front"}},
                {"name": "Reflection of Kiki-Jiki", "image_uris": {"png": "back"}},
            ],
        },
    )
    monkeypatch.setattr(
        deck_import,
        "download_card_image_set",
        lambda card_data, entry, image_dir, print_fn, fetch_bytes: (
            deck_import.ImportedCard(
                entry=entry,
                filename="scryfall_neo_141_fable-of-the-mirror-breaker.png",
            ),
            "__scryfall_neo_141_reflection-of-kiki-jiki.png",
        ),
    )

    refresh_calls = []
    monkeypatch.setattr(
        deck_import_service.project_service,
        "refresh_after_image_changes",
        lambda state, img_dict, print_fn, warn_fn=None: refresh_calls.append(dict(state.cards)) or state,
    )

    applied_art_calls = []
    monkeypatch.setattr(
        deck_import_service.high_res_service,
        "apply_candidate_to_project",
        lambda state, img_dict, card_name, candidate, source, backend_url, print_fn, warn_fn=None: applied_art_calls.append(
            (card_name, candidate.identifier, source, backend_url)
        ),
    )

    state = ProjectState()
    result = deck_import_service.import_single_card_into_project(
        state,
        {},
        "images",
        selected_card,
        lambda _message: None,
        art_candidate=art_candidate,
        art_source="mpcfill",
        backend_url="https://mpcfill.test/",
    )

    assert result.filename == "scryfall_neo_141_fable-of-the-mirror-breaker.png"
    assert result.backside_filename == "__scryfall_neo_141_reflection-of-kiki-jiki.png"
    assert state.cards["scryfall_neo_141_fable-of-the-mirror-breaker.png"] == 1
    assert state.backsides == {
        "scryfall_neo_141_fable-of-the-mirror-breaker.png": "__scryfall_neo_141_reflection-of-kiki-jiki.png"
    }
    assert refresh_calls == [{"scryfall_neo_141_fable-of-the-mirror-breaker.png": 1}]
    assert applied_art_calls == [
        (
            "scryfall_neo_141_fable-of-the-mirror-breaker.png",
            "art-1",
            "mpcfill",
            "https://mpcfill.test/",
        )
    ]
