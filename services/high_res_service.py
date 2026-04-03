from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import high_res

from models import ProjectState, as_project_state
from . import project_service


@dataclass
class HighResApplyWorkflowResult:
    state: ProjectState
    candidate: high_res.HighResCandidate
    backside_match: high_res.BacksideMatch | None


def build_card_context(card_name: str, project_like) -> high_res.CardContext:
    return high_res.build_card_context(card_name, as_project_state(project_like))


def search_high_res_page(*args, **kwargs):
    return high_res.search_high_res_page(*args, **kwargs)


def maybe_find_matching_backside(project_like, *args, **kwargs):
    return high_res.maybe_find_matching_backside(as_project_state(project_like), *args, **kwargs)


def apply_high_res_candidate(
    project_like,
    *args,
    **kwargs,
) -> ProjectState:
    state = as_project_state(project_like)
    high_res.apply_high_res_candidate(state, *args, **kwargs)
    return state


def apply_candidate_to_project(
    state: ProjectState,
    img_dict: dict,
    card_name: str,
    candidate: high_res.HighResCandidate,
    backend_url: str,
    print_fn: Callable[[str], None],
    warn_fn: Callable[[str, str], None] | None = None,
) -> HighResApplyWorkflowResult:
    state = as_project_state(state)
    context = build_card_context(card_name, state)
    backside_match = high_res.maybe_find_matching_backside(
        state,
        card_name,
        context,
        candidate,
        backend_url,
    )
    high_res.apply_high_res_candidate(
        state,
        state.image_dir,
        card_name,
        candidate,
        backside_match=backside_match,
    )
    project_service.refresh_after_image_changes(state, img_dict, print_fn, warn_fn)
    return HighResApplyWorkflowResult(
        state=state,
        candidate=candidate,
        backside_match=backside_match,
    )
