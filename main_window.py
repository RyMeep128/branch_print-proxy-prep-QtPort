import os
import re
import sys
import math
import json
import traceback
import datetime
import platform
import threading
import functools
import subprocess
import logging
from enum import Enum
from copy import deepcopy

import PyQt6.QtCore as QtCore
from PyQt6.QtGui import (
    QPixmap,
    QIntValidator,
    QPainter,
    QPainterPath,
    QCursor,
    QIcon,
    QTransform,
)
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QLabel,
    QPushButton,
    QLineEdit,
    QGridLayout,
    QVBoxLayout,
    QHBoxLayout,
    QStackedLayout,
    QStackedWidget,
    QScrollArea,
    QStyle,
    QCommonStyle,
    QSizePolicy,
    QGroupBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QToolTip,
    QCheckBox,
    QTabWidget,
    QSplitter,
    QFileDialog,
    QMessageBox,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QDialogButtonBox,
    QInputDialog,
)

import image
import project_library
from config import CFG, save_config
from constants import (
    card_ratio,
    card_size_without_bleed_inch,
    cwd,
    low_dpi_warning_threshold,
    page_sizes,
)
from models import ProjectState
from util import inch_to_mm, mm_to_inch, open_folder, point_to_inch, resource_path
import fallback_image as fallback
from background_tasks import HighResThumbnailLoader, make_popup_print_fn, popup
from dialogs import (
    delete_project_with_confirmation,
    load_project_file,
    remove_card_from_project_state,
    show_exception_dialog,
)
from editor_widgets import (
    CardGrid,
    CardScrollArea,
    CardTabs,
    EditorPage,
    OptionsWidget,
    PrintPreview,
    ProjectDashboardPage,
)
from services import deck_import_service, high_res_service, pdf_service, project_service

logger = logging.getLogger(__name__)

_showing_exception_dialog = False
RECOVERABLE_EDITOR_LOAD_ERRORS = (OSError, ValueError, TypeError, json.JSONDecodeError)


def install_exception_handlers():
    def excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        show_exception_dialog(exc_type, exc_value, exc_traceback)

    sys.excepthook = excepthook

    if hasattr(threading, "excepthook"):
        def thread_excepthook(args):
            if issubclass(args.exc_type, KeyboardInterrupt):
                return
            context = f"Background thread: {getattr(args.thread, 'name', 'unknown')}"
            show_exception_dialog(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                context=context,
            )

        threading.excepthook = thread_excepthook


