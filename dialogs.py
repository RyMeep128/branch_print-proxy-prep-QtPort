import datetime
import logging
import math
import os
import platform
import sys
import traceback

import PyQt6.QtCore as QtCore
from PyQt6.QtGui import QCursor, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

import image
import project_library
from background_tasks import HighResThumbnailLoader, make_popup_print_fn, popup
from config import CFG, save_config
from constants import cwd, page_sizes
from models import ProjectState, as_project_state, project_to_dict
from services import deck_import_service, high_res_service, project_service

logger = logging.getLogger(__name__)

_showing_exception_dialog = False


class FileDialogType:
    Open = 0
    Save = 1


def _default_crash_log_path():
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    crash_dir = os.path.join(cwd, "crash_logs")
    os.makedirs(crash_dir, exist_ok=True)
    return os.path.join(crash_dir, f"print-proxy-prep-crash-{timestamp}.log")


def file_dialog(parent, title, root, filter, type):
    function = QFileDialog.getOpenFileName if type == FileDialogType.Open else QFileDialog.getSaveFileName
    choice = function(parent, title, root, filter)[0]
    return choice if choice != "" else None


def project_file_dialog(parent, type, root):
    return file_dialog(parent, "Open Project", root, "Json Files (*.json)", type)


def decklist_file_dialog(parent, root):
    return file_dialog(
        parent,
        "Open Decklist",
        root,
        "Deck Files (*.txt *.csv *.dek *.mtga *.dck);;All Files (*)",
        FileDialogType.Open,
    )


def image_file_dialog(parent, folder):
    choice = file_dialog(
        parent,
        "Open Image",
        folder,
        f"Image Files ({' '.join(image.valid_image_extensions).replace('.', '*.')})",
        FileDialogType.Open,
    )
    return os.path.basename(choice) if choice is not None else None


def format_exception_report(exc_type, exc_value, exc_traceback, context=None):
    lines = [
        "Print Proxy Prep Crash Report",
        f"Timestamp: {datetime.datetime.now().isoformat()}",
        f"Platform: {platform.platform()}",
        f"Python: {sys.version}",
        f"Working Directory: {cwd}",
    ]
    if context:
        lines.append(f"Context: {context}")
    lines.extend(
        [
            "",
            "Exception:",
            "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
        ]
    )
    return "\n".join(lines)


def show_exception_dialog(exc_type, exc_value, exc_traceback, context=None, parent=None):
    global _showing_exception_dialog

    if _showing_exception_dialog:
        return

    _showing_exception_dialog = True
    temp_app = None
    try:
        app = QApplication.instance()
        if app is None:
            temp_app = QApplication(sys.argv)
            app = temp_app

        parent = parent or getattr(app, "_window", None)
        report = format_exception_report(exc_type, exc_value, exc_traceback, context)
        summary = f"{exc_type.__name__}: {exc_value}"

        dialog = QMessageBox(parent)
        dialog.setIcon(QMessageBox.Icon.Critical)
        dialog.setWindowTitle("Unexpected Error")
        dialog.setText("Print Proxy Prep hit an unexpected error.")
        dialog.setInformativeText(summary)
        dialog.setDetailedText(report)

        save_button = dialog.addButton("Save Crash Log", QMessageBox.ButtonRole.ActionRole)
        close_button = dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.setDefaultButton(close_button)
        dialog.exec()

        if dialog.clickedButton() == save_button:
            default_path = _default_crash_log_path()
            selected_path = file_dialog(
                parent,
                "Save Crash Log",
                default_path,
                "Log Files (*.log);;Text Files (*.txt);;All Files (*)",
                FileDialogType.Save,
            )
            if selected_path is None:
                selected_path = default_path
            if not os.path.splitext(selected_path)[1]:
                selected_path += ".log"
            try:
                with open(selected_path, "w", encoding="utf-8") as fp:
                    fp.write(report)
                QMessageBox.information(parent, "Crash Log Saved", f"The crash log was saved to:\n\n{selected_path}")
            except OSError as exc:
                QMessageBox.warning(parent, "Crash Log Save Failed", f"The crash log could not be saved.\n\n{exc}")
    finally:
        _showing_exception_dialog = False
        if temp_app is not None:
            temp_app.quit()


def folder_dialog(parent=None):
    choice = QFileDialog.getExistingDirectory(
        parent,
        "Choose Folder",
        cwd,
        QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks,
    )
    return choice if choice else None


def load_project_file(application, print_dict, img_dict, json_path, print_fn):
    state = print_dict if isinstance(print_dict, ProjectState) else print_dict
    loaded_successfully = project_service.load_project(
        state,
        img_dict,
        json_path,
        print_fn,
        application.warn_nonfatal,
    )
    if loaded_successfully:
        application.set_json_path(json_path)
    return loaded_successfully


def remove_card_from_project_state(print_dict, card_name):
    state = as_project_state(print_dict)
    state.remove_card(card_name)
    if isinstance(print_dict, ProjectState):
        return state

    print_dict.clear()
    print_dict.update(project_to_dict(state))
    return state


