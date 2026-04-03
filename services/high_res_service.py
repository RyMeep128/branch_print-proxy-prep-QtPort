from __future__ import annotations

import high_res

from models import ProjectState, as_project_state, sync_project_container


def build_card_context(card_name: str, project_like) -> high_res.CardContext:
    return high_res.build_card_context(card_name, as_project_state(project_like))


def search_high_res_page(*args, **kwargs):
    return high_res.search_high_res_page(*args, **kwargs)


def maybe_find_matching_backside(project_like, *args, **kwargs):
    return high_res.maybe_find_matching_backside(as_project_state(project_like), *args, **kwargs)


def apply_high_res_candidate(project_like, *args, **kwargs) -> ProjectState:
    state = as_project_state(project_like)
    high_res.apply_high_res_candidate(state, *args, **kwargs)
    return sync_project_container(project_like, state)