class PrintProxyPrepApplication(QApplication):
    _nonfatal_error = QtCore.pyqtSignal(str, str)

    def __init__(self, argv):
        super().__init__(argv)

        self._settings_loaded = False
        self._debug_mode = "--debug" in sys.argv
        self._pending_warnings = []

        self._nonfatal_error.connect(self._show_nonfatal_error)

        self.load()

    def close(self):
        self.save()

    def set_window(self, window):
        self._window = window
        if self._settings_loaded:
            window.restoreGeometry(self._window_geometry)
            window.restoreState(self._window_state)
            self._window_geometry = None
            self._window_state = None
        for title, message in self._pending_warnings:
            self._show_nonfatal_error(title, message)
        self._pending_warnings.clear()

    def json_path(self):
        window = getattr(self, "_window", None)
        if window is not None and hasattr(window, "current_project_path"):
            return window.current_project_path()
        return os.path.join(cwd, "print.json")

    def set_json_path(self, json_path):
        window = getattr(self, "_window", None)
        if window is not None and hasattr(window, "set_current_project_path"):
            window.set_current_project_path(json_path)

    def save(self):
        settings = QtCore.QSettings("Proxy", "PDF Proxy Printer")
        settings.setValue("version", "1.0.0")
        settings.setValue("geometry", self._window.saveGeometry())
        settings.setValue("state", self._window.saveState())

    def load(self):
        settings = QtCore.QSettings("Proxy", "PDF Proxy Printer")
        if settings.contains("version"):
            self._window_geometry = settings.value("geometry")
            self._window_state = settings.value("state")
            self._settings_loaded = True

    def warn_nonfatal(self, title, message):
        self._nonfatal_error.emit(title, message)

    def show_home(self):
        if hasattr(self, "_window"):
            self._window.show_home()

    def show_project_explorer(self):
        if hasattr(self, "_window"):
            self._window.show_project_explorer()

    def open_blank_editor(self):
        if hasattr(self, "_window"):
            self._window.open_blank_editor()

    def open_managed_project(self, project_id):
        if hasattr(self, "_window"):
            self._window.open_managed_project(project_id)

    def import_and_open_project(self, path):
        if hasattr(self, "_window"):
            self._window.import_and_open_project(path)

    def save_active_project(self, state):
        if hasattr(self, "_window"):
            return self._window.save_active_project(state)
        return None

    def set_project_thumbnail(self, card_name):
        if hasattr(self, "_window"):
            self._window.set_project_thumbnail(card_name)

    def clear_project_thumbnail_if_matches(self, card_name):
        if hasattr(self, "_window"):
            self._window.clear_project_thumbnail_if_matches(card_name)

    def autosave_managed_session(self):
        if hasattr(self, "_window"):
            self._window.autosave_managed_session()

    @QtCore.pyqtSlot(str, str)
    def _show_nonfatal_error(self, title, message):
        parent = getattr(self, "_window", None)
        if parent is None:
            self._pending_warnings.append((title, message))
            return
        QMessageBox.warning(parent, title, message)


def init():
    return PrintProxyPrepApplication(sys.argv)


