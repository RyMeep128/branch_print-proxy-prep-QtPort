import json
from pathlib import Path

import project_library


def test_create_project_adds_library_entry_and_file(monkeypatch, tmp_path):
    monkeypatch.setattr(project_library, "cwd", str(tmp_path))
    test_images_dir = tmp_path / "test_Images"
    test_images_dir.mkdir()
    (test_images_dir / "__back.jpg").write_bytes(b"shared-back")

    entry = project_library.create_project("Alpha Project")

    assert entry["display_name"] == "Alpha Project"
    assert (tmp_path / "projects" / "library.json").exists()
    assert (tmp_path / "projects").exists()
    assert entry["path"].endswith(".json")
    project_data = json.loads(open(entry["path"], "r", encoding="utf-8").read())
    assert project_data["backside_default"] == "__back.jpg"
    assert project_data["image_dir"].endswith("_images")
    assert (Path(project_data["image_dir"]) / "__back.jpg").read_bytes() == b"shared-back"
    assert (Path(project_data["image_dir"]) / "crop").exists()

    projects = project_library.list_projects()
    assert len(projects) == 1
    assert projects[0]["id"] == entry["id"]


def test_import_project_copies_external_project_into_library(monkeypatch, tmp_path):
    monkeypatch.setattr(project_library, "cwd", str(tmp_path))
    external = tmp_path / "outside.json"
    external.write_text(json.dumps({"cards": {"card-a.png": 2}}), encoding="utf-8")

    entry = project_library.import_project(str(external))

    assert entry["display_name"] == "outside"
    managed_path = tmp_path / "projects"
    assert str(managed_path) in entry["path"]
    assert json.loads(open(entry["path"], "r", encoding="utf-8").read()) == {
        "cards": {"card-a.png": 2}
    }


def test_remove_project_unregisters_without_deleting_file(monkeypatch, tmp_path):
    monkeypatch.setattr(project_library, "cwd", str(tmp_path))
    entry = project_library.create_project("Delete Me")
    project_path = entry["path"]

    assert project_library.remove_project(entry["id"]) is True
    assert project_library.list_projects() == []
    project_data = json.loads(open(project_path, "r", encoding="utf-8").read())
    assert project_data["image_dir"].endswith("_images")
