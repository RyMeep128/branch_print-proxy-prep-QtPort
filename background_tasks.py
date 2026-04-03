import logging
import sys

import PyQt6.QtCore as QtCore
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout

import high_res


logger = logging.getLogger(__name__)


def popup(window, middle_text, debug_thread):
    class PopupWindow(QDialog):
        def __init__(self, parent, text):
            super().__init__(parent)

            text_widget = QLabel(text)
            layout = QVBoxLayout()
            layout.addWidget(text_widget)
            self.setLayout(layout)
            self.setWindowFlags(
                QtCore.Qt.WindowType.FramelessWindowHint
                | QtCore.Qt.WindowType.WindowStaysOnTopHint
            )

            palette = self.palette()
            palette.setColor(self.backgroundRole(), 0x111111)
            self.setPalette(palette)
            self.setAutoFillBackground(True)

            self._text = text_widget
            self._thread = None

            self.update_text_impl(text)

        def update_text(self, text, force_this_thread=False):
            if self._thread is None or force_this_thread:
                self.update_text_impl(text)
            else:
                self._thread._refresh.emit(text)

        @QtCore.pyqtSlot(str)
        def update_text_impl(self, text):
            self.adjustSize()
            self._text.setText(text)
            self.adjustSize()
            self.recenter()

        def recenter(self):
            parent = self.parentWidget()
            if parent is not None:
                center = self.rect().center()
                parent_half_size = parent.rect().size() / 2
                offset = (
                    QtCore.QPoint(parent_half_size.width(), parent_half_size.height())
                    - center
                )
                self.move(offset)

        def show_during_work(self, work):
            class WorkThread(QtCore.QThread):
                _refresh = QtCore.pyqtSignal(str)

                def __init__(self):
                    super().__init__()
                    self._exception_info = None

                def run(self):
                    if debug_thread:
                        import debugpy

                        debugpy.debug_this_thread()

                    try:
                        work()
                    except Exception:
                        logger.exception("background popup task failed title=%s", middle_text)
                        self._exception_info = sys.exc_info()

            work_thread = WorkThread()

            self.open()
            work_thread.finished.connect(lambda: self.close())
            work_thread._refresh.connect(self.update_text_impl)
            work_thread.start()
            self._thread = work_thread
            self.exec()
            self._thread = None

            if work_thread._exception_info is not None:
                _exc_type, exc_value, exc_traceback = work_thread._exception_info
                if hasattr(exc_value, "add_note"):
                    exc_value.add_note(f"Background task failed: {middle_text}")
                raise exc_value.with_traceback(exc_traceback)

        def showEvent(self, event):
            super().showEvent(event)
            self.recenter()

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self.recenter()
            self.recenter()
            self.recenter()

    return PopupWindow(window, middle_text)


def make_popup_print_fn(progress_popup):
    def popup_print_fn(text):
        try:
            print(text)
        except UnicodeEncodeError:
            pass
        progress_popup.update_text(text)

    return popup_print_fn


class HighResThumbnailLoader(QtCore.QThread):
    thumbnail_loaded = QtCore.pyqtSignal(int, str, bytes)

    def __init__(self, page_token, items):
        super().__init__()
        self._page_token = page_token
        self._items = items
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for _row, identifier, url in self._items:
            if self._cancelled:
                return
            try:
                data = high_res.fetch_preview_bytes(url, cache_kind="thumbnail")
            except (OSError, ValueError):
                logger.warning("thumbnail load failed identifier=%s url=%s", identifier, url)
                continue
            if self._cancelled:
                return
            self.thumbnail_loaded.emit(self._page_token, identifier, data)


__all__ = ["HighResThumbnailLoader", "make_popup_print_fn", "popup"]
