import json
import logging
import os
import re
import time

import util
import image
from config import CFG
from constants import page_sizes
from models import ProjectState, as_project_state, sync_project_container


logger = logging.getLogger(__name__)


def _parse_scryfall_card_metadata(card_name):
    stem = os.path.splitext(os.path.basename(card_name))[0]
    match = re.match(r"^(?:__)?scryfall_([^_]+)_([^_]+)_(.+)$", stem)
    if match is None:
        return None

    return {
        "name": re.sub(r"\s+", " ", match.group(3).replace("-", " ").strip("_ ")).strip().title(),
        "set_code": match.group(1).lower(),
        "collector_number": match.group(2),
    }


def _detect_default_back_image(source_list, crop_list):
    back_candidates = sorted(
        {
            img_name
            for img_name in list(source_list) + list(crop_list)
            if img_name.startswith("__back")
        }
    )
    if not back_candidates:
        return None
    return back_candidates[0]


def init_dict(print_dict, img_dict, warn_fn=None):
    state = as_project_state(print_dict)
    default_page_size = CFG.DefaultPageSize
    default_print_dict = {
        # project options
        "image_dir": "images",
        "img_cache": "img.cache",
        # list of all cards
        "cards": {},
        # backside options
        "backside_enabled": False,
        "backside_default": "__back.png",
        "backside_offset": "0",
        "backsides": {},
        "backside_short_edge": {},
        # oversized options
        "oversized_enabled": False,
        "oversized": {},
        # metadata
        "card_metadata": {},
        "high_res_front_overrides": {},
        # pdf generation options
        "pagesize": (
            default_page_size if default_page_size in page_sizes else "Letter"
        ),
        "extended_guides": True,
        "orient": "Portrait",
        "bleed_edge": "0",
        "filename": "_printme",
    }

    # Initialize our default values
    for key, value in default_print_dict.items():
        if key not in state:
            state[key] = value

    # Get project folders
    image_dir = state["image_dir"]
    crop_dir = os.path.join(image_dir, "crop")
    image.init_image_folder(image_dir, crop_dir)

    # Get all image files in the crop directory
    crop_list = image.list_image_files(crop_dir)
    source_list = image.list_image_files(image_dir)

    detected_default_back = _detect_default_back_image(source_list, crop_list)
    if detected_default_back is not None:
        state["backside_default"] = detected_default_back

    # Check that we have all our cards accounted for
    for img in crop_list:
        if img not in state["cards"].keys():
            state["cards"][img] = 0 if img.startswith("__") else 1

    # And also check we don't have stale cards in here
    stale_images = []
    for img in state["cards"].keys():
        if img not in crop_list and img not in source_list:
            stale_images.append(img)
    for img in stale_images:
        del state["cards"][img]
        if img in state["backsides"]:
            del state["backsides"][img]
        if img in state["backside_short_edge"]:
            del state["backside_short_edge"][img]
        if img in state["oversized"]:
            del state["oversized"][img]
        if img in state["card_metadata"]:
            del state["card_metadata"][img]
        if img in state["high_res_front_overrides"]:
            del state["high_res_front_overrides"][img]

    # Make sure we have a sensible bleed edge
    bleed_edge = str(state["bleed_edge"])
    bleed_edge = util.cap_bleed_edge_str(bleed_edge)
    if not util.is_number_string(bleed_edge):
        bleed_edge = "0"
    state["bleed_edge"] = bleed_edge

    # Initialize the image amount
    for img in crop_list:
        if img not in state["cards"].keys():
            state["cards"][img] = 1

    # Deselect images starting with __
    for img in crop_list:
        state["cards"][img] = (
            0 if img.startswith("__") else state["cards"][img]
        )

    metadata = state["card_metadata"]
    for img in source_list:
        if img in metadata:
            continue
        parsed_metadata = _parse_scryfall_card_metadata(img)
        if parsed_metadata is not None:
            metadata[img] = parsed_metadata

    # Initialize image cache
    img_cache = state["img_cache"]
    if os.path.exists(img_cache):
        try:
            with open(img_cache, "r", encoding="utf-8") as fp:
                loaded_img_dict = json.load(fp)
                img_dict.clear()
                for key, value in loaded_img_dict.items():
                    img_dict[key] = value
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("project image cache reset path=%s error=%s", img_cache, exc)
            img_dict.clear()
            if warn_fn is not None:
                warn_fn(
                    "Cache Reset",
                    "The image cache could not be loaded and was reset. Thumbnails will be rebuilt.",
                )
    return sync_project_container(print_dict, state)


