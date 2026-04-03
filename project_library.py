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


def draft_root():
    return os.path.join(projects_root(), "tmp_images")


def draft_crop_dir():
    return os.path.join(draft_root(), "crop")


def draft_cache_path():
    return os.path.join(draft_root(), "img.cache")


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
    if (
        not isinstance(data, dict)
        or "projects" not in data
        or not isinstance(data["projects"], list)
    ):
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


def _seed_default_back(image_dir):
    os.makedirs(image_dir, exist_ok=True)
    os.makedirs(os.path.join(image_dir, "crop"), exist_ok=True)

    default_back_source = _shared_default_back_path()
    if default_back_source is None:
        return "__back.png"

    default_back_name = os.path.basename(default_back_source)
    shutil.copyfile(default_back_source, os.path.join(image_dir, default_back_name))
    return default_back_name


def _load_project_json(project_path):
    if not project_path or not os.path.exists(project_path):
        return {}
    try:
        with open(project_path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _playable_cards(project_data):
    cards = project_data.get("cards", {})
    if not isinstance(cards, dict):
        return []
    playable = []
    for card_name, quantity in cards.items():
        try:
            quantity_num = int(quantity)
        except (TypeError, ValueError):
            continue
        if str(card_name).startswith("__") or quantity_num <= 0:
            continue
        playable.append(card_name)
    return playable


def _is_valid_thumbnail_card(project_data, card_name):
    return card_name in _playable_cards(project_data)


def _resolve_thumbnail_card(entry, project_data):
    override = entry.get("thumbnail_card")
    if override and _is_valid_thumbnail_card(project_data, override):
        return override

    playable_cards = _playable_cards(project_data)
    if playable_cards:
        return playable_cards[0]
    return None


def _resolve_thumbnail_path(project_data, thumbnail_card):
    if not thumbnail_card:
        return None

    image_dir = project_data.get("image_dir")
    if not image_dir:
        return None

    source_path = os.path.join(image_dir, thumbnail_card)
    if os.path.exists(source_path):
        return source_path

    crop_path = os.path.join(image_dir, "crop", thumbnail_card)
    if os.path.exists(crop_path):
        return crop_path

    return None


def _project_summary(entry):
    project_path = entry.get("path")
    project_data = _load_project_json(project_path)
    thumbnail_card = _resolve_thumbnail_card(entry, project_data)
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
        "thumbnail_card_resolved": thumbnail_card,
        "thumbnail_path": _resolve_thumbnail_path(project_data, thumbnail_card),
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


def ensure_draft_workspace():
    root = draft_root()
    crop = draft_crop_dir()
    os.makedirs(root, exist_ok=True)
    os.makedirs(crop, exist_ok=True)

    default_back_source = _shared_default_back_path()
    if default_back_source is None:
        return {
            "image_dir": os.path.abspath(root),
            "img_cache": os.path.abspath(draft_cache_path()),
            "backside_default": "__back.png",
        }

    default_back_name = os.path.basename(default_back_source)
    draft_back_path = os.path.join(root, default_back_name)
    if not os.path.exists(draft_back_path):
        shutil.copyfile(default_back_source, draft_back_path)

    return {
        "image_dir": os.path.abspath(root),
        "img_cache": os.path.abspath(draft_cache_path()),
        "backside_default": default_back_name,
    }


def _clear_folder_contents(path):
    if not os.path.isdir(path):
        return
    for name in os.listdir(path):
        target = os.path.join(path, name)
        if os.path.isdir(target):
            shutil.rmtree(target)
        else:
            os.remove(target)


def _move_folder_contents(source_dir, destination_dir):
    os.makedirs(destination_dir, exist_ok=True)
    for name in os.listdir(source_dir):
        shutil.move(
            os.path.join(source_dir, name),
            os.path.join(destination_dir, name),
        )


def reset_draft_workspace():
    root = draft_root()
    os.makedirs(root, exist_ok=True)
    _clear_folder_contents(root)
    return ensure_draft_workspace()


def draft_has_user_content():
    ensure_draft_workspace()

    default_back_name = os.path.basename(_shared_default_back_path() or "__back.png")
    root = draft_root()
    crop = draft_crop_dir()

    for name in os.listdir(root):
        target = os.path.join(root, name)
        if os.path.isdir(target):
            if os.path.abspath(target) != os.path.abspath(crop):
                return True
            if os.listdir(target):
                return True
            continue
        if name in {default_back_name, "img.cache"}:
            continue
        return True
    return False


def create_draft_project_dict():
    return ensure_draft_workspace()


def _initial_project_dict(project_path):
    image_dir = os.path.abspath(_project_image_dir(project_path))
    default_back_name = _seed_default_back(image_dir)
    return {
        "image_dir": image_dir,
        "img_cache": os.path.join(image_dir, "img.cache"),
        "backside_default": default_back_name,
    }


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
        "thumbnail_card": None,
    }
    write_json_atomic(path, _initial_project_dict(path), ensure_ascii=False)
    data["projects"].append(entry)
    save_library(data)
    return entry