class AppShellWindow(QMainWindow):
    def __init__(self, application):
        super().__init__()

        self.setWindowTitle("PDF Proxy Printer")
        icon = QIcon(resource_path() + "/proxy.png")
        self.setWindowIcon(icon)
        if sys.platform == "win32":
            import ctypes

            myappid = "proxy.printer"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

        self._application = application
        self._current_project_path = os.path.join(cwd, "print.json")
        self._active_session = None
        self._editor_page = None

        stack = QStackedWidget()
        self._stack = stack
        self._dashboard_page = ProjectDashboardPage(application)
        stack.addWidget(self._dashboard_page)
        self.setCentralWidget(stack)
        self._dashboard_page.refresh_projects()

    def current_project_path(self):
        if self._active_session is not None and self._active_session.get("project_path"):
            return self._active_session["project_path"]
        return self._current_project_path

    def set_current_project_path(self, json_path):
        self._current_project_path = json_path
        if self._active_session is not None:
            self._active_session["project_path"] = json_path

    def _set_active_editor(self, editor_page, session):
        if self._editor_page is not None:
            self._stack.removeWidget(self._editor_page)
            self._editor_page.deleteLater()
        self._editor_page = editor_page
        self._active_session = session
        self._current_project_path = session.get("project_path") or self._current_project_path
        self._stack.addWidget(editor_page)
        self._stack.setCurrentWidget(editor_page)
        self._update_window_title()

    def _clear_active_session(self):
        if self._editor_page is not None:
            self._stack.removeWidget(self._editor_page)
            self._editor_page.deleteLater()
        self._active_session = None
        self._editor_page = None
        self._update_window_title()

    def _update_window_title(self):
        if self._active_session is None:
            self.setWindowTitle("PDF Proxy Printer")
            return
        name = self._active_session.get("display_name") or "Untitled Project"
        self.setWindowTitle(f"PDF Proxy Printer - {name}")

    def _build_editor_page(self, state, img_dict):
        card_grid = CardGrid(state, img_dict)
        scroll_area = CardScrollArea(state, card_grid)
        print_preview = PrintPreview(state, img_dict)
        tabs = CardTabs(state, img_dict, scroll_area, print_preview)
        options = OptionsWidget(self._application, state, img_dict)
        options_scroll_area = QScrollArea()
        options_scroll_area.setWidgetResizable(True)
        options_scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        options_scroll_area.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        options_scroll_area.setWidget(options)
        return EditorPage(tabs, scroll_area, options_scroll_area, options, print_preview)

    def _load_editor_state(self, loader_title, load_fn):
        error = None
        result = None

        def work():
            nonlocal error, result
            try:
                result = load_fn()
            except RECOVERABLE_EDITOR_LOAD_ERRORS as exc:
                logger.warning(
                    "editor state load failed operation=load_editor_state title=%s project_path=%s error=%s",
                    loader_title,
                    self.current_project_path(),
                    exc,
                )
                error = exc

        loading_window = popup(self, loader_title, self._application._debug_mode)
        loading_window.show_during_work(work)
        del loading_window
        if error is not None:
            raise error
        return result

    def show_home(self):
        if not self._leave_active_session():
            return
        self._dashboard_page.refresh_projects()
        self._stack.setCurrentWidget(self._dashboard_page)

    def show_project_explorer(self):
        self.show_home()

    def _confirm_discard_draft(self):
        if not project_library.draft_has_user_content():
            project_library.reset_draft_workspace()
            return True

        confirm = QMessageBox.question(
            self,
            "Discard Draft?",
            (
                "This draft still has unsaved images in tmp_images.\n\n"
                "If you continue, the current draft will be discarded and those temporary images will be removed."
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return False

        project_library.reset_draft_workspace()
        return True

    def _leave_active_session(self):
        if self._active_session is None:
            return True

        if self._active_session.get("managed"):
            self.save_active_project(self._active_session["state"])
        elif self._active_session.get("is_draft"):
            if not self._confirm_discard_draft():
                return False

        self._clear_active_session()
        return True

    def _prepare_new_draft_workspace(self):
        if project_library.draft_has_user_content():
            confirm = QMessageBox.question(
                self,
                "Start New Project?",
                (
                    "tmp_images already contains an unsaved draft.\n\n"
                    "Start a fresh draft and remove those temporary images first?"
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return None
            return project_library.reset_draft_workspace()
        return project_library.create_draft_project_dict()

    def _autosave_managed_session(self):
        if self._active_session is None or not self._active_session.get("managed"):
            return
        self.save_active_project(self._active_session["state"])

    def autosave_managed_session(self):
        self._autosave_managed_session()

    def open_blank_editor(self):
        if not self._leave_active_session():
            return

        draft_defaults = self._prepare_new_draft_workspace()
        if draft_defaults is None:
            return

        def build_blank():
            state = ProjectState.from_dict(draft_defaults)
            img_dict = {}
            project_service.init_dict(state, img_dict, self._application.warn_nonfatal)
            image_dir = state.image_dir
            crop_dir = os.path.join(image_dir, "crop")
            if image.need_run_cropper(
                image_dir, crop_dir, float(state.bleed_edge), CFG.VibranceBump
            ) or image.need_cache_previews(crop_dir, img_dict, image_dir):
                project_service.init_images(
                    state,
                    img_dict,
                    make_popup_print_fn(blank_window),
                )
            return state, img_dict

        blank_window = popup(self, "Preparing editor...", self._application._debug_mode)
        state = ProjectState.from_dict(draft_defaults)
        img_dict = {}

        def blank_work():
            nonlocal state, img_dict
            state, img_dict = build_blank()

        blank_window.show_during_work(blank_work)
        del blank_window

        editor_page = self._build_editor_page(state, img_dict)
        self._set_active_editor(
            editor_page,
            {
                "project_id": None,
                "project_path": None,
                "display_name": "Unsaved Draft",
                "managed": False,
                "is_draft": True,
                "thumbnail_card": None,
                "state": state,
                "img_dict": img_dict,
            },
        )

    def open_managed_project(self, project_id):
        if not self._leave_active_session():
            return

        project_entry = project_library.get_project(project_id)
        if project_entry is None:
            self._application.warn_nonfatal(
                "Project Missing",
                "That project could not be found in the project library.",
            )
            self._dashboard_page.refresh_projects()
            return

        state = ProjectState()
        img_dict = {}

        def load_work():
            loaded = load_project_file(
                self._application,
                state,
                img_dict,
                project_entry["path"],
                make_popup_print_fn(reload_window),
            )
            if not loaded:
                raise ValueError("The selected project could not be loaded.")

        reload_window = popup(self, "Loading project...", self._application._debug_mode)
        reload_window.show_during_work(load_work)
        del reload_window

        project_library.touch_opened(project_id)
        editor_page = self._build_editor_page(state, img_dict)
        self._set_active_editor(
            editor_page,
            {
                "project_id": project_id,
                "project_path": project_entry["path"],
                "display_name": project_entry["display_name"],
                "managed": True,
                "is_draft": False,
                "thumbnail_card": project_entry.get("thumbnail_card"),
                "state": state,
                "img_dict": img_dict,
            },
        )

    def import_and_open_project(self, source_path):
        if not self._leave_active_session():
            return
        project_entry = project_library.import_project(source_path)
        self.open_managed_project(project_entry["id"])

    def save_active_project(self, state):
        session = self._active_session
        if session is None:
            return None
        if session.get("managed") and session.get("project_id") is not None:
            saved = project_library.save_project(session["project_id"], state)
            if saved is not None:
                session["project_path"] = saved["path"]
                session["display_name"] = saved["display_name"]
                session["thumbnail_card"] = saved.get("thumbnail_card")
                self._current_project_path = saved["path"]
                self._dashboard_page.refresh_projects()
                self._update_window_title()
            return saved

        name, accepted = QInputDialog.getText(
            self,
            "Save Project",
            "Choose a name for this project.\n\nThis is the name that will appear in the project list:",
        )
        if not accepted:
            return None

        display_name = name.strip()
        if display_name == "":
            QMessageBox.warning(
                self,
                "Project Name Required",
                "Please enter a project name so it can be saved and shown in the project list.",
            )
            return None

        created = project_library.materialize_draft_project(
            display_name,
            state,
            thumbnail_card=session.get("thumbnail_card"),
        )
        session["managed"] = True
        session["is_draft"] = False
        session["project_id"] = created["id"]
        session["project_path"] = created["path"]
        session["display_name"] = created["display_name"]
        session["thumbnail_card"] = created.get("thumbnail_card")
        self._current_project_path = created["path"]
        self._dashboard_page.refresh_projects()
        self._update_window_title()
        return created

    def set_project_thumbnail(self, card_name):
        session = self._active_session
        if session is None or not card_name or card_name.startswith("__"):
            return

        session["thumbnail_card"] = card_name
        if session.get("managed") and session.get("project_id") is not None:
            project_library.set_thumbnail_card(session["project_id"], card_name)
            self._dashboard_page.refresh_projects()

        QMessageBox.information(
            self,
            "Project Cover Updated",
            f"'{card_name}' is now the cover image for this project in the project list.",
        )

    def clear_project_thumbnail_if_matches(self, card_name):
        session = self._active_session
        if session is None or session.get("thumbnail_card") != card_name:
            return

        session["thumbnail_card"] = None
        if session.get("managed") and session.get("project_id") is not None:
            project_library.clear_thumbnail_card(session["project_id"])
            self._dashboard_page.refresh_projects()

    def refresh_widgets(self, state):
        if self._editor_page is not None:
            self._editor_page.refresh_widgets(state)

    def refresh(self, state, img_dict):
        if self._editor_page is not None:
            self._editor_page.refresh(state, img_dict)

    def refresh_preview(self, state, img_dict):
        if self._editor_page is not None:
            self._editor_page.refresh_preview(state, img_dict)


def window_setup(application):
    window = AppShellWindow(application)
    application.set_window(window)
    window.show()
    return window


def projects_root():
    return project_library.projects_root()


def event_loop(application):
    application.exec()
