#!/usr/bin/env python3
"""
First run: opens a terminal over VNC, starts xeyes there,
takes a screenshot of the screen and quits xeyes again.

    ./start.sh archiv/vnc_test.py
    ./start.sh archiv/vnc_test.py --shot image.png --wait 3

find_needle/wait_for are there for the next step (needle search).
"""

import argparse
import os
import sys
import time

import cv2
import numpy as np
from vncdotool import api

# --- Target system ------------------------------------------------------
# CAUTION: one colon is the display number (:1 -> port 5901),
# two colons are the actual port. So 5001 needs '::'.
SERVER = "172.19.0.10::5901"
PASSWORD = "123456"          # or "geheim"

APP = "xeyes"
TERMINAL_KEY = "ctrl-alt-t"   # XFCE default for the terminal

# All images into the project's own tmp/, not /tmp and not the root
# directory. Derived from the script location, so the CWD doesn't matter.
# One level up: the script sits in archiv/, tmp/ belongs to the project.
TMPDIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tmp")
os.makedirs(TMPDIR, exist_ok=True)

FRAME = os.path.join(TMPDIR, "frame.png")
FAIL_SHOT = os.path.join(TMPDIR, "error.png")
SHOT = os.path.join(TMPDIR, "screenshot.png")


def type_text(client, text, delay=0.05):
    """Types a string character by character; capitals with shift."""
    for ch in text:
        client.keyPress("shift-%s" % ch.lower() if ch.isupper() else ch)
        time.sleep(delay)


def find_needle(client, needle, threshold, region=None):
    """Searches the needle in the current framebuffer.

    Returns: (score, centre_x, centre_y) - coordinates in the full image.
    """
    ox, oy = 0, 0
    if region:
        x, y, w, h = region
        client.captureRegion(FRAME, x, y, w, h)
        ox, oy = x, y
    else:
        client.captureScreen(FRAME)

    screen = cv2.imread(FRAME, cv2.IMREAD_GRAYSCALE)
    tpl = cv2.imread(needle, cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        raise SystemExit("needle not readable: %s" % needle)
    if screen is None:
        raise SystemExit("screenshot not readable: %s" % FRAME)
    if tpl.shape[0] > screen.shape[0] or tpl.shape[1] > screen.shape[1]:
        raise SystemExit("needle is larger than the search area")

    res = cv2.matchTemplate(screen, tpl, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)

    h, w = tpl.shape
    return score, ox + loc[0] + w // 2, oy + loc[1] + h // 2


def wait_for(client, needle, timeout, threshold, region=None, interval=0.5):
    """Polls until the needle shows up. Raises AssertionError on timeout."""
    deadline = time.time() + timeout
    best = 0.0
    while time.time() < deadline:
        score, cx, cy = find_needle(client, needle, threshold, region)
        best = max(best, score)
        if score >= threshold:
            return cx, cy, score
        time.sleep(interval)

    client.captureScreen(FAIL_SHOT)
    raise AssertionError(
        "'%s' not found after %ss (best score %.3f, needed %.2f) "
        "- Screenshot: %s" % (needle, timeout, best, threshold, FAIL_SHOT)
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--server", default=SERVER)
    p.add_argument("--shot", default=SHOT, help="target PNG for the screenshot")
    p.add_argument("--wait", type=float, default=2.0,
                   help="seconds xeyes gets before the screenshot")
    args = p.parse_args()

    client = api.connect(args.server, password=PASSWORD)
    try:
        # So that the connection is up and a first frame is there
        client.refreshScreen()
        time.sleep(1)

        # 1) open terminal
        client.keyPress(TERMINAL_KEY)
        time.sleep(2)

        # 2) start xeyes in the foreground
        type_text(client, APP)
        client.keyPress("enter")
        time.sleep(args.wait)

        # 3) Screenshot
        client.captureScreen(args.shot)
        print("Screenshot: %s" % args.shot)

        # 4) quit xeyes - xfwm4 focuses new windows, hence Alt-F4
        #    on the xeyes window instead of Ctrl-C in the terminal
        client.keyPress("alt-f4")
        print("xeyes quit")
    finally:
        api.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
