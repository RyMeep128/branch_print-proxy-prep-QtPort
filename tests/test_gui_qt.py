import gui_qt


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
        gui_qt.project,
        "load",
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
        gui_qt.project,
        "load",
        lambda pd, id_, path, print_fn, warn_fn=None: False,
    )

    loaded = gui_qt.load_project_file(
        app, {}, {}, "broken.json", lambda _message: None
    )

    assert loaded is False
    assert app.json_path() == "old.json"
