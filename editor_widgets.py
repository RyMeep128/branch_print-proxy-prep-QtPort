import os
import re
import math
import json
import datetime
import functools
import subprocess

import PyQt6.QtCore as QtCore
from PyQt6.QtGui import QPixmap, QIntValidator, QPainter, QPainterPath, QCursor, QTransform
from PyQt6.QtWidgets import (
    QApplication,
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
    QCheckBox,
    QTabWidget,
    QSplitter,
    QMessageBox,
    QListWidget,
    QListWidgetItem,
    QFileDialog,
    QToolTip,
    QDialog,
    QDoubleSpinBox,
    QFrame,
)

import pdf
import image
import project_library
import fallback_image as fallback
from config import CFG
from constants import (
    card_ratio,
    card_size_without_bleed_inch,
    low_dpi_warning_threshold,
    page_sizes,
)
from models import ProjectState, as_project_state
from util import inch_to_mm, mm_to_inch, open_folder, point_to_inch
from background_tasks import make_popup_print_fn, popup
from dialogs import (
    ComboBoxWithLabel,
    DeckImportDialog,
    FileDialogType,
    HighResPickerDialog,
    LineEditWithLabel,
    SettingsDialog,
    WidgetWithLabel,
    delete_project_with_confirmation,
    folder_dialog,
    image_file_dialog,
    project_file_dialog,
)
from services import deck_import_service, pdf_service, project_service


def project_thumbnail_pixmap(image_path, width=120, height=160):
    pixmap = QPixmap()
    if image_path and os.path.exists(image_path):
        pixmap.load(image_path)
    if pixmap.isNull():
        pixmap.loadFromData(fallback.data)
    return pixmap.scaled(
        width,
        height,
        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
        QtCore.Qt.TransformationMode.SmoothTransformation,
    )


class EditorPage(QWidget):
    def __init__(self, tabs, scroll_area, options_container, options, print_preview):
        super().__init__()

        splitter = QSplitter(QtCore.Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(tabs)
        splitter.addWidget(options_container)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        sidebar_width = max(
            options.sizeHint().width(),
            options.minimumSizeHint().width(),
            320,
        )
        options_container.setMinimumWidth(min(sidebar_width, 600))
        splitter.setSizes([max(sidebar_width * 2, 900), sidebar_width])

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)
        self.setLayout(layout)

        self._scroll_area = scroll_area
        self._options = options
        self._print_preview = print_preview

    def refresh_widgets(self, state):
        self._options.refresh_widgets(state)

    def refresh(self, state, img_dict):
        self._scroll_area.refresh(state, img_dict)
        self._options.refresh(state, img_dict)
        self.refresh_preview(state, img_dict)

    def refresh_preview(self, state, img_dict):
        self._print_preview.refresh(state, img_dict)


class WorkflowGuideWidget(QGroupBox):
    def __init__(self):
        super().__init__()

        self.setTitle("Start Here")

        intro = QLabel(
            "For most projects, follow these steps from top to bottom."
        )
        intro.setWordWrap(True)

        steps = QLabel(
            "1. Import cards or choose your image folder.\n"
            "2. Prepare images after adding or changing card files.\n"
            "3. Check the Preview tab to confirm the pages look right.\n"
            "4. Save the project so you can come back later.\n"
            "5. Save PDF when you are ready to export."
        )
        steps.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(intro)
        layout.addWidget(steps)
        self.setLayout(layout)


class CardImage(QLabel):
    clicked = QtCore.pyqtSignal()

    def __init__(self, img_data, img_size, round_corners=True, rotation=False):
        super().__init__()

        raw_pixmap = QPixmap()
        raw_pixmap.loadFromData(img_data, "PNG")
        pixmap = raw_pixmap

        card_size_minimum_width_pixels = 130

        if round_corners:
            card_corner_radius_inch = 1 / 8
            card_corner_radius_pixels = (
                card_corner_radius_inch * img_size[0] / card_size_without_bleed_inch[0]
            )

            clipped_pixmap = QPixmap(int(img_size[0]), int(img_size[1]))
            clipped_pixmap.fill(QtCore.Qt.GlobalColor.transparent)

            path = QPainterPath()
            path.addRoundedRect(
                QtCore.QRectF(pixmap.rect()),
                card_corner_radius_pixels,
                card_corner_radius_pixels,
            )

            painter = QPainter(clipped_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

            painter.setClipPath(path)
            painter.drawPixmap(0, 0, pixmap)
            del painter

            pixmap = clipped_pixmap

        if rotation is not None:
            match rotation:
                case image.Rotation.RotateClockwise_90:
                    rotation = 90
                case image.Rotation.RotateCounterClockwise_90:
                    rotation = -90
                case image.Rotation.Rotate_180:
                    rotation = 180
            transform = QTransform()
            transform.rotate(rotation)
            pixmap = pixmap.transformed(transform)

        self.setPixmap(pixmap)

        self.setSizePolicy(
            QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding
        )
        self.setScaledContents(True)
        self.setMinimumWidth(card_size_minimum_width_pixels)

        self._rotated = rotation in [-90, 90]

    def heightForWidth(self, width):
        if self._rotated:
            return int(width * card_ratio)
        else:
            return int(width / card_ratio)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.clicked.emit()


class BacksideImage(CardImage):
    def __init__(self, backside_name, img_dict):
        if backside_name in img_dict:
            backside_data = eval(img_dict[backside_name]["data"])
            backside_size = img_dict[backside_name]["size"]
        else:
            backside_data = fallback.data
            backside_size = fallback.size

        super().__init__(backside_data, backside_size)


class StackedCardBacksideView(QStackedWidget):
    _backside_reset = QtCore.pyqtSignal()
    _backside_clicked = QtCore.pyqtSignal()

    def __init__(self, img: QWidget, backside: QWidget):
        super().__init__()

        style = QCommonStyle()

        reset_button = QPushButton()
        reset_button.setIcon(
            style.standardIcon(QStyle.StandardPixmap.SP_DialogResetButton)
        )
        reset_button.setToolTip("Use the default card back")
        reset_button.setFixedWidth(20)
        reset_button.setFixedHeight(20)
        reset_button.clicked.connect(self._backside_reset)

        backside.setToolTip("Choose a custom back for this card")

        backside_layout = QHBoxLayout()
        backside_layout.addStretch()
        backside_layout.addWidget(
            reset_button, alignment=QtCore.Qt.AlignmentFlag.AlignBottom
        )
        backside_layout.addWidget(
            backside, alignment=QtCore.Qt.AlignmentFlag.AlignBottom
        )
        backside_layout.setContentsMargins(0, 0, 0, 0)

        backside_container = QWidget(self)
        backside_container.setLayout(backside_layout)

        img.setMouseTracking(True)
        backside.setMouseTracking(True)
        backside_container.setMouseTracking(True)
        self.setMouseTracking(True)

        self.addWidget(img)
        self.addWidget(backside_container)
        self.layout().setStackingMode(QStackedLayout.StackingMode.StackAll)
        self.layout().setAlignment(
            backside,
            QtCore.Qt.AlignmentFlag.AlignBottom | QtCore.Qt.AlignmentFlag.AlignRight,
        )

        self._img = img
        self._backside = backside
        self._backside_container = backside_container

    def refresh_backside(self, new_backside):
        new_backside.setMouseTracking(True)

        layout = self._backside_container.layout()
        self._backside.setParent(None)
        layout.addWidget(new_backside)
        layout.addWidget(new_backside, alignment=QtCore.Qt.AlignmentFlag.AlignBottom)
        self._backside = new_backside

        self.refresh_sizes(self.rect().size())

    def refresh_sizes(self, size):
        width = size.width()
        height = size.height()

        img_width = int(width * 0.9)
        img_height = int(height * 0.9)

        backside_width = int(width * 0.45)
        backside_height = int(height * 0.45)

        self._img.setFixedWidth(img_width)
        self._img.setFixedHeight(img_height)
        self._backside.setFixedWidth(backside_width)
        self._backside.setFixedHeight(backside_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh_sizes(event.size())

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)

        x = event.pos().x()
        y = event.pos().y()

        neg_backside_width = self.rect().width() - self._backside.rect().size().width()
        neg_backside_height = (
            self.rect().height() - self._backside.rect().size().height()
        )

        if x >= neg_backside_width and y >= neg_backside_height:
            self.setCurrentWidget(self._backside_container)
        else:
            self.setCurrentWidget(self._img)

    def leaveEvent(self, event):
        super().leaveEvent(event)

        self.setCurrentWidget(self._img)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)

        if self.currentWidget() == self._backside_container:
            self._backside_clicked.emit()


