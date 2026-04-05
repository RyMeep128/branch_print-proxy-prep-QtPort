import dialogs
import high_res


class _FakeLabel:
    def __init__(self):
        self.value = ""

    def setText(self, value):
        self.value = value


class _FakePageStack:
    def __init__(self):
        self.index = 0

    def setCurrentIndex(self, index):
        self.index = index


class _FakeAddCardDialogState:
    def __init__(self):
        self._selected_art_candidate_value = None
        self._art_summary_label = _FakeLabel()
        self._selected_card_value = type(
            "Candidate",
            (),
            {
                "name": "Opt",
                "set_name": "Tenth Edition",
                "set_code": "10e",
                "collector_number": "94",
            },
        )()
        self._selected_card_label = _FakeLabel()
        self._page_stack = _FakePageStack()

    def _candidate_summary_text(self, candidate):
        return dialogs.AddCardDialog._candidate_summary_text(self, candidate)

    def _selected_card_candidate(self):
        return self._selected_card_value

    def _update_art_summary(self):
        return dialogs.AddCardDialog._update_art_summary(self)


def test_add_card_dialog_uses_default_art_summary_when_no_custom_art_is_selected():
    dialog_state = _FakeAddCardDialogState()

    dialogs.AddCardDialog._update_art_summary(dialog_state)

    assert dialog_state._art_summary_label.value == "Art choice: Default Scryfall import art"


def test_add_card_dialog_shows_custom_art_summary():
    dialog_state = _FakeAddCardDialogState()
    dialog_state._selected_art_candidate_value = high_res.HighResCandidate(
        identifier="art-1",
        name="Opt",
        dpi=1200,
        extension="png",
        download_link="https://example.test/opt.png",
        small_thumbnail_url="thumb",
        medium_thumbnail_url="preview",
        source_id=1,
        source_name="MPCFill",
        art_source="mpcfill",
    )

    dialogs.AddCardDialog._update_art_summary(dialog_state)

    assert dialog_state._art_summary_label.value == "Art choice: Custom art from MPCFill [1200 DPI]"


def test_add_card_dialog_moves_to_art_step_with_selected_card():
    dialog_state = _FakeAddCardDialogState()

    dialogs.AddCardDialog._go_to_art_step(dialog_state)

    assert dialog_state._selected_card_label.value == "Selected card: Opt | Tenth Edition [10E #94]"
    assert dialog_state._page_stack.index == 1
