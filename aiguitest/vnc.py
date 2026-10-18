"""Image sources: the real VNC desktop and a static PNG as a stand-in.

Both offer the same methods (screenshot/key/type_text/click/move/close),
so workbench and runner don't need to know what they're talking to.
"""

import time

import cv2

from .config import PASSWORD, SERVER, tmp_path


class VncSession:
    """Remote control of a VNC desktop."""

    def __init__(self, server=SERVER, password=PASSWORD):
        from vncdotool import api   # lazy: offline mode stays free of it
        self._api = api
        self.client = api.connect(server, password=password)
        self.client.refreshScreen()
        time.sleep(1)

    def screenshot(self, path=None):
        path = path or tmp_path("_frame.png")
        self.client.refreshScreen()
        self.client.captureScreen(path)
        img = cv2.imread(path)
        if img is None:
            raise RuntimeError("screenshot not readable: %s" % path)
        return img

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

    def close(self):
        pass
