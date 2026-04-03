from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import deck_import

from models import ProjectState, as_project_state
from . import project_service


@dataclass
class DeckImportWorkflowResult:
    state: ProjectState
    import_result: deck_import.ImportResult


def import_decklist(*args, **kwargs):
    return deck_import.import_decklist(*args, **kwargs)


def import_archidekt_url(*args, **kwargs):
    return deck_import.import_archidekt_url(*args, **kwargs)


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
        print_fn("Refreshing project...")
        project_service.refresh_after_image_changes(state, img_dict, print_fn, warn_fn)
        apply_import_result(state, import_result)

    return DeckImportWorkflowResult(state=state, import_result=import_result)