class CardWidget(QWidget):
    def __init__(self, print_dict, img_dict, card_name):
        super().__init__()
        self.setMouseTracking(True)
        state = as_project_state(print_dict)

        if card_name in img_dict:
            img_data = eval(img_dict[card_name]["data"])
            img_size = img_dict[card_name]["size"]
        else:
            img_data = fallback.data
            img_size = fallback.size
        img = CardImage(img_data, img_size)
        img.setToolTip("Click to choose a higher-resolution front image")

        def open_high_res_picker():
            dialog = HighResPickerDialog(self, state, img_dict, card_name)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.was_applied():
                self.window().refresh(state, img_dict)

        if card_name is not None:
            img.clicked.connect(open_high_res_picker)

        backside_enabled = state.backside_enabled
        oversized_enabled = state.oversized_enabled

        backside_img = None
        if backside_enabled:
            backside_name = (
                state.backsides[card_name]
                if card_name in state.backsides
                else state.backside_default
            )
            backside_img = BacksideImage(backside_name, img_dict)

        initial_number = state.cards[card_name] if card_name is not None else 1

        number_edit = QLineEdit()
        number_edit.setValidator(QIntValidator(0, 100, self))
        number_edit.setText(str(initial_number))
        number_edit.setFixedWidth(40)

        decrement_button = QPushButton("Remove 1")
        increment_button = QPushButton("Add 1")

        decrement_button.setToolTip("Remove one copy")
        increment_button.setToolTip("Add one copy")

        number_layout = QHBoxLayout()
        number_layout.addStretch()
        number_layout.addWidget(decrement_button)
        number_layout.addWidget(number_edit)
        number_layout.addWidget(increment_button)
        number_layout.addStretch()
        number_layout.setContentsMargins(0, 0, 0, 0)

        number_area = QWidget()
        number_area.setLayout(number_layout)
        number_area.setFixedHeight(20)

        thumbnail_button = QPushButton("Use as Project Cover")
        thumbnail_button.setToolTip("Use this card on the project list")
        thumbnail_button.setFixedHeight(24)

        def set_project_thumbnail():
            app = QApplication.instance()
            if app is not None and hasattr(app, "set_project_thumbnail"):
                app.set_project_thumbnail(card_name)

        thumbnail_button.clicked.connect(set_project_thumbnail)
        thumbnail_button.setEnabled(card_name is not None)

        delete_button = None
        if card_name is not None:
            delete_button = QPushButton("X", self)
            delete_button.setFixedSize(24, 24)
            delete_button.setToolTip("Remove this card from the project")
            delete_button.setStyleSheet(
                "QPushButton {"
                "background-color: #8d2d2d; color: white; font-weight: bold;"
                "border: 1px solid #b85555; border-radius: 12px;"
                "}"
                "QPushButton:hover { background-color: #a83a3a; }"
            )
            delete_button.hide()

            def delete_card():
                confirm = QMessageBox.question(
                    self,
                    "Remove Card",
                    (
                        f"Remove '{card_name}' from this project?\n\n"
                        "This will remove it from the project and delete that card image from disk."
                    ),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if confirm != QMessageBox.StandardButton.Yes:
                    return

                application = QApplication.instance()
                try:
                    project_service.delete_card_files(state, img_dict, card_name)
                except OSError as exc:
                    if application is not None and hasattr(application, "warn_nonfatal"):
                        application.warn_nonfatal(
                            "Remove Card Failed",
                            f"The card image could not be fully deleted from disk.\n\n{exc}",
                        )
                    else:
                        QMessageBox.warning(
                            self,
                            "Remove Card Failed",
                            f"The card image could not be fully deleted from disk.\n\n{exc}",
                        )
                    return
                window = self.window()
                if window is not None and hasattr(
                    window, "clear_project_thumbnail_if_matches"
                ):
                    window.clear_project_thumbnail_if_matches(card_name)
                self.window().refresh(state, img_dict)

            delete_button.clicked.connect(delete_card)

        effective_dpi = None
        if card_name in img_dict:
            effective_dpi = img_dict[card_name].get("effective_dpi")

        if effective_dpi is not None:
            rounded_dpi = round(effective_dpi)
            dpi_label = QLabel(f"{rounded_dpi} DPI")
            dpi_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            if effective_dpi < low_dpi_warning_threshold:
                dpi_label.setToolTip(
                    f"This image is approximately {rounded_dpi} DPI, below the warning threshold of {low_dpi_warning_threshold} DPI."
                )
                dpi_label.setStyleSheet(
                    "background-color: #7a1f1f; color: white; font-weight: bold; "
                    "border: 1px solid #b85555; border-radius: 4px; padding: 2px 6px;"
                )
            else:
                dpi_label.setToolTip(
                    f"This image is approximately {rounded_dpi} DPI."
                )
                dpi_label.setStyleSheet(
                    "background-color: #1f3c5a; color: white; font-weight: bold; "
                    "border: 1px solid #5b87b5; border-radius: 4px; padding: 2px 6px;"
                )
            dpi_label.setFixedHeight(22)
            self._dpi_label = dpi_label
        else:
            self._dpi_label = None

        if backside_img is not None:
            card_widget = StackedCardBacksideView(img, backside_img)

            def backside_reset():
                if card_name in state.backsides:
                    del state.backsides[card_name]
                    new_backside_img = BacksideImage(
                        state.backside_default, img_dict
                    )
                    card_widget.refresh_backside(new_backside_img)

            def backside_choose():
                backside_choice = image_file_dialog(self, state.image_dir)
                if backside_choice is not None and (
                    card_name not in state.backsides
                    or backside_choice != state.backsides[card_name]
                ):
                    state.backsides[card_name] = backside_choice
                    new_backside_img = BacksideImage(backside_choice, img_dict)
                    card_widget.refresh_backside(new_backside_img)

            card_widget._backside_reset.connect(backside_reset)
            card_widget._backside_clicked.connect(backside_choose)
        else:
            card_widget = img

        if backside_enabled or oversized_enabled:
            extra_options = []

            if backside_enabled:
                is_short_edge = (
                    state.backside_short_edge[card_name]
                    if card_name in state.backside_short_edge
                    else False
                )
                short_edge_checkbox = QCheckBox("Flip on Short Edge")
                short_edge_checkbox.setChecked(is_short_edge)
                short_edge_checkbox.setToolTip(
                    "Turn this on if the back should flip on the short edge"
                )

                short_edge_checkbox.checkStateChanged.connect(
                    functools.partial(self.toggle_short_edge, state)
                )

                extra_options.append(short_edge_checkbox)

            if oversized_enabled:
                is_oversized = (
                    state.oversized[card_name]
                    if card_name in state.oversized
                    else False
                )
                oversized_checkbox = QCheckBox("Oversized")
                oversized_checkbox.setToolTip(
                    "Turn this on if this card should be printed oversized"
                )
                oversized_checkbox.setChecked(is_oversized)

                oversized_checkbox.checkStateChanged.connect(
                    functools.partial(self.toggle_oversized, state)
                )

                extra_options.append(oversized_checkbox)

            extra_options_layout = QHBoxLayout()
            extra_options_layout.addStretch()
            for opt in extra_options:
                extra_options_layout.addWidget(opt)
            extra_options_layout.addStretch()
            extra_options_layout.setContentsMargins(0, 0, 0, 0)

            extra_options_area = QWidget()
            extra_options_area.setLayout(extra_options_layout)
            extra_options_area.setFixedHeight(20)

            self._extra_options_area = extra_options_area
        else:
            self._extra_options_area = None

        layout = QVBoxLayout()
        layout.addWidget(card_widget)
        if self._dpi_label is not None:
            layout.addWidget(self._dpi_label)
        layout.addWidget(number_area)
        layout.addWidget(thumbnail_button)
        if self._extra_options_area is not None:
            layout.addWidget(extra_options_area)
        self.setLayout(layout)

        palette = self.palette()
        palette.setColor(self.backgroundRole(), 0x111111)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        self._img_widget = img
        self._number_area = number_area
        self._thumbnail_button = thumbnail_button
        self._delete_button = delete_button

        number_edit.editingFinished.connect(
            functools.partial(self.edit_number, state)
        )
        decrement_button.clicked.connect(functools.partial(self.dec_number, state))
        increment_button.clicked.connect(functools.partial(self.inc_number, state))

        margins = self.layout().contentsMargins()
        minimum_img_width = img.minimumWidth()
        minimum_width = minimum_img_width + margins.left() + margins.right()
        self.setMinimumSize(minimum_width, self.heightForWidth(minimum_width))

        self._number_edit = number_edit
        self._card_name = card_name

    def enterEvent(self, event):
        super().enterEvent(event)
        if self._delete_button is not None:
            self._delete_button.show()
            self._delete_button.raise_()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._delete_button is not None:
            self._delete_button.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._delete_button is not None:
            self._delete_button.move(self.width() - self._delete_button.width() - 6, 6)
            self._delete_button.raise_()

    def heightForWidth(self, width):
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()

        img_width = width - margins.left() - margins.right()
        img_height = self._img_widget.heightForWidth(img_width)

        additional_widgets = self._number_area.height() + spacing
        additional_widgets += self._thumbnail_button.height() + spacing

        if self._dpi_label is not None:
            additional_widgets += self._dpi_label.height() + spacing

        if self._extra_options_area:
            additional_widgets += self._extra_options_area.height() + spacing

        return img_height + additional_widgets + margins.top() + margins.bottom()

    def apply_number(self, state, number):
        self._number_edit.setText(str(number))
        state.cards[self._card_name] = number

    def edit_number(self, state):
        number = int(self._number_edit.text())
        number = max(number, 0)
        self.apply_number(state, number)

    def dec_number(self, state):
        number = state.cards[self._card_name] - 1
        number = max(number, 0)
        self.apply_number(state, number)

    def inc_number(self, state):
        number = state.cards[self._card_name] + 1
        number = min(number, 999)
        self.apply_number(state, number)

    def toggle_short_edge(self, state, s):
        short_edge_dict = state.backside_short_edge
        if s == QtCore.Qt.CheckState.Checked:
            short_edge_dict[self._card_name] = True
        elif self._card_name in short_edge_dict:
            del short_edge_dict[self._card_name]

    def toggle_oversized(self, state, s):
        oversized_dict = state.oversized
        if s == QtCore.Qt.CheckState.Checked:
            oversized_dict[self._card_name] = True
        elif self._card_name in oversized_dict:
            del oversized_dict[self._card_name]


class DummyCardWidget(CardWidget):
    def __init__(self, print_dict, img_dict):
        super().__init__(print_dict, img_dict, None)
        self._card_name = "__dummy"

    def apply_number(self, state, number):
        pass

    def edit_number(self, state):
        pass

    def dec_number(self, state):
        pass

    def inc_number(self, state):
        pass

    def toggle_oversized(self, state, s):
        pass


class CardGrid(QWidget):
    def __init__(self, print_dict, img_dict):
        super().__init__()

        self._cards = {}
        state = as_project_state(print_dict)

        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(9, 9, 9, 9)
        self.setLayout(grid_layout)
        self.refresh(state, img_dict)

    def totalWidthFromItemWidth(self, item_width):
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()

        return (
            item_width * self._cols
            + margins.left()
            + margins.right()
            + spacing * (self._cols - 1)
        )

    def heightForWidth(self, width):
        margins = self.layout().contentsMargins()
        spacing = self.layout().spacing()

        item_width = int(
            (width - margins.left() - margins.right() - spacing * (self._cols - 1))
            / self._cols
        )
        item_height = self._first_item.heightForWidth(item_width)
        height = (
            item_height * self._rows
            + margins.top()
            + margins.bottom()
            + spacing * (self._rows - 1)
        )

        return int(height)

    def resizeEvent(self, event):
        width = event.size().width()
        height = self.heightForWidth(width)
        self.setFixedHeight(height)

    def refresh(self, print_dict, img_dict):
        state = as_project_state(print_dict)
        for card in self._cards.values():
            card.setParent(None)
        self._cards = {}

        grid_layout = self.layout()

        i = 0
        cols = CFG.DisplayColumns
        for card_name, _ in state.cards.items():
            if card_name.startswith("__") or card_name not in img_dict:
                continue

            card_widget = CardWidget(state, img_dict, card_name)
            self._cards[card_name] = card_widget

            x = i // cols
            y = i % cols
            grid_layout.addWidget(card_widget, x, y)
            i = i + 1

        for j in range(i, cols):
            card_widget = DummyCardWidget(state, img_dict)
            sp_retain = card_widget.sizePolicy()
            sp_retain.setRetainSizeWhenHidden(True)
            card_widget.setSizePolicy(sp_retain)
            card_widget.hide()

            self._cards[card_widget._card_name] = card_widget
            grid_layout.addWidget(card_widget, 0, j)
            i = i + 1

        self._first_item = list(self._cards.values())[0]
        self._cols = cols
        self._rows = math.ceil(i / cols)
        self._nested_resize = False

        self.setMinimumWidth(
            self.totalWidthFromItemWidth(self._first_item.minimumWidth())
        )
        self.setMinimumHeight(
            self._first_item.heightForWidth(self._first_item.minimumWidth())
        )

    def has_visible_cards(self):
        return any(not card_name.startswith("__") for card_name in self._cards.keys())


class CardScrollArea(QScrollArea):
    def __init__(self, print_dict, card_grid):
        super().__init__()
        state = as_project_state(print_dict)

        global_label = QLabel("All Cards:")
        global_decrement_button = QPushButton("Remove 1")
        global_increment_button = QPushButton("Add 1")
        global_set_zero_button = QPushButton("Reset All")

        global_decrement_button.setToolTip("Remove one copy from every card")
        global_increment_button.setToolTip("Add one copy to every card")
        global_set_zero_button.setToolTip("Set every card count to zero")

        global_number_layout = QHBoxLayout()
        global_number_layout.addWidget(global_label)
        global_number_layout.addWidget(global_decrement_button)
        global_number_layout.addWidget(global_increment_button)
        global_number_layout.addWidget(global_set_zero_button)
        global_number_layout.addStretch()
        global_number_layout.setContentsMargins(6, 0, 6, 0)

        global_number_widget = QWidget()
        global_number_widget.setLayout(global_number_layout)

        empty_state = QLabel(
            "No cards are loaded yet.\n\n"
            "Start by clicking 'Import Cards' or by choosing your image folder in the sidebar.\n"
            "After your card images appear here, click 'Prepare Images' if needed and then check the Preview tab."
        )
        empty_state.setWordWrap(True)
        empty_state.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        empty_state.setFrameShape(QFrame.Shape.StyledPanel)
        empty_state.setStyleSheet("padding: 20px;")

        card_area_layout = QVBoxLayout()
        card_area_layout.addWidget(global_number_widget)
        card_area_layout.addWidget(empty_state)
        card_area_layout.addWidget(card_grid)
        card_area_layout.addStretch()
        card_area_layout.setSpacing(0)

        card_area = QWidget()
        card_area.setLayout(card_area_layout)

        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidget(card_area)

        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

        def dec_number():
            for card in card_grid._cards.values():
                card.dec_number(state)

        def inc_number():
            for card in card_grid._cards.values():
                card.inc_number(state)

        def reset_number():
            for card in card_grid._cards.values():
                card.apply_number(state, 0)

        global_decrement_button.clicked.connect(dec_number)
        global_increment_button.clicked.connect(inc_number)
        global_set_zero_button.clicked.connect(reset_number)

        self._card_grid = card_grid
        self._global_number_widget = global_number_widget
        self._empty_state = empty_state
        self._update_empty_state()

    def computeMinimumWidth(self):
        margins = self.widget().layout().contentsMargins()
        return (
            self._card_grid.minimumWidth()
            + 2 * self.verticalScrollBar().width()
            + margins.left()
            + margins.right()
        )

    def showEvent(self, event):
        super().showEvent(event)
        self.setMinimumWidth(self.computeMinimumWidth())

    def refresh(self, state, img_dict):
        self._card_grid.refresh(state, img_dict)
        self._update_empty_state()
        self.setMinimumWidth(self.computeMinimumWidth())
        self._card_grid.adjustSize()  # forces recomputing size

    def _update_empty_state(self):
        has_cards = self._card_grid.has_visible_cards()
        self._global_number_widget.setVisible(has_cards)
        self._empty_state.setVisible(not has_cards)
        self._card_grid.setVisible(has_cards)


class PageGrid(QWidget):
    def __init__(self, cards, backside, columns, rows, bleed_edge_mm, img_get):
        super().__init__()

        grid = QGridLayout()
        grid.setSpacing(0)
        grid.setContentsMargins(0, 0, 0, 0)

        left_to_right = not backside
        card_grid = pdf.distribute_cards_to_grid(cards, left_to_right, columns, rows)

        has_missing_preview = False

        for x in range(0, rows):
            for y in range(0, columns):
                if card := card_grid[x][y]:
                    (card_name, is_short_edge, is_oversized) = card
                    if card_name is None:
                        continue

                    img_data, img_size = img_get(card_name, bleed_edge_mm)
                    if img_data is None:
                        img_data, img_size = fallback.data, fallback.size
                        has_missing_preview = True

                    rotation = pdf.get_card_rotation(
                        backside, is_oversized, is_short_edge
                    )

                    img = CardImage(
                        img_data,
                        img_size,
                        round_corners=False,
                        rotation=rotation,
                    )

                    if is_oversized:
                        grid.addWidget(img, x, y, 1, 2)
                    else:
                        grid.addWidget(img, x, y)

        # pad with dummy images if we have only one uncompleted row
        for i in range(0, columns):
            x, y = pdf.get_grid_coords(i, columns, backside)
            if grid.itemAtPosition(x, y) is None:
                img_data = fallback.data
                img_size = fallback.size

                img = CardImage(img_data, img_size)
                sp_retain = img.sizePolicy()
                sp_retain.setRetainSizeWhenHidden(True)
                img.setSizePolicy(sp_retain)
                img.hide()

                grid.addWidget(img, x, y)

        for i in range(0, grid.columnCount()):
            grid.setColumnStretch(i, 1)
        for i in range(0, grid.rowCount()):
            grid.setRowStretch(i, 1)

        self.setLayout(grid)

        self._rows = grid.rowCount()
        self._cols = grid.columnCount()
        self._has_missing_preview = has_missing_preview

    def hasMissingPreviews(self):
        return self._has_missing_preview

    def heightForWidth(self, width):
        return int(width / card_ratio * (self._rows / self._cols))

    def resizeEvent(self, event):
        super().resizeEvent(event)

        width = event.size().width()
        height = self.heightForWidth(width)
        self.setFixedHeight(height)


class PagePreview(QWidget):
    def __init__(
        self,
        cards,
        backside,
        columns,
        rows,
        bleed_edge_mm,
        backside_offset_mm,
        page_size,
        img_get,
    ):
        super().__init__()

        grid = PageGrid(cards, backside, columns, rows, bleed_edge_mm, img_get)

        layout = QVBoxLayout()
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(grid)
        layout.setAlignment(grid, QtCore.Qt.AlignmentFlag.AlignTop)

        self.setLayout(layout)

        palette = self.palette()
        palette.setColor(self.backgroundRole(), 0xFFFFFF)
        self.setPalette(palette)
        self.setAutoFillBackground(True)

        (page_width, page_height) = page_size
        self._page_ratio = page_width / page_height
        self._page_width = page_width
        self._page_height = page_height

        bleed_edge = mm_to_inch(bleed_edge_mm)
        (card_width, card_height) = (
            v + 2 * bleed_edge for v in card_size_without_bleed_inch
        )
        self._card_width = card_width
        self._card_height = card_height

        self._padding_width = (page_width - columns * card_width) / 2
        self._padding_height = (page_height - rows * card_height) / 2
        self._backside_offset = mm_to_inch(backside_offset_mm) if backside else 0

        self._grid = grid

    def hasMissingPreviews(self):
        return self._grid.hasMissingPreviews()

    def heightForWidth(self, width):
        return int(width / self._page_ratio)

    def resizeEvent(self, event):
        super().resizeEvent(event)

        width = event.size().width()
        height = self.heightForWidth(width)
        self.setFixedHeight(height)

        padding_width_pixels = int(self._padding_width * width / self._page_width)
        padding_height_pixels = int(self._padding_height * height / self._page_height)
        backside_offset_pixels = int(self._backside_offset * width / self._page_width)
        self.setContentsMargins(
            max(0, padding_width_pixels + backside_offset_pixels),
            padding_height_pixels,
            max(0, padding_width_pixels - backside_offset_pixels),
            padding_height_pixels,
        )


class PrintPreview(QScrollArea):
    def __init__(self, print_dict, img_dict):
        super().__init__()

        self.refresh(as_project_state(print_dict), img_dict)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

    def refresh(self, print_dict, img_dict):
        state = as_project_state(print_dict)
        bleed_edge = float(state.bleed_edge)
        bleed_edge_inch = mm_to_inch(bleed_edge)

        page_size = page_sizes[state.pagesize]
        if state.orient == "Landscape":
            page_size = tuple(page_size[::-1])
        page_size = tuple(point_to_inch(p) for p in page_size)
        (page_width, page_height) = page_size

        (card_width, card_height) = card_size_without_bleed_inch
        card_width = card_width + 2 * bleed_edge_inch
        card_height = card_height + 2 * bleed_edge_inch

        columns = int(page_width // card_width)
        rows = int(page_height // card_height)

        raw_pages = pdf.distribute_cards_to_pages(state, columns, rows)
        pages = [
            {
                "cards": page,
                "backside": False,
            }
            for page in raw_pages
        ]

        if state.backside_enabled:
            backside_pages = pdf.make_backside_pages(state, raw_pages)
            backside_pages = [
                {
                    "cards": page,
                    "backside": True,
                }
                for page in backside_pages
            ]

            pages = [
                page for page_pair in zip(pages, backside_pages) for page in page_pair
            ]

        @functools.cache
        def img_get(card_name, bleed_edge):
            if card_name in img_dict:
                card_img = img_dict[card_name]
                if bleed_edge > 0 and "uncropped" in card_img:
                    uncropped_data = eval(card_img["uncropped"]["data"])
                    img = image.image_from_bytes(uncropped_data)
                    img_crop = image.crop_image(img, "", bleed_edge, None)
                    img_data, img_size = image.to_bytes(img_crop)
                else:
                    img_data = eval(card_img["data"])
                    img_size = card_img["size"]
                return img_data, img_size
            else:
                return None, None

        img_get.cache_clear()

        pages = [
            PagePreview(
                page["cards"],
                page["backside"],
                columns,
                rows,
                bleed_edge,
                float(state.backside_offset),
                page_size,
                img_get,
            )
            for page in pages
        ]

        has_missing_previews = any([p.hasMissingPreviews() for p in pages])
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(
            QLabel("Only a preview; Quality is lower than final render")
        )
        if has_missing_previews:
            bleed_info = QLabel(
                "Bleed edge is incorrect; Run cropper for more accurate preview"
            )
            bleed_info.setStyleSheet("QLabel { color : red; }")
            header_layout.addWidget(bleed_info)
        if CFG.VibranceBump:
            vibrance_info = QLabel("Preview does not show the 'Boost Color Vibrance' setting")
            vibrance_info.setStyleSheet("QLabel { color : red; }")
            header_layout.addWidget(vibrance_info)

        header = QWidget()
        header.setLayout(header_layout)

        layout = QVBoxLayout()
        layout.addWidget(header)
        for page in pages:
            layout.addWidget(page)
        layout.setSpacing(15)
        layout.setContentsMargins(60, 20, 60, 20)
        pages_widget = QWidget()
        pages_widget.setLayout(layout)

        self.setWidget(pages_widget)


class ActionsWidget(QGroupBox):
    def __init__(
        self,
        application,
        print_dict,
        img_dict,
    ):
        super().__init__()
        state = as_project_state(print_dict)

        self.setTitle("Main Actions")

        cropper_button = QPushButton("Prepare Images")
        render_button = QPushButton("Save PDF")
        home_button = QPushButton("Back to Projects")
        save_button = QPushButton("Save Project")
        load_button = QPushButton("Load Project")
        set_images_button = QPushButton("Choose Image Folder")
        open_images_button = QPushButton("Open Images")
        settings_button = QPushButton("Settings")
        import_decklist_button = QPushButton("Import Cards")
        clear_cards_button = QPushButton("Remove Old Card Images")

        for button in [
            import_decklist_button,
            cropper_button,
            render_button,
            save_button,
            load_button,
            set_images_button,
            open_images_button,
            settings_button,
            clear_cards_button,
            home_button,
        ]:
            button.setMinimumHeight(30)

        primary_button_style = (
            "QPushButton {"
            "background-color: #1f6f4a; color: white; font-weight: bold;"
            "border: 1px solid #17563a; border-radius: 4px; padding: 6px 10px;"
            "}"
            "QPushButton:hover { background-color: #258457; }"
        )
        danger_button_style = (
            "QPushButton {"
            "background-color: #5f2626; color: white;"
            "border: 1px solid #7e3636; border-radius: 4px; padding: 6px 10px;"
            "}"
            "QPushButton:hover { background-color: #743131; }"
        )
        subtle_heading_style = "font-size: 13px; font-weight: bold;"
        subtle_description_style = "color: #666666;"

        import_decklist_button.setStyleSheet(primary_button_style)
        cropper_button.setStyleSheet(primary_button_style)
        render_button.setStyleSheet(primary_button_style)
        clear_cards_button.setStyleSheet(danger_button_style)

        buttons = [
            cropper_button,
            render_button,
            home_button,
            save_button,
            load_button,
            set_images_button,
            open_images_button,
            settings_button,
            import_decklist_button,
            clear_cards_button,
        ]
        minimum_width = max(map(lambda x: x.sizeHint().width(), buttons))

        def section_title(text, description):
            title = QLabel(text)
            title.setStyleSheet(subtle_heading_style)
            body = QLabel(description)
            body.setWordWrap(True)
            body.setStyleSheet(subtle_description_style)

            wrapper = QWidget()
            wrapper_layout = QVBoxLayout()
            wrapper_layout.setContentsMargins(0, 0, 0, 0)
            wrapper_layout.setSpacing(2)
            wrapper_layout.addWidget(title)
            wrapper_layout.addWidget(body)
            wrapper.setLayout(wrapper_layout)
            return wrapper

        project_section = section_title(
            "1. Project",
            "Start a project, save your work, or return to the project list.",
        )
        cards_section = section_title(
            "2. Add And Prepare Cards",
            "Bring cards into the project, choose image files, and prepare them for printing.",
        )
        export_section = section_title(
            "3. Export",
            "Check the preview, then save the final PDF.",
        )
        more_section = section_title(
            "More Tools",
            "Less common actions for opening folders, changing app settings, or cleaning up old images.",
        )

        layout = QVBoxLayout()
        layout.setSpacing(12)

        project_grid = QGridLayout()
        project_grid.setColumnMinimumWidth(0, minimum_width + 10)
        project_grid.setColumnMinimumWidth(1, minimum_width + 10)
        project_grid.addWidget(home_button, 0, 0, 1, 2)
        project_grid.addWidget(save_button, 1, 0)
        project_grid.addWidget(load_button, 1, 1)

        cards_grid = QGridLayout()
        cards_grid.setColumnMinimumWidth(0, minimum_width + 10)
        cards_grid.setColumnMinimumWidth(1, minimum_width + 10)
        cards_grid.addWidget(import_decklist_button, 0, 0, 1, 2)
        cards_grid.addWidget(set_images_button, 1, 0, 1, 2)
        cards_grid.addWidget(cropper_button, 2, 0, 1, 2)

        export_grid = QGridLayout()
        export_grid.setColumnMinimumWidth(0, minimum_width + 10)
        export_grid.setColumnMinimumWidth(1, minimum_width + 10)
        export_grid.addWidget(render_button, 0, 0, 1, 2)

        more_grid = QGridLayout()
        more_grid.setColumnMinimumWidth(0, minimum_width + 10)
        more_grid.setColumnMinimumWidth(1, minimum_width + 10)
        more_grid.addWidget(open_images_button, 0, 0, 1, 2)
        more_grid.addWidget(settings_button, 1, 0, 1, 2)
        more_grid.addWidget(clear_cards_button, 2, 0, 1, 2)

        layout.addWidget(project_section)
        layout.addLayout(project_grid)
        layout.addWidget(cards_section)
        layout.addLayout(cards_grid)
        layout.addWidget(export_section)
        layout.addLayout(export_grid)
        layout.addWidget(more_section)
        layout.addLayout(more_grid)

        self.setLayout(layout)

        def render():
            bleed_edge = float(state.bleed_edge)
            image_dir = state.image_dir
            crop_dir = os.path.join(image_dir, "crop")
            if image.need_run_cropper(
                image_dir, crop_dir, bleed_edge, CFG.VibranceBump
            ):
                QToolTip.showText(
                    QCursor.pos(),
                    "Prepare images first, then try saving the PDF again.",
                )
                return

            rgx = re.compile(r"\W")
            default_pdf_name = (
                f"{re.sub(rgx, '', state.filename)}.pdf"
                if len(state.filename) > 0
                else "_printme.pdf"
            )
            pdf_path = QFileDialog.getSaveFileName(
                self,
                "Save PDF",
                os.path.join(cwd, default_pdf_name),
                "PDF Files (*.pdf)",
            )[0]
            if pdf_path == "":
                return

            if not pdf_path.lower().endswith(".pdf"):
                pdf_path = pdf_path + ".pdf"

            state.filename = os.path.splitext(os.path.basename(pdf_path))[0]

            def render_work():
                result = pdf_service.generate_pdf(
                    state,
                    crop_dir,
                    page_sizes[state.pagesize],
                    pdf_path,
                    make_popup_print_fn(render_window),
                )
                make_popup_print_fn(render_window)("Saving PDF...")
                result.pages.save()
                try:
                    subprocess.Popen([pdf_path], shell=True)
                except OSError as e:
                    application.warn_nonfatal(
                        "PDF Open Failed",
                        f"The PDF was saved, but the app could not open it automatically.\n\n{e}",
                    )

            self.window().setEnabled(False)
            render_window = popup(self.window(), "Saving PDF...", application._debug_mode)
            render_window.show_during_work(render_work)
            del render_window
            self.window().setEnabled(True)
            QMessageBox.information(
                self,
                "PDF Saved",
                f"Your PDF was saved here:\n\n{pdf_path}\n\nThe app will try to open it for you automatically.",
            )

        def run_cropper():
            bleed_edge = float(state.bleed_edge)
            image_dir = state.image_dir
            crop_dir = os.path.join(image_dir, "crop")
            img_cache = state.img_cache
            if image.need_run_cropper(
                image_dir, crop_dir, bleed_edge, CFG.VibranceBump
            ):

                self._rebuild_after_cropper = False

                def cropper_work():
                    image.cropper(
                        image_dir,
                        crop_dir,
                        img_cache,
                        img_dict,
                        bleed_edge,
                        CFG.MaxDPI,
                        CFG.VibranceBump,
                        CFG.EnableUncrop,
                        make_popup_print_fn(crop_window),
                    )

                    for img in image.list_image_files(crop_dir):
                        if img not in state.cards:
                            state.cards[img] = 1
                            self._rebuild_after_cropper = True

                    deleted_images = []
                    for img in state.cards.keys():
                        if img not in img_dict.keys():
                            deleted_images.append(img)
                            self._rebuild_after_cropper = True
                    for img in deleted_images:
                        del state.cards[img]

                self.window().setEnabled(False)
                crop_window = popup(self.window(), "Cropping images...", application._debug_mode)
                crop_window.show_during_work(cropper_work)
                del crop_window
                if self._rebuild_after_cropper:
                    self.window().refresh(state, img_dict)
                else:
                    self.window().refresh_preview(state, img_dict)
                self.window().setEnabled(True)
            else:
                QToolTip.showText(
                    QCursor.pos(),
                    "Images are already prepared. You can check Preview or save the PDF.",
                )

        def save_project():
            saved = application.save_active_project(state)
            if saved is None:
                return

            QMessageBox.information(
                self,
                "Project Saved",
                f"Your project was saved as '{saved['display_name']}'.\n\nLocation:\n{saved['path']}",
            )

        def load_project():
            new_project_json = project_file_dialog(
                self, FileDialogType.Open, application.json_path()
            )
            if new_project_json is not None and os.path.exists(new_project_json):
                application.import_and_open_project(new_project_json)

        def set_images_folder():
            new_image_dir = folder_dialog(self)
            if new_image_dir is not None:
                state.image_dir = new_image_dir
                state.img_cache = os.path.join(new_image_dir, "img.cache")

                project_service.init_dict(state, img_dict, application.warn_nonfatal)

                bleed_edge = float(state.bleed_edge)
                image_dir = new_image_dir
                crop_dir = os.path.join(image_dir, "crop")
                if image.need_run_cropper(
                    image_dir, crop_dir, bleed_edge, CFG.VibranceBump
                ) or image.need_cache_previews(crop_dir, img_dict, image_dir):

                    def reload_work():
                        project_service.init_images(
                            state, img_dict, make_popup_print_fn(reload_window)
                        )

                    self.window().setEnabled(False)
                    reload_window = popup(self.window(), "Reloading project...", application._debug_mode)
                    reload_window.show_during_work(reload_work)
                    del reload_window
                    self.window().refresh(state, img_dict)
                    self.window().setEnabled(True)
                else:
                    self.window().refresh(state, img_dict)

        def open_images_folder():
            open_folder(state.image_dir)

        def open_settings():
            prior_values = {
                "DisplayColumns": CFG.DisplayColumns,
                "EnableUncrop": CFG.EnableUncrop,
                "VibranceBump": CFG.VibranceBump,
                "MaxDPI": CFG.MaxDPI,
                "DefaultPageSize": CFG.DefaultPageSize,
                "HighResBackendURL": CFG.HighResBackendURL,
                "HighResCacheTTLSeconds": CFG.HighResCacheTTLSeconds,
                "HighResSearchCacheMemoryMB": CFG.HighResSearchCacheMemoryMB,
                "HighResImageCacheMemoryMB": CFG.HighResImageCacheMemoryMB,
            }
            dialog = SettingsDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            dialog.apply()
            if prior_values["DisplayColumns"] != CFG.DisplayColumns:
                self.window().refresh(state, img_dict)
            elif (
                prior_values["VibranceBump"] != CFG.VibranceBump
                or prior_values["DefaultPageSize"] != CFG.DefaultPageSize
            ):
                self.window().refresh_preview(state, img_dict)

        def import_decklist_images():
            dialog = DeckImportDialog(self, state.image_dir)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            deck_text = dialog.deck_text()
            archidekt_url = dialog.archidekt_url()
            import_result = None
            import_error = None

            def import_work():
                nonlocal import_result, import_error
                try:
                    workflow_result = deck_import_service.import_into_project(
                        state,
                        img_dict,
                        state.image_dir,
                        make_popup_print_fn(import_window),
                        deck_text=deck_text,
                        archidekt_url=archidekt_url,
                        warn_fn=application.warn_nonfatal,
                    )
                    import_result = workflow_result.import_result
                except (OSError, ValueError) as exc:
                    import_error = exc
                    return

            self.window().setEnabled(False)
            import_window = popup(
                self.window(), "Importing cards...", application._debug_mode
            )
            import_window.show_during_work(import_work)
            del import_window
            self.window().setEnabled(True)

            if import_error is not None:
                application.warn_nonfatal(
                    "Card Import Failed",
                    str(import_error),
                )
                return

            if import_result is None:
                return

            if import_result.imported:
                self.window().refresh(state, img_dict)

            summary_lines = [
                f"Imported {len(import_result.imported)} unique cards "
                f"({import_result.imported_count} total copies)."
            ]
            if import_result.failed_cards:
                summary_lines.append(
                    "Failed to import: " + ", ".join(import_result.failed_cards[:8])
                )
            if import_result.unmatched_lines:
                summary_lines.append(
                    "Unmatched lines: " + ", ".join(import_result.unmatched_lines[:8])
                )

            message = "\n\n".join(summary_lines)
            if import_result.imported:
                QMessageBox.information(
                    self,
                    "Card Import Complete",
                    message
                    + "\n\nNext step: click 'Prepare Images' if needed, then check the Preview tab.",
                )
            else:
                application.warn_nonfatal("Card Import Failed", message)

        def clear_old_cards():
            confirm = QMessageBox.question(
                self,
                "Remove Old Card Images",
                (
                    "Remove all card images from the current image folder and its crop folder?\n\n"
                    "This is meant for cleaning out an old batch before starting over.\n"
                    "The default card back will be kept."
                ),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return

            try:
                project_service.clear_old_cards(state, img_dict)
            except OSError as exc:
                application.warn_nonfatal(
                    "Remove Old Card Images Failed",
                    f"The old card images could not be fully removed.\n\n{exc}",
                )
                return

            self.window().refresh(state, img_dict)
            QMessageBox.information(
                self,
                "Old Card Images Removed",
                "The old card images were removed.\n\nYou can now import cards or choose a different image folder.",
            )

        render_button.clicked.connect(render)
        cropper_button.clicked.connect(run_cropper)
        home_button.clicked.connect(application.show_home)
        save_button.clicked.connect(save_project)
        load_button.clicked.connect(load_project)
        set_images_button.clicked.connect(set_images_folder)
        open_images_button.clicked.connect(open_images_folder)
        settings_button.clicked.connect(open_settings)
        import_decklist_button.clicked.connect(import_decklist_images)
        clear_cards_button.clicked.connect(clear_old_cards)

        self._cropper_button = cropper_button
        self._rebuild_after_cropper = False
        self._img_dict = img_dict


class PrintOptionsWidget(QGroupBox):
    def __init__(self, print_dict, img_dict):
        super().__init__()
        state = as_project_state(print_dict)

        self.setTitle("PDF Settings")

        description = QLabel(
            "These settings control the PDF file name, paper size, page direction, and guide lines."
        )
        description.setWordWrap(True)

        print_output = LineEditWithLabel("PDF &Name", state.filename)
        paper_size = ComboBoxWithLabel(
            "&Paper Size", list(page_sizes.keys()), state.pagesize
        )
        orientation = ComboBoxWithLabel(
            "&Orientation", ["Landscape", "Portrait"], state.orient
        )
        guides_checkbox = QCheckBox("Extended Guides")
        guides_checkbox.setChecked(state.extended_guides)

        layout = QVBoxLayout()
        layout.addWidget(description)
        layout.addWidget(print_output)
        layout.addWidget(paper_size)
        layout.addWidget(orientation)
        layout.addWidget(guides_checkbox)

        self.setLayout(layout)

        def change_output(t):
            state.filename = t

        def change_papersize(t):
            state.pagesize = t
            self.window().refresh_preview(state, img_dict)

        def change_orientation(t):
            state.orient = t
            self.window().refresh_preview(state, img_dict)

        def change_guides(s):
            enabled = s == QtCore.Qt.CheckState.Checked
            state.extended_guides = enabled

        print_output._widget.textChanged.connect(change_output)
        paper_size._widget.currentTextChanged.connect(change_papersize)
        orientation._widget.currentTextChanged.connect(change_orientation)
        guides_checkbox.checkStateChanged.connect(change_guides)

        self._print_output = print_output._widget
        self._paper_size = paper_size._widget
        self._orientation = orientation._widget
        self._guides_checkbox = guides_checkbox

    def refresh_widgets(self, print_dict):
        state = as_project_state(print_dict)
        self._print_output.setText(state.filename)
        self._paper_size.setCurrentText(state.pagesize)
        self._orientation.setCurrentText(state.orient)
        self._guides_checkbox.setChecked(state.extended_guides)


class BacksidePreview(QWidget):
    def __init__(self, backside_name, img_dict):
        super().__init__()

        self.setLayout(QVBoxLayout())
        self.refresh(backside_name, img_dict)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def refresh(self, backside_name, img_dict):
        backside_default_image = BacksideImage(backside_name, img_dict)

        backside_width = 120
        backside_height = backside_default_image.heightForWidth(backside_width)
        backside_default_image.setFixedWidth(backside_width)
        backside_default_image.setFixedHeight(backside_height)

        backside_default_label = QLabel(backside_name)

        layout = self.layout()
        for i in reversed(range(layout.count())):
            layout.itemAt(i).widget().setParent(None)

        layout.addWidget(backside_default_image)
        layout.addWidget(backside_default_label)
        layout.setAlignment(
            backside_default_image, QtCore.Qt.AlignmentFlag.AlignHCenter
        )
        layout.setAlignment(
            backside_default_label, QtCore.Qt.AlignmentFlag.AlignHCenter
        )
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        self.setLayout(layout)


class CardOptionsWidget(QGroupBox):
    def __init__(self, print_dict, img_dict):
        super().__init__()
        state = as_project_state(print_dict)

        self.setTitle("Card Settings")

        description = QLabel(
            "Use these settings to adjust bleed, card backs, and oversized card handling."
        )
        description.setWordWrap(True)

        advanced_note = QLabel(
            "Most projects can leave these off. Turn them on only if your cards need backs or oversized printing."
        )
        advanced_note.setWordWrap(True)

        bleed_edge_spin = QDoubleSpinBox()
        bleed_edge_spin.setDecimals(2)
        bleed_edge_spin.setRange(0, inch_to_mm(0.12))
        bleed_edge_spin.setSingleStep(0.1)
        bleed_edge_spin.setSuffix("mm")
        bleed_edge_spin.setValue(float(state.bleed_edge))
        bleed_edge = WidgetWithLabel("&Bleed Edge", bleed_edge_spin)

        bleed_back_divider = QFrame()
        bleed_back_divider.setFrameShape(QFrame.Shape.HLine)
        bleed_back_divider.setFrameShadow(QFrame.Shadow.Sunken)

        backside_enabled = state.backside_enabled
        backside_checkbox = QCheckBox("Print Card Backs")
        backside_checkbox.setChecked(backside_enabled)
        backside_checkbox.setToolTip(
            "Turn this on only if you want separate back pages in the final PDF."
        )

        backside_default_button = QPushButton("Choose Default Back")
        backside_default_preview = BacksidePreview(
            state.backside_default, img_dict
        )
        backside_default_button.setToolTip(
            "Choose the back image used for cards that do not have a custom back."
        )

        backside_offset_spin = QDoubleSpinBox()
        backside_offset_spin.setDecimals(2)
        backside_offset_spin.setRange(-inch_to_mm(0.3), inch_to_mm(0.3))
        backside_offset_spin.setSingleStep(0.1)
        backside_offset_spin.setSuffix("mm")
        backside_offset_spin.setValue(float(state.backside_offset))
        backside_offset = WidgetWithLabel("Back &Offset", backside_offset_spin)
        backside_offset.setToolTip(
            "Adjust this only if front and back pages print slightly misaligned."
        )

        backside_default_button.setEnabled(backside_enabled)
        backside_default_preview.setEnabled(backside_enabled)
        backside_offset.setEnabled(backside_enabled)

        back_over_divider = QFrame()
        back_over_divider.setFrameShape(QFrame.Shape.HLine)
        back_over_divider.setFrameShadow(QFrame.Shadow.Sunken)

        oversized_enabled = state.oversized_enabled
        oversized_checkbox = QCheckBox("Allow Oversized Cards")
        oversized_checkbox.setChecked(oversized_enabled)
        oversized_checkbox.setToolTip(
            "Turn this on only if some cards need a larger print size."
        )

        layout = QVBoxLayout()
        layout.addWidget(description)
        layout.addWidget(advanced_note)
        layout.addWidget(bleed_edge)
        layout.addWidget(bleed_back_divider)
        layout.addWidget(backside_checkbox)
        layout.addWidget(backside_default_button)
        layout.addWidget(backside_default_preview)
        layout.addWidget(backside_offset)
        layout.addWidget(back_over_divider)
        layout.addWidget(oversized_checkbox)

        layout.setAlignment(
            backside_default_preview, QtCore.Qt.AlignmentFlag.AlignHCenter
        )

        self.setLayout(layout)

        def change_bleed_edge(v):
            state.bleed_edge = v
            self.window().refresh_preview(state, img_dict)

        def switch_backside_enabled(s):
            enabled = s == QtCore.Qt.CheckState.Checked
            state.backside_enabled = enabled
            backside_default_button.setEnabled(enabled)
            backside_offset.setEnabled(enabled)
            backside_default_preview.setEnabled(enabled)
            self.window().refresh(state, img_dict)

        def pick_backside():
            default_backside_choice = image_file_dialog(self, state.image_dir)
            if default_backside_choice is not None:
                state.backside_default = default_backside_choice
                backside_default_preview.refresh(
                    state.backside_default, img_dict
                )
                self.window().refresh(state, img_dict)

        def change_backside_offset(v):
            state.backside_offset = v
            self.window().refresh_preview(state, img_dict)

        def switch_oversized_enabled(s):
            enabled = s == QtCore.Qt.CheckState.Checked
            state.oversized_enabled = enabled
            self.window().refresh(state, img_dict)

        bleed_edge_spin.valueChanged.connect(change_bleed_edge)
        backside_checkbox.checkStateChanged.connect(switch_backside_enabled)
        backside_default_button.clicked.connect(pick_backside)
        backside_offset_spin.valueChanged.connect(change_backside_offset)
        oversized_checkbox.checkStateChanged.connect(switch_oversized_enabled)

        self._bleed_edge_spin = bleed_edge_spin
        self._backside_checkbox = backside_checkbox
        self._backside_offset_spin = backside_offset_spin
        self._backside_default_preview = backside_default_preview
        self._oversized_checkbox = oversized_checkbox

    def refresh_widgets(self, print_dict):
        state = as_project_state(print_dict)
        self._bleed_edge_spin.setValue(float(state.bleed_edge))
        self._backside_checkbox.setChecked(state.backside_enabled)
        self._backside_offset_spin.setValue(float(state.backside_offset))
        self._oversized_checkbox.setChecked(state.oversized_enabled)

    def refresh(self, print_dict, img_dict):
        state = as_project_state(print_dict)
        self._backside_default_preview.refresh(state.backside_default, img_dict)


class GlobalOptionsWidget(QGroupBox):
    def __init__(self, print_dict, img_dict):
        super().__init__()
        state = as_project_state(print_dict)

        self.setTitle("App Settings")

        description = QLabel(
            "Open the settings window to edit app-wide options stored in config.ini."
        )
        description.setWordWrap(True)

        secondary_description = QLabel(
            "This is where you adjust how the app behaves overall, such as card grid size and image-processing defaults."
        )
        secondary_description.setWordWrap(True)

        open_settings_button = QPushButton("Open Settings")

        layout = QVBoxLayout()
        layout.addWidget(description)
        layout.addWidget(secondary_description)
        layout.addWidget(open_settings_button)
        self.setLayout(layout)

        def open_settings():
            prior_values = {
                "DisplayColumns": CFG.DisplayColumns,
                "VibranceBump": CFG.VibranceBump,
                "DefaultPageSize": CFG.DefaultPageSize,
            }
            dialog = SettingsDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            dialog.apply()
            if prior_values["DisplayColumns"] != CFG.DisplayColumns:
                self.window().refresh(state, img_dict)
            elif (
                prior_values["VibranceBump"] != CFG.VibranceBump
                or prior_values["DefaultPageSize"] != CFG.DefaultPageSize
            ):
                self.window().refresh_preview(state, img_dict)

        open_settings_button.clicked.connect(open_settings)


class OptionsWidget(QWidget):
    def __init__(
        self,
        application,
        print_dict,
        img_dict,
    ):
        super().__init__()
        state = as_project_state(print_dict)

        workflow_guide = WorkflowGuideWidget()
        actions_widget = ActionsWidget(
            application,
            state,
            img_dict,
        )
        print_options = PrintOptionsWidget(state, img_dict)
        card_options = CardOptionsWidget(state, img_dict)
        global_options = GlobalOptionsWidget(state, img_dict)

        layout = QVBoxLayout()
        layout.addWidget(workflow_guide)
        layout.addWidget(actions_widget)
        layout.addWidget(print_options)
        layout.addWidget(card_options)
        layout.addWidget(global_options)
        layout.addStretch()

        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        self._print_options = print_options
        self._card_options = card_options

    def refresh_widgets(self, print_dict):
        self._print_options.refresh_widgets(print_dict)
        self._card_options.refresh_widgets(print_dict)

    def refresh(self, print_dict, img_dict):
        self._card_options.refresh(print_dict, img_dict)


class CardTabs(QTabWidget):
    def __init__(self, print_dict, img_dict, scroll_area, print_preview):
        super().__init__()
        state = as_project_state(print_dict)

        self.addTab(scroll_area, "Cards")
        self.addTab(print_preview, "Preview")

        def current_changed(i):
            if i == 1:
                print_preview.refresh(state, img_dict)

        self.currentChanged.connect(current_changed)


class ProjectTileWidget(QWidget):
    open_requested = QtCore.pyqtSignal(str)
    delete_requested = QtCore.pyqtSignal(str)

    def __init__(self, project_entry):
        super().__init__()
        self.setMouseTracking(True)
        self._project_id = project_entry.get("id")

        thumbnail = QLabel()
        thumbnail.setPixmap(project_thumbnail_pixmap(project_entry.get("thumbnail_path")))
        thumbnail.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        thumbnail.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        modified = project_entry.get("modified_at") or project_entry.get("last_opened_at")
        modified_text = "Unknown"
        if modified:
            try:
                modified_text = (
                    datetime.datetime.fromisoformat(modified).astimezone().strftime("%Y-%m-%d %H:%M")
                )
            except ValueError:
                modified_text = modified

        title = QLabel(project_entry.get("display_name", "Untitled Project"))
        title.setWordWrap(True)
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-weight: bold;")
        title.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        subtitle = QLabel(f"Modified: {modified_text}")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #666666;")
        subtitle.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        layout = QVBoxLayout()
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(thumbnail)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        self.setLayout(layout)
        self.setFixedSize(210, 228)
        self.setStyleSheet(
            "ProjectTileWidget {"
            "background-color: #171717; border: 1px solid #2c2c2c; border-radius: 10px;"
            "}"
        )

        delete_button = QPushButton("X", self)
        delete_button.setFixedSize(24, 24)
        delete_button.setToolTip("Delete this project")
        delete_button.setStyleSheet(
            "QPushButton {"
            "background-color: #8d2d2d; color: white; font-weight: bold;"
            "border: 1px solid #b85555; border-radius: 12px;"
            "}"
            "QPushButton:hover { background-color: #a83a3a; }"
        )
        delete_button.hide()
        delete_button.clicked.connect(
            lambda: self.delete_requested.emit(self._project_id)
        )
        self._delete_button = delete_button

    def enterEvent(self, event):
        super().enterEvent(event)
        self._delete_button.show()
        self._delete_button.raise_()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._delete_button.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._delete_button.move(self.width() - self._delete_button.width() - 6, 6)
        self._delete_button.raise_()

    def mouseDoubleClickEvent(self, event):
        super().mouseDoubleClickEvent(event)
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.open_requested.emit(self._project_id)


class ProjectDashboardPage(QWidget):
    def __init__(self, application):
        super().__init__()

        self._application = application
        self._projects = []

        title = QLabel("Projects")
        title.setStyleSheet("font-size: 28px; font-weight: bold;")
        subtitle = QLabel(
            "Open a saved project, import one from a file, or start a fresh draft."
        )
        subtitle.setWordWrap(True)

        helper_text = QLabel(
            "If you are new here, start a fresh draft, import or add your cards, then save the project once it looks right."
        )
        helper_text.setWordWrap(True)

        empty_state = QLabel(
            "No projects yet.\n\n"
            "Click the green + button to start a new draft, or click 'Import Project' if you already have a saved project file."
        )
        empty_state.setWordWrap(True)
        empty_state.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        empty_state.setFrameShape(QFrame.Shape.StyledPanel)
        empty_state.setStyleSheet("padding: 24px;")
        self._empty_state = empty_state

        project_list = QListWidget()
        project_list.setViewMode(QListWidget.ViewMode.IconMode)
        project_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        project_list.setMovement(QListWidget.Movement.Static)
        project_list.setSpacing(14)
        project_list.setIconSize(QtCore.QSize(120, 160))
        project_list.setGridSize(QtCore.QSize(220, 230))
        self._project_list = project_list

        import_button = QPushButton("Import Project")
        new_button = QPushButton("+")
        new_button.setFixedSize(56, 56)
        new_button.setStyleSheet(
            "QPushButton {"
            "font-size: 28px; font-weight: bold; border-radius: 28px; "
            "background-color: #1f6f4a; color: white; border: 2px solid #17563a;"
            "}"
            "QPushButton:hover { background-color: #289b63; border-color: #43c884; }"
            "QPushButton:pressed { background-color: #1a5f40; }"
        )
        new_button.setToolTip("Start a new project draft")

        import_button.clicked.connect(self.import_project)
        new_button.clicked.connect(application.open_blank_editor)

        top_row = QHBoxLayout()
        top_row.addWidget(title)
        top_row.addStretch()
        top_row.addWidget(import_button)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        bottom_row.addWidget(new_button)

        layout = QVBoxLayout()
        layout.addLayout(top_row)
        layout.addWidget(subtitle)
        layout.addWidget(helper_text)
        layout.addWidget(empty_state)
        layout.addWidget(project_list)
        layout.addLayout(bottom_row)
        self.setLayout(layout)

    def refresh_projects(self):
        self._projects = project_library.list_projects()
        self._project_list.clear()
        for project_entry in self._projects:
            item = QListWidgetItem()
            item.setData(QtCore.Qt.ItemDataRole.UserRole, project_entry.get("id"))
            item.setSizeHint(QtCore.QSize(220, 230))
            self._project_list.addItem(item)
            tile = ProjectTileWidget(project_entry)
            tile.open_requested.connect(self._application.open_managed_project)
            tile.delete_requested.connect(self.delete_project)
            self._project_list.setItemWidget(item, tile)

        has_projects = self._project_list.count() > 0
        self._empty_state.setVisible(not has_projects)
        self._project_list.setVisible(has_projects)

        if self._project_list.count() > 0:
            self._project_list.setCurrentRow(0)

    def selected_project_id(self):
        item = self._project_list.currentItem()
        if item is None:
            return None
        return item.data(QtCore.Qt.ItemDataRole.UserRole)

    def open_selected(self):
        project_id = self.selected_project_id()
        if project_id is None:
            return
        self._application.open_managed_project(project_id)

    def import_project(self):
        selected_path = project_file_dialog(
            self,
            FileDialogType.Open,
            project_library.projects_root(),
        )
        if selected_path is None or not os.path.exists(selected_path):
            return
        self._application.import_and_open_project(selected_path)
        self.refresh_projects()

    def delete_project(self, project_id):
        delete_project_with_confirmation(
            self, self._application, project_id, self.refresh_projects
        )



__all__ = [
    "ActionsWidget",
    "BacksidePreview",
    "CardGrid",
    "CardOptionsWidget",
    "CardScrollArea",
    "CardTabs",
    "CardWidget",
    "DummyCardWidget",
    "EditorPage",
    "GlobalOptionsWidget",
    "OptionsWidget",
    "PageGrid",
    "PagePreview",
    "PrintOptionsWidget",
    "PrintPreview",
    "ProjectDashboardPage",
    "ProjectTileWidget",
    "WorkflowGuideWidget",
]
