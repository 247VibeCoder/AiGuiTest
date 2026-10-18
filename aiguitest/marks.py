"""Image analysis: candidate search, set-of-marks and template matching.

This module imports nothing from the package and is therefore the lowest
layer - workbench and runner both depend on it.
"""

import cv2
import numpy as np


def candidate_boxes(img, min_side=10, max_side=260):
    """Rough candidate search via edges - good enough for buttons and icons."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 60, 180)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    # RETR_LIST instead of RETR_EXTERNAL: otherwise the window frame
    # swallows every button inside it.
    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if min_side <= w <= max_side and min_side <= h <= max_side:
            if not any(abs(x - a) < 6 and abs(y - b) < 6 for a, b, _, _ in out):
                out.append((x, y, w, h))
    out.sort(key=lambda b: (b[1] // 40, b[0]))      # row by row
    return out[:60]


def needle_filter(img, boxes, needle_path, threshold=0.9, pad=6):
    """Restrict the candidates to those resembling an example image.

    The model is bad at picking the right one out of 60 numbered boxes and
    good at deciding between two. The template answers 'is this a close
    button', the model 'in which window'. Returns [(box, score), ...],
    descending.
    """
    # ValueError, not SystemExit: the workbench only catches Exception, a
    # typo in the path would otherwise end the session and its step list.
    needle = cv2.imread(needle_path)
    if needle is None:
        raise ValueError("needle not readable: %s" % needle_path)
    if needle.shape[0] > img.shape[0] or needle.shape[1] > img.shape[1]:
        raise ValueError("needle is larger than the screenshot")
    nh, nw = needle.shape[:2]
    res = cv2.matchTemplate(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                            cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY),
                            cv2.TM_CCOEFF_NORMED)
    out = []
    for x, y, w, h in boxes:
        # res[y][x] is the TOP LEFT corner of the hit, not its centre. If the
        # needle is larger than the candidate, that corner lies well above/
        # left of the box - hence computing via centres instead of box edges.
        ty = y + h // 2 - nh // 2
        tx = x + w // 2 - nw // 2
        y0, y1 = max(0, ty - pad), min(res.shape[0], ty + pad + 1)
        x0, x1 = max(0, tx - pad), min(res.shape[1], tx + pad + 1)
        if y1 <= y0 or x1 <= x0:
            continue
        s = float(res[y0:y1, x0:x1].max())
        if s >= threshold:
            out.append(((x, y, w, h), s))
    out.sort(key=lambda t: -t[1])
    return out


# Minimum distance between two number labels in pixels
GAP = 6


def draw_marks(img, boxes):
    """Outline candidates in red and number them."""
    vis = img.copy()
    font, size = cv2.FONT_HERSHEY_SIMPLEX, 0.4
    for i, (x, y, w, h) in enumerate(boxes, 1):
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)
    # Numbers only after all frames, otherwise a later frame paints over an
    # earlier label.
    placed = []
    for i, (x, y, w, h) in enumerate(boxes, 1):
        # Label INSIDE at the top left: above the box it sat right under the
        # row above in dense menus and was assigned to it ('14' under
        # 'Terminal' belonged to 'File Manager').
        (tw, th), _ = cv2.getTextSize(str(i), font, size, 1)
        lw, lh = tw + 4, th + 4
        # The model reads two adjacent labels as one number: '1' at the icon
        # and '2' at the text of 'Applications' became '12'. So move to
        # another corner of the box if necessary.
        corners = [(x, y), (x + w - lw, y), (x, y + h - lh),
                   (x + w - lw, y + h - lh)]
        lx, ly = corners[0]
        for cx, cy in corners:
            if not any(cx < px + pw + GAP and px < cx + lw + GAP and
                       cy < py + ph + GAP and py < cy + lh + GAP
                       for px, py, pw, ph in placed):
                lx, ly = cx, cy
                break
        placed.append((lx, ly, lw, lh))
        cv2.rectangle(vis, (lx, ly), (lx + lw, ly + lh), (0, 0, 255), -1)
        cv2.putText(vis, str(i), (lx + 2, ly + th + 2), font, size,
                    (255, 255, 255), 1)
    return vis


def match(screen, needle, threshold=0.9):
    """Best template occurrence; returns (score, centre_x, centre_y).

    CAUTION: minMaxLoc only returns the global maximum. If an element looks
    the same several times (say the X of two windows), noise decides which
    one wins - then the needle needs context or the search a region.
    """
    res = cv2.matchTemplate(cv2.cvtColor(screen, cv2.COLOR_BGR2GRAY),
                            cv2.cvtColor(needle, cv2.COLOR_BGR2GRAY),
                            cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    h, w = needle.shape[:2]
    return score, loc[0] + w // 2, loc[1] + h // 2
