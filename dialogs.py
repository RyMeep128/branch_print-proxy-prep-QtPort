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
    def __init__(self, parent, print_dict, img_dict, card_name):
        super().__init__(parent)
        self.setWindowTitle("Choose Better Front Image")
        self.resize(960, 680)

        self._state = as_project_state(print_dict)
        self._img_dict = img_dict
        self._card_name = card_name
        self._context = high_res_service.build_card_context(card_name, self._state)
        self._candidates = []
        self._thumbnail_cache = {}
        self._preview_cache = {}
        self._applied = False
        self._page_size = 60
        self._page_start = 0
        self._total_result_count = 0
        self._thumbnail_loader = None
        self._page_token = 0

        info_text = QLabel(f"Searching MPCFill for front-face replacements for `{self._context.display_name}`.")
        info_text.setWordWrap(True)
        helper_text = QLabel("Use this only if you want to replace the current front image with a higher-resolution version.")
        helper_text.setWordWrap(True)

        current_override = self._state.get_high_res_override(card_name)
        current_source_text = "Current source: Scryfall import"
        if current_override is not None:
            current_source_text = (
                f"Current source: {current_override.get('source_name', 'MPCFill')} "
                f"[{current_override.get('dpi', '?')} DPI]"
            )
        self._current_source_label = QLabel(current_source_text)
        self._current_source_label.setWordWrap(True)

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
        filters_layout.addWidget(WidgetWithLabel("Min DPI", min_dpi))
        filters_layout.addWidget(WidgetWithLabel("Max DPI", max_dpi))
        filters_layout.addWidget(search_button)
        filters_layout.addStretch()
        self._min_dpi = min_dpi
        self._max_dpi = max_dpi

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
        apply_button = QPushButton("Apply")
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
        layout.addLayout(pagination_layout)
        layout.addWidget(self._status_label)
        layout.addLayout(content_layout)
        layout.addLayout(button_row)
        self.setLayout(layout)

        if CFG.HighResBackendURL.strip():
            self._status_label.setText("Set your DPI filters and click Search to load MPCFill results.")
            QtCore.QTimer.singleShot(0, lambda: self.refresh_results(reset_page=True))
        else:
            self._status_label.setText("Set `HighRes.BackendURL` in config.ini to the MPCFill base URL, then reopen the app.")

    def was_applied(self):
        return self._applied

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

    def refresh_results(self, reset_page=False):
        if not CFG.HighResBackendURL.strip():
            self._warn(
                "High-Res Backend Not Configured",
                "Set `HighRes.BackendURL` in config.ini to the MPCFill base URL, such as `https://mpcfill.com/`, then reopen the app.",
            )
            self._status_label.setText("High-res search is disabled until a backend URL is configured.")
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
                search_page = high_res_service.search_high_res_page(
                    self._context,
                    CFG.HighResBackendURL,
                    min_dpi,
                    max_dpi,
                    page_start=self._page_start,
                    page_size=self._page_size,
                )
            except ValueError as exc:
                error = exc

        self._run_with_popup("Searching MPCFill...", do_search)
        if error is not None:
            self._warn("High-Res Search Failed", str(error))
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
            self._status_label.setText("No high-res matches found for this card.")
            return

        page_number = (self._page_start // self._page_size) + 1
        total_pages = max(1, math.ceil(self._total_result_count / self._page_size))
        start_index = self._page_start + 1
        end_index = min(self._page_start + len(results), self._total_result_count)
        self._status_label.setText(
            f"Showing {start_index}-{end_index} of {self._total_result_count} high-res options (page {page_number}/{total_pages})."
        )
        for candidate in results:
            item = QListWidgetItem(f"{candidate.name}\n{candidate.source_name} | {candidate.dpi} DPI")
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
        self._details_label.setText(
            f"{candidate.name}\n{candidate.source_name}\n{candidate.dpi} DPI\nSource ID: {candidate.source_id}\nID: {candidate.identifier}"
        )
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
                    CFG.HighResBackendURL,
                    make_popup_print_fn(apply_window),
                    getattr(application, "warn_nonfatal", None),
                )
                backside_match = result.backside_match
            except (OSError, ValueError) as exc:
                error = exc

        apply_window = popup(
            self.window() if self.window() is not None else self,
            "Applying high-res image...",
            getattr(application, "_debug_mode", False),
        )
        apply_window.show_during_work(do_apply)
        del apply_window

        if error is not None:
            self._warn("High-Res Apply Failed", str(error))
            return
        self._applied = True
        self._current_source_label.setText(
            f"Current source: {candidate.source_name} [{candidate.dpi} DPI]"
            + (" | front + back applied" if backside_match is not None else "")
        )
        self.accept()


__all__ = [
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
