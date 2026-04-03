import json

from models import CardMetadata
import project


def test_init_dict_adds_defaults_and_removes_stale_entries(monkeypatch, tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"
    img_cache = tmp_path / "img.cache"
    img_cache.write_text(
        json.dumps({"cached.png": {"size": [1, 2], "thumb": {}, "uncropped": {}}}),
        encoding="utf-8",
    )

    init_calls = []

    def fake_init_image_folder(image_dir_arg, crop_dir_arg):
        init_calls.append((image_dir_arg, crop_dir_arg))

    monkeypatch.setattr(project.image, "init_image_folder", fake_init_image_folder)
    monkeypatch.setattr(
        project.image,
        "list_image_files",
        lambda folder: ["card-a.png", "__hidden.png"],
    )
    monkeypatch.setattr(project.CFG, "DefaultPageSize", "NotARealPageSize")

    print_dict = {
        "image_dir": str(image_dir),
        "img_cache": str(img_cache),
        "cards": {"stale.png": 3, "__hidden.png": 9},
        "backsides": {"stale.png": "back.png"},
        "backside_short_edge": {"stale.png": True},
        "oversized": {"stale.png": True},
        "bleed_edge": "not-a-number",
    }
    img_dict = {"old": "value"}

    project.init_dict(print_dict, img_dict)

    assert init_calls == [(str(image_dir), str(crop_dir))]
    assert print_dict["pagesize"] == "Letter"
    assert print_dict["cards"] == {"__hidden.png": 0, "card-a.png": 1}
    assert print_dict["backsides"] == {}
    assert print_dict["backside_short_edge"] == {}
    assert print_dict["oversized"] == {}
    assert print_dict["bleed_edge"] == "0"
    assert img_dict == {"cached.png": {"size": [1, 2], "thumb": {}, "uncropped": {}}}


def test_init_dict_keeps_cards_with_source_files_even_if_crop_is_missing(monkeypatch, tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"

    def fake_list_image_files(folder):
        if folder == str(crop_dir):
            return []
        if folder == str(image_dir):
            return [
                "scryfall_mid_1_delver-of-secrets.png",
                "__scryfall_mid_1_insectile-aberration.png",
            ]
        return []

    monkeypatch.setattr(project.image, "init_image_folder", lambda *_args: None)
    monkeypatch.setattr(project.image, "list_image_files", fake_list_image_files)

    print_dict = {
        "image_dir": str(image_dir),
        "img_cache": str(tmp_path / "img.cache"),
        "cards": {
            "scryfall_mid_1_delver-of-secrets.png": 1,
            "__scryfall_mid_1_insectile-aberration.png": 0,
        },
        "backsides": {
            "scryfall_mid_1_delver-of-secrets.png": "__scryfall_mid_1_insectile-aberration.png"
        },
        "bleed_edge": "0",
    }
    img_dict = {}

    project.init_dict(print_dict, img_dict)

    assert print_dict["cards"]["scryfall_mid_1_delver-of-secrets.png"] == 1
    assert print_dict["cards"]["__scryfall_mid_1_insectile-aberration.png"] == 0
    assert print_dict["backsides"] == {
        "scryfall_mid_1_delver-of-secrets.png": "__scryfall_mid_1_insectile-aberration.png"
    }


def test_init_dict_loads_utf8_cache_keys_without_mojibake(monkeypatch, tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"
    img_cache = tmp_path / "img.cache"
    unicode_name = "scryfall_oarc_10★_every-hope-shall-vanish.png"

    image_dir.mkdir()
    crop_dir.mkdir()
    img_cache.write_text(
        json.dumps(
            {
                unicode_name: {
                    "size": [1, 2],
                    "thumb": {},
                    "uncropped": {},
                    "effective_dpi": 300,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_list_image_files(folder):
        if folder == str(crop_dir):
            return [unicode_name]
        if folder == str(image_dir):
            return [unicode_name]
        return []

    monkeypatch.setattr(project.image, "init_image_folder", lambda *_args: None)
    monkeypatch.setattr(project.image, "list_image_files", fake_list_image_files)

    print_dict = {
        "image_dir": str(image_dir),
        "img_cache": str(img_cache),
        "cards": {unicode_name: 1},
        "backsides": {},
        "backside_short_edge": {},
        "oversized": {},
        "card_metadata": {},
        "high_res_front_overrides": {},
        "bleed_edge": "0",
    }
    img_dict = {}

    project.init_dict(print_dict, img_dict)

    assert unicode_name in img_dict


def test_init_dict_backfills_scryfall_metadata_from_filename(monkeypatch, tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"

    def fake_list_image_files(folder):
        if folder == str(crop_dir):
            return ["scryfall_mom_137_etali-primal-conqueror.png"]
        if folder == str(image_dir):
            return ["scryfall_mom_137_etali-primal-conqueror.png"]
        return []

    monkeypatch.setattr(project.image, "init_image_folder", lambda *_args: None)
    monkeypatch.setattr(project.image, "list_image_files", fake_list_image_files)

    print_dict = {
        "image_dir": str(image_dir),
        "img_cache": str(tmp_path / "img.cache"),
        "cards": {"scryfall_mom_137_etali-primal-conqueror.png": 1},
        "card_metadata": {},
        "bleed_edge": "0",
    }
    img_dict = {}

    project.init_dict(print_dict, img_dict)

    assert print_dict["card_metadata"] == {
        "scryfall_mom_137_etali-primal-conqueror.png": {
            "name": "Etali Primal Conqueror",
            "set_code": "mom",
            "collector_number": "137",
        }
    }


def test_init_dict_promotes_detected_back_file_to_default(monkeypatch, tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"

    def fake_list_image_files(folder):
        if folder == str(crop_dir):
            return ["card-a.png", "__back.jpg"]
        if folder == str(image_dir):
            return ["card-a.png", "__back.jpg"]
        return []

    monkeypatch.setattr(project.image, "init_image_folder", lambda *_args: None)
    monkeypatch.setattr(project.image, "list_image_files", fake_list_image_files)

    print_dict = {
        "image_dir": str(image_dir),
        "img_cache": str(tmp_path / "img.cache"),
        "cards": {"card-a.png": 1},
        "backside_default": "__back.png",
        "bleed_edge": "0",
    }
    img_dict = {}

    project.init_dict(print_dict, img_dict)

    assert print_dict["backside_default"] == "__back.jpg"


def test_load_resets_invalid_project_file_and_initializes_images(
    monkeypatch, tmp_path
):
    project_file = tmp_path / "print.json"
    project_file.write_text("{invalid json", encoding="utf-8")

    init_dict_calls = []
    init_images_calls = []
    printed = []
    print_dict = {"keep": "value"}
    img_dict = {}

    monkeypatch.setattr(
        project,
        "init_dict",
        lambda pd, id_, warn_fn=None: init_dict_calls.append(
            (dict(pd), dict(id_), warn_fn)
        ),
    )
    monkeypatch.setattr(
        project,
        "init_images",
        lambda pd, id_, fn: init_images_calls.append((dict(pd), dict(id_), fn)),
    )
    monkeypatch.setattr(project.time, "sleep", lambda _: None)

    loaded_successfully = project.load(
        print_dict, img_dict, str(project_file), printed.append
    )

    assert loaded_successfully is False
    assert print_dict == {}
    assert len(init_dict_calls) == 1
    assert len(init_images_calls) == 1
    assert init_dict_calls[0][2] is None
    assert printed
    assert printed[0].startswith("Error: Failed loading project")


def test_load_valid_project_replaces_existing_state(monkeypatch, tmp_path):
    project_file = tmp_path / "print.json"
    project_file.write_text(
        json.dumps(
            {
                "image_dir": "images",
                "img_cache": "img.cache",
                "cards": {"new-card.png": 2},
                "backsides": {},
                "backside_short_edge": {},
                "oversized": {},
                "card_metadata": {"new-card.png": {"name": "New Card"}},
                "high_res_front_overrides": {},
                "bleed_edge": "0",
            }
        ),
        encoding="utf-8",
    )

    init_dict_calls = []
    init_images_calls = []
    print_dict = {
        "cards": {"stale-card.png": 5},
        "backsides": {"stale-card.png": "__back.png"},
        "backside_short_edge": {"stale-card.png": True},
        "oversized": {"stale-card.png": True},
        "card_metadata": {"stale-card.png": {"name": "Stale"}},
        "high_res_front_overrides": {"stale-card.png": {"identifier": "old"}},
        "extra_runtime_only": "stale",
    }
    img_dict = {}

    monkeypatch.setattr(
        project,
        "init_dict",
        lambda pd, id_, warn_fn=None: init_dict_calls.append(dict(pd)),
    )
    monkeypatch.setattr(
        project,
        "init_images",
        lambda pd, id_, fn: init_images_calls.append(dict(pd)),
    )

    loaded_successfully = project.load(
        print_dict, img_dict, str(project_file), lambda _msg: None
    )

    assert loaded_successfully is True
    assert "extra_runtime_only" not in print_dict
    assert print_dict["cards"] == {"new-card.png": 2}
    assert print_dict["card_metadata"] == {"new-card.png": {"name": "New Card"}}
    assert len(init_dict_calls) == 1
    assert len(init_images_calls) == 1


def test_card_metadata_to_dict_omits_none_fields():
    metadata = CardMetadata.from_dict({"name": "New Card"})

    assert metadata.to_dict() == {"name": "New Card"}


def test_clear_old_cards_removes_card_images_but_preserves_default_back(tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"
    nested_crop_dir = crop_dir / "0p7"
    image_dir.mkdir()
    crop_dir.mkdir()
    nested_crop_dir.mkdir()

    (image_dir / "__back.jpg").write_bytes(b"back")
    (image_dir / "card-a.png").write_bytes(b"front")
    (crop_dir / "__back.jpg").write_bytes(b"back-crop")
    (crop_dir / "card-a.png").write_bytes(b"crop")
    (nested_crop_dir / "__back.jpg").write_bytes(b"nested-back")
    (nested_crop_dir / "card-a.png").write_bytes(b"nested-crop")

    img_cache = tmp_path / "img.cache"
    img_cache.write_text(
        json.dumps(
            {
                "__back.jpg": {"size": [1, 1], "data": "b''"},
                "card-a.png": {"size": [1, 1], "data": "b''"},
            }
        ),
        encoding="utf-8",
    )

    print_dict = {
        "image_dir": str(image_dir),
        "img_cache": str(img_cache),
        "cards": {"__back.jpg": 0, "card-a.png": 1},
        "backsides": {"card-a.png": "__back.jpg"},
        "backside_short_edge": {"card-a.png": True},
        "oversized": {"card-a.png": True},
    }
    img_dict = {
        "__back.jpg": {"size": [1, 1], "data": "b''"},
        "card-a.png": {"size": [1, 1], "data": "b''"},
    }

    deleted_count = project.clear_old_cards(print_dict, img_dict)

    assert deleted_count == 3
    assert (image_dir / "__back.jpg").exists()
    assert not (image_dir / "card-a.png").exists()
    assert (crop_dir / "__back.jpg").exists()
    assert not (crop_dir / "card-a.png").exists()
    assert nested_crop_dir.exists()
    assert (nested_crop_dir / "__back.jpg").exists()
    assert not (nested_crop_dir / "card-a.png").exists()
    assert print_dict["cards"] == {"__back.jpg": 0}
    assert print_dict["backsides"] == {}
    assert print_dict["backside_short_edge"] == {}
    assert print_dict["oversized"] == {}


def test_delete_card_files_removes_source_crop_and_cache_entries(tmp_path):
    image_dir = tmp_path / "images"
    crop_dir = image_dir / "crop"
    crop_variant_dir = crop_dir / "vibrance"
    image_dir.mkdir()
    crop_dir.mkdir()
    crop_variant_dir.mkdir()

    card_name = "card-a.png"
    (image_dir / card_name).write_bytes(b"source")
    (crop_dir / card_name).write_bytes(b"crop")
    (crop_variant_dir / card_name).write_bytes(b"variant")
    img_cache = image_dir / "img.cache"
    img_cache.write_text(json.dumps({card_name: {"data": "cached"}, "other.png": {"data": "keep"}}), encoding="utf-8")

    print_dict = {
        "image_dir": str(image_dir),
        "img_cache": str(img_cache),
        "cards": {card_name: 1, "other.png": 2},
        "backsides": {card_name: "__back.png"},
        "backside_short_edge": {card_name: True},
        "oversized": {card_name: True},
        "card_metadata": {card_name: {"name": "Card A"}},
        "high_res_front_overrides": {card_name: {"identifier": "abc"}},
    }
    img_dict = {card_name: {"data": "cached"}, "other.png": {"data": "keep"}}

    deleted_count = project.delete_card_files(print_dict, img_dict, card_name)

    assert deleted_count == 3
    assert not (image_dir / card_name).exists()
    assert not (crop_dir / card_name).exists()
    assert not (crop_variant_dir / card_name).exists()
    assert card_name not in img_dict
    assert print_dict["cards"] == {"other.png": 2}
    assert print_dict["backsides"] == {}
    assert print_dict["backside_short_edge"] == {}
    assert print_dict["oversized"] == {}
    assert print_dict["card_metadata"] == {}
    assert print_dict["high_res_front_overrides"] == {}
    cache_data = json.loads(img_cache.read_text(encoding="utf-8"))
    assert card_name not in cache_data
    assert cache_data["other.png"] == {"data": "keep"}
    assert img_dict == {"__back.jpg": {"size": [1, 1], "data": "b''"}}
    assert json.loads(img_cache.read_text(encoding="utf-8")) == img_dict


def test_refresh_after_image_changes_runs_init_then_images_then_init(monkeypatch):
    calls = []

    monkeypatch.setattr(
        project,
        "init_dict",
        lambda pd, id_, warn_fn=None: calls.append(("init_dict", warn_fn)),
    )
    monkeypatch.setattr(
        project,
        "init_images",
        lambda pd, id_, print_fn: calls.append(("init_images", print_fn)),
    )

    warn_fn = object()
    print_fn = object()

    project.refresh_after_image_changes({}, {}, print_fn, warn_fn)

    assert calls == [
        ("init_dict", warn_fn),
        ("init_images", print_fn),
        ("init_dict", warn_fn),
    ]