def materialize_draft_project(display_name, print_dict, thumbnail_card=None):
    data = load_library()
    project_id = str(uuid.uuid4())
    path = os.path.join(projects_root(), _project_file_name(display_name))
    destination_image_dir = os.path.abspath(_project_image_dir(path))
    os.makedirs(destination_image_dir, exist_ok=True)
    os.makedirs(os.path.join(destination_image_dir, "crop"), exist_ok=True)

    ensure_draft_workspace()
    for name in os.listdir(draft_root()):
        source_path = os.path.join(draft_root(), name)
        destination_path = os.path.join(destination_image_dir, name)
        if os.path.isdir(source_path) and name == "crop":
            _move_folder_contents(source_path, destination_path)
        else:
            shutil.move(source_path, destination_path)

    timestamp = _utc_now()
    entry = {
        "id": project_id,
        "display_name": display_name,
        "path": os.path.abspath(path),
        "created_at": timestamp,
        "last_opened_at": timestamp,
        "thumbnail_card": thumbnail_card,
    }

    print_dict["image_dir"] = destination_image_dir
    print_dict["img_cache"] = os.path.join(destination_image_dir, "img.cache")
    default_back_source = _shared_default_back_path()
    if default_back_source is not None:
        default_back_name = os.path.basename(default_back_source)
        if os.path.exists(os.path.join(destination_image_dir, default_back_name)):
            print_dict["backside_default"] = default_back_name

    write_json_atomic(path, print_dict, ensure_ascii=False)
    data["projects"].append(entry)
    save_library(data)
    reset_draft_workspace()
    return get_project(project_id)


def import_project(source_path, display_name=None):
    data = load_library()
    existing = _find_entry_by_path(data, source_path)
    if existing is not None:
        touch_opened(existing["id"])
        return get_project(existing["id"])

    display_name = display_name or os.path.splitext(os.path.basename(source_path))[0]
    entry = create_project(display_name)
    shutil.copyfile(source_path, entry["path"])
    touch_opened(entry["id"])
    return get_project(entry["id"])


def list_projects():
    data = load_library()
    results = [_project_summary(entry) for entry in data["projects"]]
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
    return _project_summary(entry)


def touch_opened(project_id):
    data = load_library()
    entry = _find_entry(data, project_id)
    if entry is None:
        return None
    entry["last_opened_at"] = _utc_now()
    save_library(data)
    return entry


def set_thumbnail_card(project_id, card_name):
    data = load_library()
    entry = _find_entry(data, project_id)
    if entry is None:
        return None
    entry["thumbnail_card"] = card_name
    save_library(data)
    return get_project(project_id)


def clear_thumbnail_card(project_id):
    data = load_library()
    entry = _find_entry(data, project_id)
    if entry is None:
        return None
    entry["thumbnail_card"] = None
    save_library(data)
    return get_project(project_id)


def remove_project(project_id):
    data = load_library()
    entry = _find_entry(data, project_id)
    if entry is None:
        return False

    project_path = os.path.abspath(entry.get("path", ""))
    image_dir = os.path.abspath(_project_image_dir(project_path)) if project_path else ""

    if image_dir and os.path.isdir(image_dir):
        shutil.rmtree(image_dir)

    if project_path and os.path.exists(project_path):
        os.remove(project_path)

    data["projects"] = [
        existing_entry
        for existing_entry in data["projects"]
        if existing_entry.get("id") != project_id
    ]
    save_library(data)
    return True


def save_project(project_id, print_dict):
    data = load_library()
    entry = _find_entry(data, project_id)
    if entry is None:
        return None

    if not _is_valid_thumbnail_card(print_dict, entry.get("thumbnail_card")):
        entry["thumbnail_card"] = None

    write_json_atomic(entry["path"], print_dict, ensure_ascii=False)
    entry["last_opened_at"] = _utc_now()
    save_library(data)
    return get_project(project_id)
