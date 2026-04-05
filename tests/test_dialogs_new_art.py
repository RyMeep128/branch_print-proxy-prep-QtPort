import dialogs


class _FakeWidget:
    def __init__(self):
        self.hidden = False

    def setVisible(self, visible):
        self.hidden = not visible

    def isHidden(self):
        return self.hidden


class _FakeLabel:
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = value


class _FakeLineEdit:
    def __init__(self, text=""):
        self._text = text
        self._placeholder = ""

    def setPlaceholderText(self, value):
        self._placeholder = value

    def placeholderText(self):
        return self._placeholder

    def setText(self, value):
        self._text = value

    def text(self):
        return self._text


class _FakeDialogState:
    def __init__(self):
        self._context = type("Context", (), {"display_name": "Opt"})()
        self._source = "mpcfill"
        self._search_mode = "name"
        self._min_dpi_widget = _FakeWidget()
        self._max_dpi_widget = _FakeWidget()
        self._search_mode_widget = _FakeWidget()
        self._manual_search_widget = _FakeWidget()
        self._scryfall_set_filter_widget = _FakeWidget()
        self._info_text = _FakeLabel()
        self._helper_text = _FakeLabel()
        self._manual_search_edit = _FakeLineEdit("Opt")
        self._mpcfill_name_search_text = "Opt"
        self._mpcfill_artist_search_text = ""

    def _selected_source(self):
        return self._source

    def _selected_search_mode(self):
        return self._search_mode

    def _apply_search_mode_ui(self):
        return dialogs.HighResPickerDialog._apply_search_mode_ui(self)


def test_apply_source_mode_ui_shows_mpcfill_manual_search_controls():
    dialog_state = _FakeDialogState()

    dialogs.HighResPickerDialog._apply_source_mode_ui(dialog_state)

    assert dialog_state._search_mode_widget.isHidden() is False
    assert dialog_state._manual_search_widget.isHidden() is False
    assert dialog_state._scryfall_set_filter_widget.isHidden() is True
    assert "Search MPCFill" in dialog_state._info_text.value
    assert "card name or artist" in dialog_state._helper_text.value
    assert dialog_state._manual_search_edit.placeholderText() == "Search card name"
    assert dialog_state._manual_search_edit.text() == "Opt"


def test_apply_source_mode_ui_shows_scryfall_set_filter():
    dialog_state = _FakeDialogState()
    dialog_state._source = "scryfall"

    dialogs.HighResPickerDialog._apply_source_mode_ui(dialog_state)

    assert dialog_state._search_mode_widget.isHidden() is True
    assert dialog_state._manual_search_widget.isHidden() is True
    assert dialog_state._scryfall_set_filter_widget.isHidden() is False
    assert "Search Scryfall" in dialog_state._info_text.value
    assert "set code or set name" in dialog_state._helper_text.value


def test_apply_search_mode_ui_restores_name_and_artist_text():
    dialog_state = _FakeDialogState()
    dialog_state._manual_search_edit.setText("Island")
    dialogs.HighResPickerDialog._remember_manual_search_text(dialog_state, "Island")

    dialog_state._search_mode = "artist"
    dialogs.HighResPickerDialog._apply_search_mode_ui(dialog_state)
    assert dialog_state._manual_search_edit.placeholderText() == "Search artist"
    assert dialog_state._manual_search_edit.text() == ""

    dialog_state._manual_search_edit.setText("John Avon")
    dialogs.HighResPickerDialog._remember_manual_search_text(dialog_state, "John Avon")

    dialog_state._search_mode = "name"
    dialogs.HighResPickerDialog._apply_search_mode_ui(dialog_state)
    assert dialog_state._manual_search_edit.placeholderText() == "Search card name"
    assert dialog_state._manual_search_edit.text() == "Island"

    dialog_state._search_mode = "artist"
    dialogs.HighResPickerDialog._apply_search_mode_ui(dialog_state)
    assert dialog_state._manual_search_edit.text() == "John Avon"
