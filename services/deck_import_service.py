from __future__ import annotations

import deck_import

from models import ProjectState, as_project_state, sync_project_container


def import_decklist(*args, **kwargs):
    return deck_import.import_decklist(*args, **kwargs)


def import_archidekt_url(*args, **kwargs):
    return deck_import.import_archidekt_url(*args, **kwargs)


def apply_import_result(project_like, import_result) -> ProjectState:
    state = as_project_state(project_like)
    deck_import.apply_import_result(state, import_result)
    return sync_project_container(project_like, state)
