import dialogs
import editor_widgets


def test_dialogs_exports_real_helpers():
    assert callable(dialogs.load_project_file)
    assert callable(dialogs.delete_project_with_confirmation)
    assert callable(dialogs.remove_card_from_project_state)
    assert dialogs.HighResPickerDialog.__module__ == "dialogs"


def test_editor_widgets_exports_real_widgets():
    assert editor_widgets.EditorPage.__module__ == "editor_widgets"
    assert editor_widgets.ProjectDashboardPage.__module__ == "editor_widgets"
    assert editor_widgets.OptionsWidget.__module__ == "editor_widgets"
