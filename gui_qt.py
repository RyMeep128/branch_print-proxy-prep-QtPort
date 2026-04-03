import main_window

from main_window import event_loop, init, install_exception_handlers, window_setup

__all__ = [
    "event_loop",
    "init",
    "install_exception_handlers",
    "window_setup",
]


def __getattr__(name):
    return getattr(main_window, name)
