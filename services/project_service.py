from __future__ import annotations

from dataclasses import dataclass

import project

from models import ProjectState, as_project_state, project_to_dict


@dataclass
class ProjectLoadResult:
    state: ProjectState
    loaded_successfully: bool


def init_dict(project_like, img_dict, warn_fn=None) -> ProjectState:
    return project.init_dict(project_like, img_dict, warn_fn)


def init_images(project_like, img_dict, print_fn) -> ProjectState:
    return project.init_images(project_like, img_dict, print_fn)


def refresh_after_image_changes(project_like, img_dict, print_fn, warn_fn=None) -> ProjectState:
    return project.refresh_after_image_changes(project_like, img_dict, print_fn, warn_fn)


def clear_old_cards(project_like, img_dict) -> int:
    return project.clear_old_cards(project_like, img_dict)


def load_project(project_like, img_dict, json_path, print_fn, warn_fn=None) -> bool:
    return project.load(project_like, img_dict, json_path, print_fn, warn_fn)


def load_project_state(json_path, img_dict, print_fn, warn_fn=None) -> ProjectLoadResult:
    state = ProjectState()
    loaded_successfully = project.load(state, img_dict, json_path, print_fn, warn_fn)
    return ProjectLoadResult(state=state, loaded_successfully=loaded_successfully)


def save_project_data(project_like) -> dict:
    return project_to_dict(as_project_state(project_like))
