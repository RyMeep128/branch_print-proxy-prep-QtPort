import os
import uuid
import shutil
import datetime
import json

from constants import cwd
from util import write_json_atomic


def projects_root():
    path = os.path.join(cwd, "projects")
    os.makedirs(path, exist_ok=True)
    return path


def library_path():
    return os.path.join(projects_root(), "library.json")


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _default_library():
    return {"projects": []}


def load_library():
    path = library_path()
    if not os.path.exists(path):
        return _default_library()
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, ValueError, TypeError):
        return _default_library()
    if not isinstance(data, dict) or "projects" not in data or not isinstance(data["projects"], list):
        return _default_library()
    return data


def save_library(data):
    write_json_atomic(library_path(), data, ensure_ascii=False)


def _slugify(value):
    import re

    slug = re.sub(r"[^\w\s-]", "", value, flags=re.ASCII)
    slug = re.sub(r"[-\s]+", "-", slug.strip(), flags=re.ASCII)
    return slug.lower() or "project"


def _default_display_name():
    return "Project " + datetime.datetime.now().strftime("%Y-%m-%d %H-%M-%S")


def _project_file_name(display_name):
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{_slugify(display_name)}-{timestamp}.json"


def _project_image_dir(project_path):
    project_stem = os.path.splitext(os.path.basename(project_path))[0]
    return os.path.join(projects_root(), f"{project_stem}_images")


def _shared_default_back_path():
    test_images_dir = os.path.join(cwd, "test_Images")
    if not os.path.isdir(test_images_dir):
        return None

    back_candidates = sorted(
        file_name
        for file_name in os.listdir(test_images_dir)
        if file_name.startswith("__back")
        and os.path.isfile(os.path.join(test_images_dir, file_name))
    )
    if not back_candidates:
        return None
    return os.path.join(test_images_dir, back_candidates[0])


def _seed_project_image_dir(image_dir):
    os.makedirs(image_dir, exist_ok=True)
    os.makedirs(os.path.join(image_dir, "crop"), exist_ok=True)

    default_back_source = _shared_default_back_path()
    if default_back_source is None:
        return "__back.png"

    default_back_name = os.path.basename(default_back_source)
    shutil.copyfile(default_back_source, os.path.join(image_dir, default_back_name))
    return default_back_name


def _initial_project_dict(project_path):
    image_dir = os.path.abspath(_project_image_dir(project_path))
    default_back_name = _seed_project_image_dir(image_dir)
    return {
        "image_dir": image_dir,
        "img_cache": os.path.join(image_dir, "img.cache"),
        "backside_default": default_back_name,
    }


def _find_entry(data, project_id):
    for entry in data["projects"]:
        if entry.get("id") == project_id:
            return entry
    return None


def _find_entry_by_path(data, project_path):
    normalized = os.path.abspath(project_path)
    for entry in data["projects"]:
        if os.path.abspath(entry.get("path", "")) == normalized:
            return entry
    return None


def create_project(display_name=None):
    data = load_library()
    display_name = display_name or _default_display_name()
    project_id = str(uuid.uuid4())
    path = os.path.join(projects_root(), _project_file_name(display_name))
    timestamp = _utc_now()
    entry = {
        "id": project_id,
        "display_name": display_name,
        "path": os.path.abspath(path),
        "created_at": timestamp,
        "last_opened_at": timestamp,
    }
    write_json_atomic(path, _initial_project_dict(path), ensure_ascii=False)
    data["projects"].append(entry)
    save_library(data)
    return entry


def import_project(source_path, display_name=None):
    data = load_library()
    existing = _find_entry_by_path(data, source_path)
    if existing is not None:
        touch_opened(existing["id"])
        return existing

    display_name = display_name or os.path.splitext(os.path.basename(source_path))[0]
    entry = create_project(display_name)
    shutil.copyfile(source_path, entry["path"])
    touch_opened(entry["id"])
    return get_project(entry["id"])


def list_projects():
    data = load_library()
    results = []
    for entry in data["projects"]:
        project_path = entry.get("path")
        modified_at = None
        if project_path and os.path.exists(project_path):
            modified_at = datetime.datetime.fromtimestamp(
                os.path.getmtime(project_path),
                tz=datetime.timezone.utc,
            ).isoformat()
        results.append(
            {
                **entry,
                "exists": bool(project_path and os.path.exists(project_path)),
                "modified_at": modified_at,
            }
        )
    results.sort(
        key=lambda entry: (
            entry.get("modified_at") or "",
            entry.get("last_opened_at") or "",
            entry.get("display_name") or "",
        ),
        reverse=True,
    )
    return results


def get_project(project_id):
    entry = _find_entry(load_library(), project_id)
    if entry is None:
        return None
    project_path = entry.get("path")
    modified_at = None
    if project_path and os.path.exists(project_path):
        modified_at = datetime.datetime.fromtimestamp(
            os.path.getmtime(project_path),
            tz=datetime.timezone.utc,
        ).isoformat()
    return {
        **entry,
        "exists": bool(project_path and os.path.exists(project_path)),
        "modified_at": modified_at,
    }


def touch_opened(project_id):
    data = load_library()
    entry = _find_entry(data, project_id)
    if entry is None:
        return None
    entry["last_opened_at"] = _utc_now()
    save_library(data)
    return entry


def remove_project(project_id):
    data = load_library()
    before = len(data["projects"])
    data["projects"] = [
        entry for entry in data["projects"] if entry.get("id") != project_id
    ]
    if len(data["projects"]) != before:
        save_library(data)
        return True
    return False


def save_project(project_id, print_dict):
    project = get_project(project_id)
    if project is None:
        return None
    write_json_atomic(project["path"], print_dict, ensure_ascii=False)
    touch_opened(project_id)
    return get_project(project_id)
