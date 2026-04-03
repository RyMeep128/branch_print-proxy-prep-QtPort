from services import deck_import_service
from models import ProjectState
import deck_import


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