def delete_project_with_confirmation(parent, application, project_id, refresh_fn):
    project_entry = project_library.get_project(project_id)
    if project_entry is None:
        refresh_fn()
        return
    confirm = QMessageBox.question(
        parent,
        "Delete Project",
        (
            f"Delete '{project_entry.get('display_name', 'Untitled Project')}'?\n\n"
            "This will permanently delete the saved project file and its project images from disk."
        ),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    if confirm != QMessageBox.StandardButton.Yes:
        return
    try:
        project_library.remove_project(project_id)
    except OSError as exc:
        application.warn_nonfatal("Delete Project Failed", f"The project could not be fully deleted.\n\n{exc}")
        return
    refresh_fn()


class WidgetWithLabel(QWidget):
    def __init__(self, label_text, widget):
        super().__init__()
        label = QLabel(label_text + ":")
        if "&" in label_text:
            label.setBuddy(widget)
        layout = QHBoxLayout()
        layout.addWidget(label)
        layout.addWidget(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self._widget = widget


class ComboBoxWithLabel(WidgetWithLabel):
    def __init__(self, label_text, options, default_option=None):
        combo = QComboBox()
        for option in options:
            combo.addItem(option)
        if default_option is not None and default_option in options:
            combo.setCurrentIndex(options.index(default_option))
        super().__init__(label_text, combo)


class LineEditWithLabel(WidgetWithLabel):
    def __init__(self, label_text, default_text=None):
        super().__init__(label_text, QLineEdit(default_text))


class DeckImportDialog(QDialog):
    def __init__(self, parent, image_dir):
        super().__init__(parent)
        self.setWindowTitle("Import Cards")
        self.resize(560, 420)

        instructions = QLabel(
            "Paste a decklist or load one from a file. Supported formats include lines like `4 Lightning Bolt` and CSV exports with count/name/set_code/collector_number columns."
        )
        instructions.setWordWrap(True)

        self._text_edit = QTextEdit()
        self._text_edit.setAcceptRichText(False)
        self._text_edit.setPlaceholderText(
            "4 Lightning Bolt\n2 Counterspell\n1 Opt (ELD) 59\n\nor CSV with headers like:\ncount,name,set_code,collector_number"
        )
        self._archidekt_url = QLineEdit()
        self._archidekt_url.setPlaceholderText("https://archidekt.com/decks/123456/example-deck")

        load_file_button = QPushButton("Choose File")
        import_button = QPushButton("Import Cards")
        cancel_button = QPushButton("Cancel")

        button_row = QHBoxLayout()
        button_row.addWidget(load_file_button)
        button_row.addStretch()
        button_row.addWidget(import_button)
        button_row.addWidget(cancel_button)

        layout = QVBoxLayout()
        layout.addWidget(instructions)
        layout.addWidget(WidgetWithLabel("Archidekt &URL", self._archidekt_url))
        layout.addWidget(self._text_edit)
        layout.addLayout(button_row)
        self.setLayout(layout)

        self._image_dir = image_dir

        def load_file():
            decklist_path = decklist_file_dialog(self, self._image_dir)
            if decklist_path is None:
                return
            try:
                self._text_edit.setPlainText(deck_import_service.read_decklist_file(decklist_path))
            except OSError as exc:
                QMessageBox.warning(self, "Decklist Load Failed", f"The decklist file could not be loaded.\n\n{exc}")

        def import_deck():
            if len(self.archidekt_url().strip()) > 0 and not deck_import_service.is_archidekt_url(self.archidekt_url()):
                QToolTip.showText(QCursor.pos(), "Enter a valid public Archidekt deck URL")
                return
            if len(self.archidekt_url().strip()) == 0 and len(self.deck_text().strip()) == 0:
                QToolTip.showText(QCursor.pos(), "Paste/load a decklist or enter an Archidekt URL")
                return
            self.accept()

        load_file_button.clicked.connect(load_file)
        import_button.clicked.connect(import_deck)
        cancel_button.clicked.connect(self.reject)

    def deck_text(self):
        return self._text_edit.toPlainText()

    def archidekt_url(self):
        return self._archidekt_url.text().strip()


class AddCardDialog(QDialog):
    def __init__(self, parent, image_dir):
        super().__init__(parent)
        self.setWindowTitle("Add Card")
        self.resize(960, 700)

        self._image_dir = image_dir
        self._card_candidates = []
        self._card_preview_cache = {}
        self._selected_card_value = None
        self._selected_art_candidate_value = None
        self._selected_art_source_value = None
        self._card_page_size = 60
        self._card_page_start = 0
        self._total_card_count = 0

        intro = QLabel(
            "Search Scryfall for the card printing you want to add, then optionally choose custom art from Scryfall or MPCFill."
        )
        intro.setWordWrap(True)

        page_stack = QStackedWidget()
        self._page_stack = page_stack

        card_name_edit = QLineEdit()
        card_name_edit.setPlaceholderText("Search card name")
        self._card_name_edit = card_name_edit

        card_set_filter_edit = QLineEdit()
        card_set_filter_edit.setPlaceholderText("Set code or set name")
        self._card_set_filter_edit = card_set_filter_edit

        card_search_button = QPushButton("Search")
        card_search_button.clicked.connect(lambda: self.refresh_card_results(reset_page=True))

        card_filters_layout = QHBoxLayout()
        card_filters_layout.addWidget(WidgetWithLabel("Card Name", card_name_edit), 2)
        card_filters_layout.addWidget(WidgetWithLabel("Set Filter", card_set_filter_edit), 1)
        card_filters_layout.addWidget(card_search_button)

        card_prev_page_button = QPushButton("Previous 60 Results")
        card_prev_page_button.setEnabled(False)
        card_prev_page_button.clicked.connect(self._go_to_previous_card_page)
        self._card_prev_page_button = card_prev_page_button

        card_next_page_button = QPushButton("Next 60 Results")
        card_next_page_button.setEnabled(False)
        card_next_page_button.clicked.connect(self._go_to_next_card_page)
        self._card_next_page_button = card_next_page_button

        card_page_label = QLabel("Page 0 of 0")
        self._card_page_label = card_page_label

        card_pagination_layout = QHBoxLayout()
        card_pagination_layout.addWidget(card_prev_page_button)
        card_pagination_layout.addWidget(card_next_page_button)
        card_pagination_layout.addWidget(card_page_label)
        card_pagination_layout.addStretch()

        card_results_list = QListWidget()
        card_results_list.setIconSize(QtCore.QSize(90, 126))
        card_results_list.currentRowChanged.connect(self._handle_card_selection_changed)
        card_results_list.itemDoubleClicked.connect(lambda _item: self._go_to_art_step())
        self._card_results_list = card_results_list

        card_preview_label = QLabel("Select a card to preview it here.")
        card_preview_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        card_preview_label.setMinimumSize(300, 420)
        card_preview_label.setFrameShape(QFrame.Shape.StyledPanel)
        card_preview_label.setWordWrap(True)
        self._card_preview_label = card_preview_label

        card_details_label = QLabel("")
        card_details_label.setWordWrap(True)
        self._card_details_label = card_details_label

        card_left_layout = QVBoxLayout()
        card_left_layout.addWidget(QLabel("Scryfall Matches"))
        card_left_layout.addWidget(card_results_list)

        card_right_layout = QVBoxLayout()
        card_right_layout.addWidget(QLabel("Preview"))
        card_right_layout.addWidget(card_preview_label)
        card_right_layout.addWidget(card_details_label)
        card_right_layout.addStretch()

        card_content_layout = QHBoxLayout()
        card_content_layout.addLayout(card_left_layout, 3)
        card_content_layout.addLayout(card_right_layout, 2)

        card_status_label = QLabel("Enter a card name and click Search.")
        card_status_label.setWordWrap(True)
        self._card_status_label = card_status_label

        card_next_button = QPushButton("Next: Art")
        card_next_button.setEnabled(False)
        card_next_button.clicked.connect(self._go_to_art_step)
        self._card_next_button = card_next_button

        card_cancel_button = QPushButton("Cancel")
        card_cancel_button.clicked.connect(self.reject)

        card_button_row = QHBoxLayout()
        card_button_row.addStretch()
        card_button_row.addWidget(card_next_button)
        card_button_row.addWidget(card_cancel_button)

        card_page = QWidget()
        card_page_layout = QVBoxLayout()
        card_page_layout.addLayout(card_filters_layout)
        card_page_layout.addLayout(card_pagination_layout)
        card_page_layout.addWidget(card_status_label)
        card_page_layout.addLayout(card_content_layout)
        card_page_layout.addLayout(card_button_row)
        card_page.setLayout(card_page_layout)

        art_page = QWidget()
        art_page_layout = QVBoxLayout()

        art_heading = QLabel("Choose the art for the card you selected.")
        art_heading.setWordWrap(True)
        self._art_heading = art_heading

        selected_card_label = QLabel("No card selected yet.")
        selected_card_label.setWordWrap(True)
        self._selected_card_label = selected_card_label

        art_summary_label = QLabel("")
        art_summary_label.setWordWrap(True)
        self._art_summary_label = art_summary_label

        art_help_label = QLabel(
            "Use the default Scryfall import art, or open the New Art picker to choose custom art from Scryfall or MPCFill."
        )
        art_help_label.setWordWrap(True)

        choose_custom_art_button = QPushButton("Choose Custom Art")
        choose_custom_art_button.clicked.connect(self._choose_custom_art)

        use_default_art_button = QPushButton("Use Default Art")
        use_default_art_button.clicked.connect(self._use_default_art)

        art_back_button = QPushButton("Back")
        art_back_button.clicked.connect(lambda: self._page_stack.setCurrentIndex(0))

        add_card_button = QPushButton("Add Card")
        add_card_button.clicked.connect(self._accept_add_card)
        self._add_card_button = add_card_button

        art_cancel_button = QPushButton("Cancel")
        art_cancel_button.clicked.connect(self.reject)

        art_actions_row = QHBoxLayout()
        art_actions_row.addWidget(choose_custom_art_button)
        art_actions_row.addWidget(use_default_art_button)
        art_actions_row.addStretch()

        art_button_row = QHBoxLayout()
        art_button_row.addWidget(art_back_button)
        art_button_row.addStretch()
        art_button_row.addWidget(add_card_button)
        art_button_row.addWidget(art_cancel_button)

        art_page_layout.addWidget(art_heading)
        art_page_layout.addWidget(selected_card_label)
        art_page_layout.addWidget(art_help_label)
        art_page_layout.addWidget(art_summary_label)
        art_page_layout.addStretch()
        art_page_layout.addLayout(art_actions_row)
        art_page_layout.addLayout(art_button_row)
        art_page.setLayout(art_page_layout)

        page_stack.addWidget(card_page)
        page_stack.addWidget(art_page)

        layout = QVBoxLayout()
        layout.addWidget(intro)
        layout.addWidget(page_stack)
        self.setLayout(layout)

        self._update_art_summary()

    def selected_card(self):
        return self._selected_card_value

    def selected_art_candidate(self):
        return self._selected_art_candidate_value

    def selected_art_source(self):
        return self._selected_art_source_value

    def _warn(self, title, message):
        application = QApplication.instance()
        if application is not None and hasattr(application, "warn_nonfatal"):
            application.warn_nonfatal(title, message)
        else:
            QMessageBox.warning(self, title, message)

    def _run_with_popup(self, title, work):
        application = QApplication.instance()
        debug_mode = getattr(application, "_debug_mode", False)
        window = self.window() if self.window() is not None else self
        loading_window = popup(window, title, debug_mode)
        loading_window.show_during_work(work)
        del loading_window

    def _candidate_summary_text(self, candidate):
        set_code = str(candidate.set_code or "?").upper()
        set_name = candidate.set_name or set_code
        collector_number = candidate.collector_number or "?"
        return f"{set_name} [{set_code} #{collector_number}]"

    def _candidate_details_text(self, candidate):
        details = [candidate.name]
        if candidate.set_name:
            details.append(f"Set Name: {candidate.set_name}")
        if candidate.set_code and candidate.collector_number:
            details.append(f"Set: {str(candidate.set_code).upper()} #{candidate.collector_number}")
        details.append(f"Filename: {candidate.filename}")
        return "\n".join(details)

    def _selected_card_candidate(self, row=None):
        if row is None:
            row = self._card_results_list.currentRow()
        if row < 0 or row >= len(self._card_candidates):
            return None
        return self._card_candidates[row]

    def _update_card_pagination_controls(self):
        if self._total_card_count <= 0:
            self._card_page_label.setText("Page 0 of 0")
            self._card_prev_page_button.setEnabled(False)
            self._card_next_page_button.setEnabled(False)
            return
        current_page = (self._card_page_start // self._card_page_size) + 1
        total_pages = max(1, math.ceil(self._total_card_count / self._card_page_size))
        self._card_page_label.setText(f"Page {current_page} of {total_pages}")
        self._card_prev_page_button.setEnabled(self._card_page_start > 0)
        self._card_next_page_button.setEnabled(
            self._card_page_start + self._card_page_size < self._total_card_count
        )

    def _go_to_previous_card_page(self):
        if self._card_page_start <= 0:
            return
        self._card_page_start = max(0, self._card_page_start - self._card_page_size)
        self.refresh_card_results(reset_page=False)

    def _go_to_next_card_page(self):
        if self._card_page_start + self._card_page_size >= self._total_card_count:
            return
        self._card_page_start += self._card_page_size
        self.refresh_card_results(reset_page=False)

    def refresh_card_results(self, reset_page=False):
        name_query = self._card_name_edit.text().strip()
        set_filter = self._card_set_filter_edit.text().strip()
        if reset_page:
            self._card_page_start = 0

        search_page = None
        error = None

        def do_search():
            nonlocal search_page, error
            try:
                search_page = deck_import_service.search_scryfall_card_page(
                    name_query,
                    set_filter=set_filter,
                    page_start=self._card_page_start,
                    page_size=self._card_page_size,
                )
            except ValueError as exc:
                error = exc

        self._run_with_popup("Searching Scryfall...", do_search)
        if error is not None:
            self._warn("Card Search Failed", str(error))
            self._card_status_label.setText("Card search failed. Check the warning for details.")
            self._card_candidates = []
            self._card_results_list.clear()
            self._card_next_button.setEnabled(False)
            self._total_card_count = 0
            self._update_card_pagination_controls()
            return

        self._card_candidates = [] if search_page is None else search_page.candidates
        self._total_card_count = 0 if search_page is None else search_page.total_count
        self._card_results_list.clear()
        self._card_next_button.setEnabled(False)
        self._card_preview_label.setText("Select a card to preview it here.")
        self._card_preview_label.setPixmap(QPixmap())
        self._card_details_label.setText("")
        self._update_card_pagination_controls()

        if not self._card_candidates:
            self._card_status_label.setText("No Scryfall card matches found.")
            return

        page_number = (self._card_page_start // self._card_page_size) + 1
        total_pages = max(1, math.ceil(self._total_card_count / self._card_page_size))
        start_index = self._card_page_start + 1
        end_index = min(self._card_page_start + len(self._card_candidates), self._total_card_count)
        self._card_status_label.setText(
            f"Showing {start_index}-{end_index} of {self._total_card_count} Scryfall printings (page {page_number}/{total_pages})."
        )
        for candidate in self._card_candidates:
            item = QListWidgetItem(f"{candidate.name}\n{self._candidate_summary_text(candidate)}")
            thumb_bytes = self._card_preview_cache.get(candidate.thumbnail_url)
            if thumb_bytes:
                pixmap = QPixmap()
                if pixmap.loadFromData(thumb_bytes):
                    item.setIcon(QIcon(pixmap))
            self._card_results_list.addItem(item)
        self._card_results_list.setCurrentRow(0)

    def _handle_card_selection_changed(self, row):
        candidate = self._selected_card_candidate(row)
        self._selected_card_value = candidate
        if candidate is None:
            self._card_next_button.setEnabled(False)
            self._card_details_label.setText("")
            return
        self._card_next_button.setEnabled(True)
        self._card_details_label.setText(self._candidate_details_text(candidate))
        self._update_card_preview(candidate)

    def _update_card_preview(self, candidate):
        cache_key = candidate.preview_url or candidate.thumbnail_url
        if cache_key not in self._card_preview_cache:
            preview_bytes = None
            error = None

            def load_preview():
                nonlocal preview_bytes, error
                try:
                    url = candidate.preview_url or candidate.thumbnail_url
                    if not url:
                        preview_bytes = None
                        return
                    preview_bytes = high_res_service.fetch_preview_bytes(url, cache_kind="preview")
                except (OSError, ValueError) as exc:
                    error = exc

            self._run_with_popup("Loading preview...", load_preview)
            if error is not None:
                self._warn("Preview Load Failed", str(error))
                return
            if preview_bytes is not None and cache_key:
                self._card_preview_cache[cache_key] = preview_bytes

        preview_bytes = self._card_preview_cache.get(cache_key)
        if preview_bytes is None:
            self._card_preview_label.setText("Preview unavailable.")
            self._card_preview_label.setPixmap(QPixmap())
            return

        pixmap = QPixmap()
        pixmap.loadFromData(preview_bytes)
        scaled = pixmap.scaled(
            self._card_preview_label.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self._card_preview_label.setPixmap(scaled)
        self._card_preview_label.setText("")

    def _go_to_art_step(self):
        candidate = self._selected_card_candidate()
        if candidate is None:
            QToolTip.showText(QCursor.pos(), "Choose a card printing first")
            return
        self._selected_card_value = candidate
        self._selected_card_label.setText(
            f"Selected card: {candidate.name} | {self._candidate_summary_text(candidate)}"
        )
        self._update_art_summary()
        self._page_stack.setCurrentIndex(1)

    def _update_art_summary(self):
        if self._selected_art_candidate_value is None:
            self._art_summary_label.setText("Art choice: Default Scryfall import art")
            return
        summary = self._selected_art_candidate_value.source_name
        if self._selected_art_candidate_value.art_source == "scryfall":
            set_code = str(self._selected_art_candidate_value.set_code or "?").upper()
            collector_number = self._selected_art_candidate_value.collector_number or "?"
            summary = f"{summary} [{set_code} #{collector_number}]"
        else:
            summary = f"{summary} [{self._selected_art_candidate_value.dpi} DPI]"
        self._art_summary_label.setText(f"Art choice: Custom art from {summary}")

    def _use_default_art(self):
        self._selected_art_candidate_value = None
        self._selected_art_source_value = None
        self._update_art_summary()

    def _choose_custom_art(self):
        if self._selected_card_value is None:
            QToolTip.showText(QCursor.pos(), "Choose a card printing first")
            return
        temp_state = ProjectState()
        temp_state.image_dir = self._image_dir
        dialog = HighResPickerDialog(
            self,
            temp_state,
            {},
            self._selected_card_value.filename,
            context_override=self._selected_card_value.art_context,
            selection_mode=True,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.was_applied():
            return
        self._selected_art_candidate_value = dialog.selected_candidate()
        self._selected_art_source_value = dialog.selected_source()
        self._update_art_summary()

    def _accept_add_card(self):
        if self._selected_card_value is None:
            QToolTip.showText(QCursor.pos(), "Choose a card printing first")
            return
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(560, 420)

        description = QLabel(
            "Edit application-wide settings stored in config.ini. Most changes apply immediately after saving."
        )
        description.setWordWrap(True)

        display_columns_spin_box = QSpinBox()
        display_columns_spin_box.setRange(2, 10)
        display_columns_spin_box.setSingleStep(1)
        display_columns_spin_box.setValue(CFG.DisplayColumns)
        display_columns = WidgetWithLabel("Display &Columns", display_columns_spin_box)
        display_columns.setToolTip("Number of columns shown in the card grid")

        precropped_checkbox = QCheckBox("Allow Pre-Cropped Images")
        precropped_checkbox.setChecked(CFG.EnableUncrop)
        vibrance_checkbox = QCheckBox("Boost Color Vibrance")
        vibrance_checkbox.setChecked(CFG.VibranceBump)

        max_dpi_spin_box = QSpinBox()
        max_dpi_spin_box.setRange(300, 1200)
        max_dpi_spin_box.setSingleStep(100)
        max_dpi_spin_box.setValue(CFG.MaxDPI)
        max_dpi = WidgetWithLabel("&Max DPI", max_dpi_spin_box)

        paper_sizes_box = ComboBoxWithLabel("Default P&aper Size", list(page_sizes.keys()), CFG.DefaultPageSize)
        backend_url = LineEditWithLabel("High-Res Backend &URL", CFG.HighResBackendURL)

        cache_ttl_spin_box = QSpinBox()
        cache_ttl_spin_box.setRange(0, 24 * 60 * 60)
        cache_ttl_spin_box.setSingleStep(60)
        cache_ttl_spin_box.setSuffix(" sec")
        cache_ttl_spin_box.setValue(CFG.HighResCacheTTLSeconds)
        cache_ttl = WidgetWithLabel("High-Res Cache &TTL", cache_ttl_spin_box)

        search_cache_spin_box = QSpinBox()
        search_cache_spin_box.setRange(1, 1024)
        search_cache_spin_box.setSingleStep(1)
        search_cache_spin_box.setSuffix(" MB")
        search_cache_spin_box.setValue(CFG.HighResSearchCacheMemoryMB)
        search_cache = WidgetWithLabel("Search Cache Memory", search_cache_spin_box)

        image_cache_spin_box = QSpinBox()
        image_cache_spin_box.setRange(1, 2048)
        image_cache_spin_box.setSingleStep(1)
        image_cache_spin_box.setSuffix(" MB")
        image_cache_spin_box.setValue(CFG.HighResImageCacheMemoryMB)
        image_cache = WidgetWithLabel("Image Cache Memory", image_cache_spin_box)

        fields_layout = QVBoxLayout()
        for widget in [
            description,
            display_columns,
            precropped_checkbox,
            vibrance_checkbox,
            max_dpi,
            paper_sizes_box,
            backend_url,
            cache_ttl,
            search_cache,
            image_cache,
        ]:
            fields_layout.addWidget(widget)
        fields_layout.addStretch()

        fields_widget = QWidget()
        fields_widget.setLayout(fields_layout)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setWidget(fields_widget)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(scroll_area)
        layout.addWidget(button_box)
        self.setLayout(layout)

        self._display_columns_spin_box = display_columns_spin_box
        self._precropped_checkbox = precropped_checkbox
        self._vibrance_checkbox = vibrance_checkbox
        self._max_dpi_spin_box = max_dpi_spin_box
        self._paper_sizes = paper_sizes_box._widget
        self._backend_url = backend_url._widget
        self._cache_ttl_spin_box = cache_ttl_spin_box
        self._search_cache_spin_box = search_cache_spin_box
        self._image_cache_spin_box = image_cache_spin_box

    def apply(self):
        CFG.DisplayColumns = self._display_columns_spin_box.value()
        CFG.EnableUncrop = self._precropped_checkbox.isChecked()
        CFG.VibranceBump = self._vibrance_checkbox.isChecked()
        CFG.MaxDPI = self._max_dpi_spin_box.value()
        CFG.DefaultPageSize = self._paper_sizes.currentText()
        CFG.HighResBackendURL = self._backend_url.text().strip()
        CFG.HighResCacheTTLSeconds = self._cache_ttl_spin_box.value()
        CFG.HighResSearchCacheMemoryMB = self._search_cache_spin_box.value()
        CFG.HighResImageCacheMemoryMB = self._image_cache_spin_box.value()
        save_config(CFG)


class HighResPickerDialog(QDialog):
    def __init__(
        self,
        parent,
        print_dict,
        img_dict,
        card_name,
        context_override=None,
        selection_mode=False,
    ):
        super().__init__(parent)
        self._selection_mode = bool(selection_mode)
        self.setWindowTitle("Choose New Front Art" if not self._selection_mode else "Choose Art")
        self.resize(960, 680)

        self._state = as_project_state(print_dict)
        self._img_dict = img_dict
        self._card_name = card_name
        self._context = context_override or high_res_service.build_card_context(card_name, self._state)
        self._candidates = []
        self._thumbnail_cache = {}
        self._preview_cache = {}
        self._applied = False
        self._selected_candidate_value = None
        self._selected_source_value = None
        self._page_size = 60
        self._page_start = 0
        self._total_result_count = 0
        self._thumbnail_loader = None
        self._page_token = 0
        self._mpcfill_name_search_text = self._context.display_name
        self._mpcfill_artist_search_text = ""

        info_text = QLabel(
            f"Search for new front art for `{self._context.display_name}`."
            if not self._selection_mode
            else f"Choose art for `{self._context.display_name}`."
        )
        info_text.setWordWrap(True)
        helper_text = QLabel(
            "Choose either Scryfall print art or MPCFill art to replace the current front image."
        )
        helper_text.setWordWrap(True)
        self._info_text = info_text
        self._helper_text = helper_text

        current_override = None if self._selection_mode else self._state.get_high_res_override(card_name)
        current_source_text = (
            "Selected art will be applied after the card is added."
            if self._selection_mode
            else self._format_override_source_text(current_override)
        )
        self._current_source_label = QLabel(current_source_text)
        self._current_source_label.setWordWrap(True)

        source_combo = QComboBox()
        source_combo.addItem("MPCFill", "mpcfill")
        source_combo.addItem("Scryfall", "scryfall")
        default_source = "mpcfill"
        if current_override is not None and current_override.get("art_source") == "scryfall":
            default_source = "scryfall"
        source_combo.setCurrentIndex(0 if default_source == "mpcfill" else 1)
        source_combo.currentIndexChanged.connect(self._handle_source_changed)
        self._source_combo = source_combo
        self._source_widget = WidgetWithLabel("Source", source_combo)

        search_mode_combo = QComboBox()
        search_mode_combo.addItem("Name", "name")
        search_mode_combo.addItem("Artist", "artist")
        search_mode_combo.currentIndexChanged.connect(self._handle_search_mode_changed)
        self._search_mode_combo = search_mode_combo
        self._search_mode_widget = WidgetWithLabel("Search By", search_mode_combo)

        manual_search_edit = QLineEdit(self._context.display_name)
        manual_search_edit.setPlaceholderText("Search card name")
        manual_search_edit.textChanged.connect(self._remember_manual_search_text)
        self._manual_search_edit = manual_search_edit
        self._manual_search_widget = WidgetWithLabel("Search", manual_search_edit)

        scryfall_set_filter_edit = QLineEdit()
        scryfall_set_filter_edit.setPlaceholderText("Set code or set name")
        self._scryfall_set_filter_edit = scryfall_set_filter_edit
        self._scryfall_set_filter_widget = WidgetWithLabel("Set Filter", scryfall_set_filter_edit)

        min_dpi = QSpinBox()
        min_dpi.setRange(0, 5000)
        min_dpi.setSingleStep(50)
        min_dpi.setValue(300)
        max_dpi = QSpinBox()
        max_dpi.setRange(0, 5000)
        max_dpi.setSingleStep(50)
        max_dpi.setValue(1500)
        search_button = QPushButton("Search")
        search_button.clicked.connect(lambda: self.refresh_results(reset_page=True))

        filters_layout = QHBoxLayout()
        min_dpi_widget = WidgetWithLabel("Min DPI", min_dpi)
        max_dpi_widget = WidgetWithLabel("Max DPI", max_dpi)
        filters_layout.addWidget(self._source_widget)
        filters_layout.addWidget(min_dpi_widget)
        filters_layout.addWidget(max_dpi_widget)
        filters_layout.addWidget(search_button)
        filters_layout.addStretch()
        self._min_dpi = min_dpi
        self._max_dpi = max_dpi
        self._min_dpi_widget = min_dpi_widget
        self._max_dpi_widget = max_dpi_widget

        search_controls_layout = QHBoxLayout()
        search_controls_layout.addWidget(self._search_mode_widget)
        search_controls_layout.addWidget(self._manual_search_widget, 1)
        search_controls_layout.addWidget(self._scryfall_set_filter_widget, 1)
        search_controls_layout.addStretch()

        prev_page_button = QPushButton("Previous 60 Results")
        prev_page_button.setEnabled(False)
        prev_page_button.clicked.connect(self._go_to_previous_page)
        self._prev_page_button = prev_page_button
        next_page_button = QPushButton("Next 60 Results")
        next_page_button.setEnabled(False)
        next_page_button.clicked.connect(self._go_to_next_page)
        self._next_page_button = next_page_button
        self._page_label = QLabel("Page 0 of 0")

        pagination_layout = QHBoxLayout()
        pagination_layout.addWidget(prev_page_button)
        pagination_layout.addWidget(next_page_button)
        pagination_layout.addWidget(self._page_label)
        pagination_layout.addStretch()

        results_list = QListWidget()
        results_list.setIconSize(QtCore.QSize(90, 126))
        results_list.currentRowChanged.connect(self._handle_selection_changed)
        results_list.itemDoubleClicked.connect(lambda _item: self.apply_selected())
        self._results_list = results_list

        preview_label = QLabel("Select a result to preview it here.")
        preview_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        preview_label.setMinimumSize(300, 420)
        preview_label.setFrameShape(QFrame.Shape.StyledPanel)
        preview_label.setWordWrap(True)
        self._preview_label = preview_label
        self._details_label = QLabel("")
        self._details_label.setWordWrap(True)

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Matches"))
        left_layout.addWidget(results_list)
        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Preview"))
        right_layout.addWidget(preview_label)
        right_layout.addWidget(self._details_label)
        right_layout.addStretch()

        content_layout = QHBoxLayout()
        content_layout.addLayout(left_layout, 3)
        content_layout.addLayout(right_layout, 2)

        self._status_label = QLabel("")
        apply_button = QPushButton("Apply" if not self._selection_mode else "Select Art")
        apply_button.setEnabled(False)
        apply_button.clicked.connect(self.apply_selected)
        self._apply_button = apply_button
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(apply_button)
        button_row.addWidget(cancel_button)

        layout = QVBoxLayout()
        layout.addWidget(info_text)
        layout.addWidget(helper_text)
        layout.addWidget(self._current_source_label)
        layout.addLayout(filters_layout)
        layout.addLayout(search_controls_layout)
        layout.addLayout(pagination_layout)
        layout.addWidget(self._status_label)
        layout.addLayout(content_layout)
        layout.addLayout(button_row)
        self.setLayout(layout)

        self._apply_source_mode_ui()
        QtCore.QTimer.singleShot(0, lambda: self._auto_refresh_initial_results())

    def was_applied(self):
        return self._applied

    def selected_candidate(self):
        return self._selected_candidate_value

    def selected_source(self):
        return self._selected_source_value

    def _warn(self, title, message):
        application = QApplication.instance()
        if application is not None and hasattr(application, "warn_nonfatal"):
            application.warn_nonfatal(title, message)
        else:
            QMessageBox.warning(self, title, message)

    def _run_with_popup(self, title, work):
        application = QApplication.instance()
        debug_mode = getattr(application, "_debug_mode", False)
        window = self.window() if self.window() is not None else self
        loading_window = popup(window, title, debug_mode)
        loading_window.show_during_work(work)
        del loading_window

    def _selected_source(self):
        return str(self._source_combo.currentData() or "mpcfill")

    def _selected_search_mode(self):
        return str(self._search_mode_combo.currentData() or "name")

    def _format_override_source_text(self, override):
        if override is None:
            return "Current source: Scryfall import"
        source_name = override.get("source_name") or (
            "Scryfall" if override.get("art_source") == "scryfall" else "MPCFill"
        )
        dpi = override.get("dpi")
        if isinstance(dpi, int) and dpi > 0:
            return f"Current source: {source_name} [{dpi} DPI]"
        set_code = override.get("set_code")
        collector_number = override.get("collector_number")
        if set_code and collector_number:
            return f"Current source: {source_name} [{str(set_code).upper()} #{collector_number}]"
        return f"Current source: {source_name}"

    def _candidate_summary_text(self, candidate):
        if candidate.art_source == "scryfall":
            set_code = candidate.set_code or "?"
            collector_number = candidate.collector_number or "?"
            if candidate.set_name:
                return f"{candidate.source_name} | {candidate.set_name} [{str(set_code).upper()} #{collector_number}]"
            return f"{candidate.source_name} | {str(set_code).upper()} #{collector_number}"
        return f"{candidate.source_name} | {candidate.dpi} DPI"

    def _candidate_details_text(self, candidate):
        details = [candidate.name, candidate.source_name]
        if candidate.art_source == "scryfall":
            if candidate.set_name:
                details.append(f"Set Name: {candidate.set_name}")
            if candidate.set_code and candidate.collector_number:
                details.append(f"Set: {str(candidate.set_code).upper()} #{candidate.collector_number}")
        else:
            details.append(f"{candidate.dpi} DPI")
            details.append(f"Source ID: {candidate.source_id}")
        details.append(f"ID: {candidate.identifier}")
        return "\n".join(details)

    def _apply_source_mode_ui(self):
        is_mpcfill = self._selected_source() == "mpcfill"
        self._min_dpi_widget.setVisible(is_mpcfill)
        self._max_dpi_widget.setVisible(is_mpcfill)
        self._search_mode_widget.setVisible(is_mpcfill)
        self._manual_search_widget.setVisible(is_mpcfill)
        self._scryfall_set_filter_widget.setVisible(not is_mpcfill)
        if is_mpcfill:
            self._info_text.setText(
                f"Search MPCFill for new front art for `{self._context.display_name}`."
            )
            self._helper_text.setText(
                "MPCFill results are treated as source art and cropped to the project card size when applied. Search by card name or artist."
            )
            self._apply_search_mode_ui()
        else:
            self._info_text.setText(
                f"Search Scryfall print variants for `{self._context.display_name}`."
            )
            self._helper_text.setText(
                "Scryfall results use full-card print images and do not use the MPCFill DPI filters. Filter printings by set code or set name."
            )

    def _set_idle_status_for_source(self):
        if self._selected_source() == "mpcfill":
            if CFG.HighResBackendURL.strip():
                self._status_label.setText("Set your DPI filters and click Search to load MPCFill art.")
            else:
                self._status_label.setText(
                    "Set `HighRes.BackendURL` in config.ini to the MPCFill base URL to use MPCFill art."
                )
            return
        self._status_label.setText("Click Search to load Scryfall print art.")

    def _remember_manual_search_text(self, text):
        if self._selected_search_mode() == "artist":
            self._mpcfill_artist_search_text = text
        else:
            self._mpcfill_name_search_text = text

    def _apply_search_mode_ui(self):
        if self._selected_search_mode() == "artist":
            self._manual_search_edit.setPlaceholderText("Search artist")
            if self._manual_search_edit.text() != self._mpcfill_artist_search_text:
                self._manual_search_edit.setText(self._mpcfill_artist_search_text)
        else:
            self._manual_search_edit.setPlaceholderText("Search card name")
            target_text = self._mpcfill_name_search_text or self._context.display_name
            if self._manual_search_edit.text() != target_text:
                self._manual_search_edit.setText(target_text)

    def _clear_results(self):
        self._stop_thumbnail_loader()
        self._candidates = []
        self._results_list.clear()
        self._apply_button.setEnabled(False)
        self._preview_label.setText("Select a result to preview it here.")
        self._preview_label.setPixmap(QPixmap())
        self._details_label.setText("")
        self._total_result_count = 0
        self._update_pagination_controls()

    def _auto_refresh_initial_results(self):
        self._apply_source_mode_ui()
        self._set_idle_status_for_source()
        if self._selected_source() == "scryfall" or CFG.HighResBackendURL.strip():
            self.refresh_results(reset_page=True, warn_on_missing_backend=False)

    def _handle_source_changed(self, *_args):
        self._page_start = 0
        self._apply_source_mode_ui()
        self._clear_results()
        self._set_idle_status_for_source()
        if self._selected_source() == "scryfall" or CFG.HighResBackendURL.strip():
            self.refresh_results(reset_page=True, warn_on_missing_backend=False)

    def _handle_search_mode_changed(self, *_args):
        self._apply_search_mode_ui()

    def _stop_thumbnail_loader(self):
        if self._thumbnail_loader is not None:
            self._thumbnail_loader.cancel()
            self._thumbnail_loader.wait(2000)
            self._thumbnail_loader = None

    def closeEvent(self, event):
        self._stop_thumbnail_loader()
        super().closeEvent(event)

    def reject(self):
        self._stop_thumbnail_loader()
        super().reject()

    @QtCore.pyqtSlot(int, str, bytes)
    def _handle_thumbnail_loaded(self, page_token, identifier, data):
        if page_token != self._page_token:
            return
        self._thumbnail_cache[identifier] = data
        for row, candidate in enumerate(self._candidates):
            if candidate.identifier != identifier:
                continue
            item = self._results_list.item(row)
            if item is None:
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                item.setIcon(QIcon(pixmap))
            return

    def _start_thumbnail_loader(self, candidates):
        self._stop_thumbnail_loader()
        pending = []
        for row, candidate in enumerate(candidates):
            if not candidate.small_thumbnail_url:
                continue
            if candidate.identifier in self._thumbnail_cache:
                continue
            cached = high_res_service.get_cached_thumbnail_bytes(candidate.small_thumbnail_url)
            if cached is not None:
                self._thumbnail_cache[candidate.identifier] = cached
                item = self._results_list.item(row)
                if item is not None:
                    pixmap = QPixmap()
                    if pixmap.loadFromData(cached):
                        item.setIcon(QIcon(pixmap))
                continue
            pending.append((row, candidate.identifier, candidate.small_thumbnail_url))
        if not pending:
            return
        self._page_token += 1
        loader = HighResThumbnailLoader(self._page_token, pending)
        loader.thumbnail_loaded.connect(self._handle_thumbnail_loaded)
        loader.finished.connect(lambda: setattr(self, "_thumbnail_loader", None))
        self._thumbnail_loader = loader
        loader.start()

    def _update_pagination_controls(self):
        if self._total_result_count <= 0:
            self._page_label.setText("Page 0 of 0")
            self._prev_page_button.setEnabled(False)
            self._next_page_button.setEnabled(False)
            return
        current_page = (self._page_start // self._page_size) + 1
        total_pages = max(1, math.ceil(self._total_result_count / self._page_size))
        self._page_label.setText(f"Page {current_page} of {total_pages}")
        self._prev_page_button.setEnabled(self._page_start > 0)
        self._next_page_button.setEnabled(self._page_start + self._page_size < self._total_result_count)

    def _go_to_previous_page(self):
        if self._page_start <= 0:
            return
        self._page_start = max(0, self._page_start - self._page_size)
        self.refresh_results(reset_page=False)

    def _go_to_next_page(self):
        if self._page_start + self._page_size >= self._total_result_count:
            return
        self._page_start += self._page_size
        self.refresh_results(reset_page=False)

    def refresh_results(self, reset_page=False, warn_on_missing_backend=True):
        source = self._selected_source()
        search_mode = self._selected_search_mode()
        search_text = self._manual_search_edit.text()
        set_filter = self._scryfall_set_filter_edit.text()
        if source == "mpcfill" and not CFG.HighResBackendURL.strip():
            if warn_on_missing_backend:
                self._warn(
                    "MPCFill Backend Not Configured",
                    "Set `HighRes.BackendURL` in config.ini to the MPCFill base URL, such as `https://mpcfill.com/`, then reopen the app.",
                )
            self._status_label.setText("MPCFill art is disabled until a backend URL is configured.")
            return

        if reset_page:
            self._page_start = 0
        min_dpi = self._min_dpi.value()
        max_dpi = self._max_dpi.value()
        if min_dpi > max_dpi:
            max_dpi = min_dpi
            self._max_dpi.setValue(max_dpi)

        search_page = None
        error = None

        def do_search():
            nonlocal search_page, error
            try:
                search_page = high_res_service.search_new_art_page(
                    self._context,
                    source,
                    CFG.HighResBackendURL,
                    min_dpi,
                    max_dpi,
                    page_start=self._page_start,
                    page_size=self._page_size,
                    search_text=search_text,
                    search_mode=search_mode,
                    set_filter=set_filter,
                )
            except ValueError as exc:
                error = exc

        popup_title = "Searching MPCFill..." if source == "mpcfill" else "Searching Scryfall..."
        self._run_with_popup(popup_title, do_search)
        if error is not None:
            self._warn("New Art Search Failed", str(error))
            self._status_label.setText("Search failed. Check the warning for details.")
            self._total_result_count = 0
            self._update_pagination_controls()
            return

        results = [] if search_page is None else search_page.candidates
        self._total_result_count = 0 if search_page is None else search_page.total_count
        self._candidates = results
        self._results_list.clear()
        self._apply_button.setEnabled(False)
        self._preview_label.setText("Select a result to preview it here.")
        self._preview_label.setPixmap(QPixmap())
        self._details_label.setText("")
        self._update_pagination_controls()

        if not results:
            self._status_label.setText("No new art matches found for this card.")
            return

        page_number = (self._page_start // self._page_size) + 1
        total_pages = max(1, math.ceil(self._total_result_count / self._page_size))
        start_index = self._page_start + 1
        end_index = min(self._page_start + len(results), self._total_result_count)
        self._status_label.setText(
            f"Showing {start_index}-{end_index} of {self._total_result_count} new art options (page {page_number}/{total_pages})."
        )
        for candidate in results:
            item = QListWidgetItem(f"{candidate.name}\n{self._candidate_summary_text(candidate)}")
            thumb_bytes = self._thumbnail_cache.get(candidate.identifier)
            if thumb_bytes:
                pixmap = QPixmap()
                pixmap.loadFromData(thumb_bytes)
                item.setIcon(QIcon(pixmap))
            self._results_list.addItem(item)
        self._start_thumbnail_loader(results)
        self._results_list.setCurrentRow(0)

    def _selected_candidate(self, row=None):
        if row is None:
            row = self._results_list.currentRow()
        if row < 0 or row >= len(self._candidates):
            return None
        return self._candidates[row]

    def _handle_selection_changed(self, row):
        candidate = self._selected_candidate(row)
        if candidate is None:
            self._apply_button.setEnabled(False)
            self._details_label.setText("")
            return
        self._apply_button.setEnabled(True)
        self._details_label.setText(self._candidate_details_text(candidate))
        self._update_preview(candidate)

    def _update_preview(self, candidate):
        if candidate.identifier not in self._preview_cache:
            error = None
            preview_bytes = None

            def load_preview():
                nonlocal preview_bytes, error
                try:
                    url = candidate.medium_thumbnail_url or candidate.small_thumbnail_url
                    if not url:
                        preview_bytes = None
                        return
                    preview_bytes = high_res_service.fetch_preview_bytes(url, cache_kind="preview")
                except (OSError, ValueError) as exc:
                    error = exc

            self._run_with_popup("Loading preview...", load_preview)
            if error is not None:
                self._warn("Preview Load Failed", str(error))
                return
            if preview_bytes is not None:
                self._preview_cache[candidate.identifier] = preview_bytes

        preview_bytes = self._preview_cache.get(candidate.identifier)
        if preview_bytes is None:
            self._preview_label.setText("Preview unavailable.")
            self._preview_label.setPixmap(QPixmap())
            return

        pixmap = QPixmap()
        pixmap.loadFromData(preview_bytes)
        scaled = pixmap.scaled(
            self._preview_label.size(),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self._preview_label.setPixmap(scaled)
        self._preview_label.setText("")

    def apply_selected(self):
        candidate = self._selected_candidate()
        if candidate is None:
            return
        if self._selection_mode:
            self._selected_candidate_value = candidate
            self._selected_source_value = self._selected_source()
            self._applied = True
            self.accept()
            return
        application = QApplication.instance()
        error = None
        backside_match = None

        def do_apply():
            nonlocal error, backside_match
            try:
                result = high_res_service.apply_candidate_to_project(
                    self._state,
                    self._img_dict,
                    self._card_name,
                    candidate,
                    self._selected_source(),
                    CFG.HighResBackendURL,
                    make_popup_print_fn(apply_window),
                    getattr(application, "warn_nonfatal", None),
                )
                backside_match = result.backside_match
            except (OSError, ValueError) as exc:
                error = exc

        apply_window = popup(
            self.window() if self.window() is not None else self,
            "Applying new art...",
            getattr(application, "_debug_mode", False),
        )
        apply_window.show_during_work(do_apply)
        del apply_window

        if error is not None:
            self._warn("New Art Apply Failed", str(error))
            return
        self._applied = True
        self._current_source_label.setText(
            self._format_override_source_text(self._state.get_high_res_override(self._card_name))
        )
        if backside_match is not None:
            self._current_source_label.setText(self._current_source_label.text() + " | front + back applied")
        self.accept()


__all__ = [
    "AddCardDialog",
    "ComboBoxWithLabel",
    "DeckImportDialog",
    "FileDialogType",
    "HighResPickerDialog",
    "LineEditWithLabel",
    "SettingsDialog",
    "WidgetWithLabel",
    "decklist_file_dialog",
    "delete_project_with_confirmation",
    "file_dialog",
    "format_exception_report",
    "folder_dialog",
    "image_file_dialog",
    "load_project_file",
    "project_file_dialog",
    "remove_card_from_project_state",
    "show_exception_dialog",
]
