import gui_qt
from models import ProjectState
from PyQt6.QtWidgets import QMessageBox


class _FakeApplication:
    def __init__(self, json_path):
        self._json_path = json_path
        self.warnings = []

    def json_path(self):
        return self._json_path

    def set_json_path(self, json_path):
        self._json_path = json_path

    def warn_nonfatal(self, title, message):
        self.warnings.append((title, message))


def test_load_project_file_updates_active_json_path_on_success(monkeypatch):
    app = _FakeApplication("old.json")

    monkeypatch.setattr(
        gui_qt.project_service,
        "load_project",
        lambda pd, id_, path, print_fn, warn_fn=None: True,
    )

    loaded = gui_qt.load_project_file(
        app, {}, {}, "new.json", lambda _message: None
    )

    assert loaded is True
    assert app.json_path() == "new.json"


def test_load_project_file_keeps_active_json_path_on_failure(monkeypatch):
    app = _FakeApplication("old.json")

    monkeypatch.setattr(
        gui_qt.project_service,
        "load_project",
        lambda pd, id_, path, print_fn, warn_fn=None: False,
    )

    loaded = gui_qt.load_project_file(
        app, {}, {}, "broken.json", lambda _message: None
    )

    assert loaded is False
    assert app.json_path() == "old.json"


def test_remove_card_from_project_state_cleans_up_related_metadata():
    print_dict = {
        "cards": {"card-a.png": 2, "card-b.png": 1},
        "backsides": {"card-a.png": "__back.png"},
        "backside_short_edge": {"card-a.png": True},
        "oversized": {"card-a.png": True},
        "high_res_front_overrides": {"card-a.png": {"dpi": 600}},
    }

    gui_qt.remove_card_from_project_state(print_dict, "card-a.png")

    assert print_dict["cards"] == {"card-b.png": 1}
    assert print_dict["backsides"] == {}
    assert print_dict["backside_short_edge"] == {}
    assert print_dict["oversized"] == {}
    assert print_dict["high_res_front_overrides"] == {}


def test_remove_card_from_project_state_accepts_project_state():
    state = ProjectState.from_dict(
        {
            "cards": {"card-a.png": 2, "card-b.png": 1},
            "backsides": {"card-a.png": "__back.png"},
            "backside_short_edge": {"card-a.png": True},
            "oversized": {"card-a.png": True},
            "high_res_front_overrides": {"card-a.png": {"dpi": 600}},
        }
    )

    gui_qt.remove_card_from_project_state(state, "card-a.png")

    assert state.cards == {"card-b.png": 1}
    assert state.backsides == {}
    assert state.backside_short_edge == {}
    assert state.oversized == {}
    assert state.high_res_front_overrides_dict() == {}


def test_delete_project_with_confirmation_only_runs_after_confirmation(monkeypatch):
    class _FakeDashboardApp:
        def __init__(self):
            self.warnings = []

        def warn_nonfatal(self, title, message):
            self.warnings.append((title, message))

    app = _FakeDashboardApp()
    refreshed = []
    monkeypatch.setattr(
        gui_qt.project_library,
        "get_project",
        lambda project_id: {"id": project_id, "display_name": "Alpha"},
    )

    deleted = []
    monkeypatch.setattr(
        gui_qt.project_library,
        "remove_project",
        lambda project_id: deleted.append(project_id) or True,
    )

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )
    gui_qt.delete_project_with_confirmation(
        None, app, "project-1", lambda: refreshed.append(True)
    )
    assert deleted == []
    assert refreshed == []

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    gui_qt.delete_project_with_confirmation(
        None, app, "project-1", lambda: refreshed.append(True)
    )
    assert deleted == ["project-1"]
    assert refreshed == [True]