def init_images(print_dict, img_dict, print_fn):
    state = as_project_state(print_dict)
    image_dir = state["image_dir"]
    crop_dir = os.path.join(image_dir, "crop")
    img_cache = state["img_cache"]

    # setup crops
    bleed_edge = float(state["bleed_edge"])
    if image.need_run_cropper(image_dir, crop_dir, bleed_edge, CFG.VibranceBump):
        image.cropper(
            image_dir,
            crop_dir,
            img_cache,
            img_dict,
            bleed_edge,
            CFG.MaxDPI,
            CFG.VibranceBump,
            CFG.EnableUncrop,
            print_fn,
        )

    # setup image previews
    img_cache = state["img_cache"]
    if image.need_cache_previews(crop_dir, img_dict, image_dir):
        image.cache_previews(img_cache, image_dir, crop_dir, print_fn, img_dict)
    return sync_project_container(print_dict, state)


def refresh_after_image_changes(print_dict, img_dict, print_fn, warn_fn=None):
    init_dict(print_dict, img_dict, warn_fn)
    init_images(print_dict, img_dict, print_fn)
    return init_dict(print_dict, img_dict, warn_fn)


def clear_old_cards(print_dict, img_dict):
    state = as_project_state(print_dict)
    image_dir = state["image_dir"]
    crop_dir = os.path.join(image_dir, "crop")
    img_cache = state["img_cache"]

    image.init_image_folder(image_dir, crop_dir)

    deleted_count = 0

    for img_name in image.list_image_files(image_dir):
        if img_name.startswith("__back"):
            continue
        os.remove(os.path.join(image_dir, img_name))
        deleted_count += 1

    if os.path.exists(crop_dir):
        for root, dirs, files in os.walk(crop_dir, topdown=False):
            for file_name in files:
                if os.path.splitext(file_name)[1].lower() not in image.valid_image_extensions:
                    continue
                if file_name.startswith("__back"):
                    continue
                os.remove(os.path.join(root, file_name))
                deleted_count += 1

            if root != crop_dir and len(os.listdir(root)) == 0:
                os.rmdir(root)

    remaining_crop_images = set(image.list_image_files(crop_dir))
    stale_cache_entries = [img_name for img_name in img_dict if img_name not in remaining_crop_images]
    for img_name in stale_cache_entries:
        del img_dict[img_name]

    if stale_cache_entries:
        util.write_json_atomic(img_cache, img_dict)

    init_dict(state, img_dict)
    sync_project_container(print_dict, state)
    return deleted_count


def load(print_dict, img_dict, json_path, print_fn, warn_fn=None):
    loaded_successfully = False
    try:
        with open(json_path, "r", encoding="utf-8") as fp:
            loaded_print_dict = json.load(fp)
            print_dict.clear()
            print_dict.update(ProjectState.from_dict(loaded_print_dict).to_dict())
            loaded_successfully = True
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("project load failed path=%s error=%s", json_path, exc)
        print_fn(f"Error: Failed loading project ({exc})... Resetting...")
        if warn_fn is not None:
            warn_fn(
                "Project Load Failed",
                f"The project file could not be loaded and the project was reset.\n\n{exc}",
            )
        time.sleep(1)
        print_dict.clear()

    init_dict(print_dict, img_dict, warn_fn)
    init_images(print_dict, img_dict, print_fn)
    return loaded_successfully
