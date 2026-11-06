"""Image sources: the real VNC desktop and a static PNG as a stand-in.

Both offer the same methods (screenshot/key/type_text/click/move/close,
plus double_click/right_click/mouse_down/mouse_up/scroll/key_down/key_up),
so runner and bridge don't need to know what they're talking to.
"""

import os
import time

import cv2

from .config import PASSWORD, SERVER, tmp_path


class VncSession:
    """Remote control of a VNC desktop."""

    def __init__(self, server=SERVER, password=PASSWORD):
        from vncdotool import api   # lazy: offline mode stays free of it
        self._api = api
        self.client = api.connect(server, password=password)
        # A debugger stopped in a test suspends every thread - vncdotool's
        # reactor too, and a Click typed into the debug console would wait
        # on it for ever. pydevd (debugpy) leaves threads with this mark
        # running; nobody wants to step through twisted anyway.
        reactor = getattr(api, "_THREAD", None)
        if reactor is not None:
            reactor.is_pydev_daemon_thread = True
        self.client.refreshScreen()
        time.sleep(1)

    def screenshot(self, path=None):
        # One file per process: the live view's bridge and a test run share
        # tmp/, and a shared _frame.png got read while the other process was
        # half-way through writing it (libpng "Read Error").
        path = path or tmp_path("_frame_%d.png" % os.getpid())
        for attempt in range(3):
            self.client.refreshScreen()
            self.client.captureScreen(path)
            img = cv2.imread(path)
            if img is not None:
                return img
            time.sleep(0.5)
        raise RuntimeError("screenshot not readable: %s" % path)

    def key(self, k):
        self.client.keyPress(k)

    def type_text(self, text, delay=0.05):
        for ch in text:
            self.client.keyPress("shift-%s" % ch.lower() if ch.isupper() else ch)
            time.sleep(delay)

    def click(self, x, y):
        self.client.mouseMove(int(x), int(y))
        time.sleep(0.2)
        self.client.mousePress(1)

    def move(self, x, y):
        self.client.mouseMove(int(x), int(y))

    def double_click(self, x, y):
        self.client.mouseMove(int(x), int(y))
        time.sleep(0.2)
        self.client.mousePress(1)
        time.sleep(0.08)        # well inside any double-click interval
        self.client.mousePress(1)

    def right_click(self, x, y):
        self.client.mouseMove(int(x), int(y))
        time.sleep(0.2)
        self.client.mousePress(3)

    def mouse_down(self, x, y, button=1):
        self.client.mouseMove(int(x), int(y))
        time.sleep(0.2)
        self.client.mouseDown(button)

    def mouse_up(self, x, y, button=1):
        self.client.mouseMove(int(x), int(y))
        time.sleep(0.2)
        self.client.mouseUp(button)

    # VNC has no wheel events: the wheel is buttons 4 (up), 5 (down),
    # 6 (left) and 7 (right), one press per notch.
    _WHEEL = {"up": 4, "down": 5, "left": 6, "right": 7}

    def scroll(self, direction, count=1):
        button = self._WHEEL[direction]
        for _ in range(int(count)):
            self.client.mousePress(button)
            time.sleep(0.05)

    def key_down(self, k):
        self.client.keyDown(k)

    def key_up(self, k):
        self.client.keyUp(k)

    def close(self):
        self._api.shutdown()


class ImageSource:
    """Static image instead of VNC - for pure prompt tuning."""

    def __init__(self, path):
        self.img = cv2.imread(path)
        if self.img is None:
            raise SystemExit("image not readable: %s" % path)
        self.path = path

    def screenshot(self):
        return self.img.copy()

    def key(self, k):
        print("  (offline: key %s ignored)" % k)

    def type_text(self, t):
        print("  (offline: type %r ignored)" % t)

    def click(self, x, y):
        print("  (offline: click %d,%d ignored)" % (x, y))

    def move(self, x, y):
        print("  (offline: mouse %d,%d ignored)" % (x, y))

    def double_click(self, x, y):
        print("  (offline: double click %d,%d ignored)" % (x, y))

    def right_click(self, x, y):
        print("  (offline: right click %d,%d ignored)" % (x, y))

    def mouse_down(self, x, y, button=1):
        print("  (offline: mouse down %d,%d ignored)" % (x, y))

    def mouse_up(self, x, y, button=1):
        print("  (offline: mouse up %d,%d ignored)" % (x, y))

    def scroll(self, direction, count=1):
        print("  (offline: scroll %s x%d ignored)" % (direction, count))

    def key_down(self, k):
        print("  (offline: key down %s ignored)" % k)

    def key_up(self, k):
        print("  (offline: key up %s ignored)" % k)

    def close(self):
        pass
