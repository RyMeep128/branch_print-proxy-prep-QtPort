import image
import gui_qt
from util import *

def main():
    app = gui_qt.init()
    image.init()
    window = gui_qt.window_setup(app)

    gui_qt.event_loop(app)
    app.autosave_managed_session()
    app.close()

if __name__ == "__main__":
    gui_qt.install_exception_handlers()
    main()
