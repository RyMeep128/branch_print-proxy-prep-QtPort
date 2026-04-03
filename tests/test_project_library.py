import json
from pathlib import Path

import project_library


def _seed_test_back(tmp_path):
    test_images_dir = tmp_path / "test_Images"
    test_images_dir.mkdir()
    (test_images_dir / "__back.jpg").write_bytes(b"shared-back")


def test_create_project_adds_library_entry_and_seeded_image_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(project_library, "cwd", str(tmp_path))
    _seed_test_back(tmp_path)

    entry = project_library.create_project("Alpha Project")

    assert entry["display_name"] == "Alpha Project"
    assert (tmp_path / "projects" / "library.json").exists()
    project_data = json.loads(Path(entry["path"]).read_text(encoding="utf-8"))
    assert project_data["backside_default"] == "__back.jpg"
    assert (Path(project_data["image_dir"]) / "__back.jpg").read_bytes() == b"shared-back"
    assert (Path(project_data["image_dir"]) / "crop").exists()

    projects = project_library.list_projects()
    assert len(projects) == 1
    assert projects[0]["id"] == entry["id"]


def test_draft_workspace_is_seeded_and_detects_user_content(monkeypatch, tmp_path):
    monkeypatch.setattr(project_library, "cwd", str(tmp_path))
    _seed_test_back(tmp_path)

    draft = project_library.create_draft_project_dict()

    assert Path(draft["image_dir"]).name == "tmp_images"
    assert (Path(draft["image_dir"]) / "__back.jpg").exists()
    assert project_library.draft_has_user_content() is False

    (Path(draft["image_dir"]) / "card-a.png").write_bytes(b"front")
    assert project_library.draft_has_user_content() is True


def test_materialize_draft_project_moves_tmp_images_into_managed_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(project_library, "cwd", str(tmp_path))
    _seed_test_back(tmp_path)

    draft = project_library.create_draft_project_dict()
    draft_root = Path(draft["image_dir"])
    (draft_root / "card-a.png").write_bytes(b"front")
    (draft_root / "crop" / "card-a.png").write_bytes(b"cropped")
    Path(draft["img_cache"]).write_text("{}", encoding="utf-8")

    print_dict = {
        "image_dir": str(draft_root),
        "img_cache": str(draft_root / "img.cache"),
        "backside_default": "__back.jpg",
        "cards": {"card-a.png": 1},
    }

    entry = project_library.materialize_draft_project(
        "Saved Draft",
        print_dict,
        thumbnail_card="card-a.png",
    )

    saved_project = json.loads(Path(entry["path"]).read_text(encoding="utf-8"))
    managed_image_dir = Path(saved_project["image_dir"])
    assert managed_image_dir.name.endswith("_images")
    assert (managed_image_dir / "card-a.png").read_bytes() == b"front"
    assert (managed_image_dir / "crop" / "card-a.png").read_bytes() == b"cropped"
    assert (managed_image_dir / "__back.jpg").read_bytes() == b"shared-back"
    assert entry["thumbnail_card"] == "card-a.png"

    assert (Path(project_library.draft_root()) / "crop").exists()
    assert not (Path(project_library.draft_root()) / "card-a.png").exists()
    assert project_library.draft_has_user_content() is False


def test_list_projects_uses_thumbnail_override_then_first_playable(monkeypatch, tmp_path):
    monkeypatch.setattr(project_library, "cwd", str(tmp_path))
    _seed_test_back(tmp_path)

    entry = project_library.create_project("Thumb Test")
    project_path = Path(entry["path"])
    project_data = json.loads(project_path.read_text(encoding="utf-8"))
    image_dir = Path(project_data["image_dir"])
    (image_dir / "front-a.png").write_bytes(b"a")
    (image_dir / "front-b.png").write_bytes(b"b")
    project_path.write_text(
        json.dumps(
            {
                **project_data,
                "cards": {"front-a.png": 1, "front-b.png": 1},
            }
        ),
        encoding="utf-8",
    )

    first = project_library.get_project(entry["id"])
    assert first["thumbnail_card_resolved"] == "front-a.png"

    project_library.set_thumbnail_card(entry["id"], "front-b.png")
    second = project_library.get_project(entry["id"])
    assert second["thumbnail_card_resolved"] == "front-b.png"
    assert second["thumbnail_path"].endswith("front-b.png")


def test_import_project_copies_external_project_into_library(monkeypatch, tmp_path):
    monkeypatch.setattr(project_library, "cwd", str(tmp_path))
    external = tmp_path / "outside.json"
    external.write_text(json.dumps({"cards": {"card-a.png": 2}}), encoding="utf-8")

    entry = project_library.import_project(str(external))

    assert entry["display_name"] == "outside"
    managed_path = tmp_path / "projects"
    assert str(managed_path) in entry["path"]
    assert json.loads(Path(entry["path"]).read_text(encoding="utf-8")) == {
        "cards": {"card-a.png": 2}
    }


def test_remove_project_unregisters_without_deleting_file(monkeypatch, tmp_path):
    monkeypatch.setattr(project_library, "cwd", str(tmp_path))
    _seed_test_back(tmp_path)
    entry = project_library.create_project("Delete Me")
    project_path = entry["path"]

    assert project_library.remove_project(entry["id"]) is True
    assert project_library.list_projects() == []
    project_data = json.loads(Path(project_path).read_text(encoding="utf-8"))
    assert project_data["image_dir"].endswith("_images")
