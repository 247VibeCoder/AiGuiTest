"""Test run: execute steps, log them, repeat without a model."""

import contextlib
import json
import os
import re
import sys
import time

import cv2
import numpy as np

from .config import (LOCATE_NORM, MAX_SIDE, SERVER, VLM_MODEL, image_path,
                     log_path, tmp_path)
from .keys import resolve_key, send_sequence
from .marks import candidate_boxes, draw_marks, match, needle_filter
from .points import (LEARNED, POINTS_DIR, THRESHOLD, TOLERANCE,
                     reference_path, site_key)
from .vlm import Vlm, _extract_json, _shrink


def _slug(text):
    """File-name-safe name from free text."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text or "").strip("_") or "screenshot"


# Keys from the time the file formats were German. Old run folders must
# stay readable for --replay.
_OLD_KEYS = {
    "schritte": "steps", "typ": "type", "erwartet": "expected",
    "passwort": "password", "ziel": "target", "frage": "question",
    "ergebnis": "result", "erfolg": "success", "punkt": "point",
    "datei": "file", "modell": "model", "sehe": "seen", "grund": "reason",
}


def _english_keys(obj):
    """Rename old German keys recursively; values stay untouched.

    If a key appears in both spellings, the English one wins.
    """
    if isinstance(obj, list):
        return [_english_keys(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        new = _OLD_KEYS.get(k, k)
        if new != k and new in obj:
            continue
        out[new] = _english_keys(v)
    return out


def log_marker(text):
    """One form for markers - the same in run and replay, so a search for
    '===' finds them in the log."""
    return "=== %s ===" % text


class _Tee:
    """Writes to the actual stream and additionally to the log file."""

    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, text):
        self.stream.write(text)
        self.log.write(text)
        return len(text)

    def flush(self):
        self.stream.flush()
        self.log.flush()

    def __getattr__(self, name):          # isatty, encoding, fileno ...
        return getattr(self.stream, name)


class RunLog:
    """Open log file of a run; 'path' for output, 'note' for lines that
    belong only in the log (such as the pytest command line)."""

    def __init__(self, path, f):
        self.path, self._f = path, f

    def note(self, text):
        self._f.write(text if text.endswith("\n") else text + "\n")


@contextlib.contextmanager
def run_log(name):
    """Mirror console output to log/<timestamp>_<name>.log.

    stdout and stderr land in the same file, in the order they were
    written. Yields a RunLog; the file is line-buffered so it is complete
    even after a crash.
    """
    path = log_path("%s_%s.log" % (time.strftime("%Y%m%d-%H%M%S"), _slug(name)))
    out, err = sys.stdout, sys.stderr
    with open(path, "w", buffering=1) as f:
        f.write("# %s\n# %s\n\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                     " ".join(sys.argv)))
        # _Tee passes fileno/isatty through, so pytest still sees a
        # terminal and keeps its colours.
        sys.stdout, sys.stderr = _Tee(out, f), _Tee(err, f)
        try:
            yield RunLog(path, f)
        finally:
            sys.stdout, sys.stderr = out, err
            f.write("\n# end %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))


# ---------------------------------------------------------------- Targets --

def parse_target(t):
    """A target as in Click("OkButton") -> dict.

    "SpeichernButton"         image by name: images/SpeichernButton.png
    "image:close.png"         the same, explicitly
    "text:the OK button"      found by the vision model (any description
                              works)
    [x, y]                    a fixed point
    [x1, y1, x2, y2]          a fixed rectangle (read_text, image_found)
    {image: ..., text: ...}   image AND description: the template narrows
                              the candidates, the model picks one
                              (set-of-marks, like click_marks)
    {..., threshold: 0.8}     template threshold, default 0.9
    {..., area: [dx1, dy1, dx2, dy2]}  for read_text: a rectangle relative
                              to the centre of what was found

    Returns {"image": path, "text": str, "point": [x, y],
    "rect": [x1, y1, x2, y2], "threshold": float, "area": [...]}, only the
    keys that apply. SystemExit for a target that is none of the above.
    """
    spec = {}
    if isinstance(t, dict):
        if t.get("image"):
            spec["image"] = image_path(str(t["image"]))
        if t.get("text"):
            spec["text"] = str(t["text"])
        if t.get("point"):
            spec["point"] = [int(v) for v in t["point"]]
        if t.get("rect"):
            spec["rect"] = [int(v) for v in t["rect"]]
        if t.get("area"):
            spec["area"] = [int(v) for v in t["area"]]
        if "threshold" in t:
            spec["threshold"] = float(t["threshold"])
    elif isinstance(t, (list, tuple)) and len(t) in (2, 4):
        spec["point" if len(t) == 2 else "rect"] = [int(v) for v in t]
    elif isinstance(t, str) and t.strip():
        v = t.strip()
        low = v.lower()
        if low.startswith("text:"):
            spec["text"] = v[5:].strip().strip("\"'")
        elif low.startswith("image:"):
            spec["image"] = image_path(v[6:].strip().strip("\"'"))
        else:
            spec["image"] = image_path(v)
    if not any(k in spec for k in ("image", "text", "point", "rect")):
        raise SystemExit("target %r: expected an image name, 'text:...', "
                         "[x, y], [x1, y1, x2, y2] or a dict with image/text"
                         % (t,))
    return spec


def describe_target(spec):
    """Short form of a parsed target for console and run.json."""
    if "image" in spec and "text" in spec:
        return "%s in %s" % (spec["text"], os.path.basename(spec["image"]))
    if "image" in spec:
        return os.path.basename(spec["image"])
    if "text" in spec:
        return "text:" + spec["text"]
    if "rect" in spec:
        return "rect %s" % spec["rect"]
    return "point %s" % spec["point"]


class Run:
    """Executes the steps and writes the replay artefact."""

    def __init__(self, session, vlm, outdir):
        self.s, self.vlm, self.dir = session, vlm, outdir
        self.steps = []
        # log_error/log_warning: the run goes on, the result is recorded.
        # aiguitest-run fails the run at the end if 'errors' is not empty.
        self.errors, self.warnings = [], []
        self._needles = {}
        self._held = None            # point of a 'drag' until its 'drop'
        # remembered points (points.py): where the reference images live,
        # and the points found anew - the plugin writes them back
        self.points_dir = POINTS_DIR
        self.point_updates = []
        os.makedirs(outdir, exist_ok=True)

    def _shot(self, tag):
        img = self.s.screenshot()
        cv2.imwrite(os.path.join(self.dir, "%02d_%s.png" % (len(self.steps), tag)), img)
        return img

    def assert_visible(self, question, timeout=20, interval=2.0, expect=True):
        deadline = time.time() + timeout
        last = {}
        while True:
            img = self._shot("assert")
            last = self.vlm.ask(img, question)
            if last["ok"] == expect:
                break
            if time.time() >= deadline:
                self.steps.append({"type": "assert", "question": question,
                                   "result": last, "success": False})
                raise AssertionError("%s -> %s (%s)" %
                                     (question, last["ok"], last["seen"]))
            time.sleep(interval)
        print("  ok: %s" % last["seen"])
        self.steps.append({"type": "assert", "question": question,
                           "expected": expect, "result": last, "success": True})

    def click_element(self, target, timeout=20, interval=2.0, pad=4):
        deadline = time.time() + timeout
        hit, why = None, ""
        while True:
            img = self._shot("locate")
            try:
                hit = self.vlm.locate(img, target)
            except AssertionError as e:
                # Empty content when the model thinks itself into the context
                # limit in its 'reasoning' - happens occasionally, the next
                # attempt usually works. So treat it like 'not found'.
                why = " (%s)" % e
            if hit:
                break
            if time.time() >= deadline:
                raise AssertionError("element not found: %s%s" % (target, why))
            time.sleep(interval)

        x1, y1, x2, y2 = hit["box"]
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

        # cut a needle for the later replay run
        h, w = img.shape[:2]
        crop = img[max(0, y1 - pad):min(h, y2 + pad),
                   max(0, x1 - pad):min(w, x2 + pad)]
        needle = "%02d_needle.png" % len(self.steps)
        cv2.imwrite(os.path.join(self.dir, needle), crop)

        print("  '%s' at (%d, %d), conf %.2f" % (target, cx, cy, hit["conf"]))
        self.s.click(cx, cy)
        self.steps.append({"type": "click", "target": target, "box": hit["box"],
                           "point": [cx, cy], "needle": needle,
                           "offset": [max(0, x1 - pad), max(0, y1 - pad)],
                           "success": True})
        time.sleep(1)

    def click_marks(self, target, needle_path=None, hint=None):
        """Number the candidates, the model picks a number, then click.

        With needle_path the candidates are sieved by template first - 60
        candidates typically become 2, and only then can the model solve it.
        With a hint (a remembered point, see _recall) the reference image
        is checked first and the model only asked if it doesn't match.
        """
        img = self._shot("marks")
        hit, why = self._recall(img, target, hint)
        if hit is None:
            if hint and hint.get("strict"):
                self.steps.append({"type": "click_marks", "target": target,
                                   "success": False})
                raise AssertionError("click_marks: %s" % why)
            x, y, w, h = self._marks_box(img, target, needle_path)
            hit = {"point": [x + w // 2, y + h // 2],
                   "box": [x, y, x + w, y + h], "via": "model"}
        cx, cy = hit["point"]
        self._learn(target, hint, hit, img)
        self.s.click(cx, cy)
        self.steps.append({"type": "click_marks", "target": target,
                           "point": [cx, cy], "needle": needle_path,
                           "via": hit["via"], "success": True})
        time.sleep(1)

    # ------------------------------------------------ remembered points --
    # Click(text=..., point=(x, y)): the point is checked against the
    # reference image images/points/<text>.png before the model is asked.

    def _recall(self, img, text, hint):
        """The remembered element on this screenshot -> (hit, why).

        hit is {"point", "box", "score", "via": "point"|"moved"} - "point"
        if the reference image matches around the remembered point,
        "moved" if it matches elsewhere. (None, reason) if there is no
        hint, no reference image or no match.
        """
        if not hint:
            return None, ""
        ref_path = reference_path(text, self.points_dir)
        old = hint.get("point")
        ref = cv2.imread(ref_path) if old is not None else None
        if ref is None:
            return None, ("--nollm: no remembered point with a reference "
                          "image for '%s' - run it once without --nollm"
                          % text)
        rh, rw = ref.shape[:2]
        h, w = img.shape[:2]
        if rh > h or rw > w:
            return None, "reference image larger than the screen"
        # around the point first: the same element, not a look-alike
        r = max(48, rw, rh)
        x1, y1 = max(0, old[0] - r - rw // 2), max(0, old[1] - r - rh // 2)
        x2, y2 = min(w, old[0] + r + rw // 2), min(h, old[1] + r + rh // 2)
        via, score = "point", -1.0
        if x2 - x1 >= rw and y2 - y1 >= rh:
            res = cv2.matchTemplate(img[y1:y2, x1:x2], ref,
                                    cv2.TM_CCOEFF_NORMED)
            _, score, _, (bx, by) = cv2.minMaxLoc(res)
            cx, cy = x1 + bx + rw // 2, y1 + by + rh // 2
        if score < THRESHOLD:
            via = "moved"
            score, cx, cy = match(img, ref)
        if score < THRESHOLD:
            return None, ("--nollm: '%s' no longer looks like its reference "
                          "image (best score %.3f) - run it once without "
                          "--nollm" % (text, score))
        print("  '%s' -> remembered point%s (%d, %d), score %.3f"
              % (text, " moved to" if via == "moved" else "", cx, cy, score))
        return {"point": [int(cx), int(cy)], "score": round(float(score), 3),
                "box": [int(cx) - rw // 2, int(cy) - rh // 2,
                        int(cx) - rw // 2 + rw, int(cy) - rh // 2 + rh],
                "via": via}, ""

    def _learn(self, text, hint, hit, img):
        """After a hit: note a new or moved point for the source, and keep
        what the model found as the reference image."""
        if not hint:
            return
        if hit.get("via") == "model" and hit.get("box"):
            x1, y1, x2, y2 = hit["box"]
            h, w = img.shape[:2]
            crop = img[max(0, y1 - 4):min(h, y2 + 4), max(0, x1 - 4):min(w, x2 + 4)]
            if crop.size:
                os.makedirs(self.points_dir, exist_ok=True)
                cv2.imwrite(reference_path(text, self.points_dir), crop)
        old, new = hint.get("point"), hit["point"]
        if hint.get("site"):
            LEARNED[site_key(hint["site"])] = list(new)
        if old is not None and abs(old[0] - new[0]) <= TOLERANCE \
                and abs(old[1] - new[1]) <= TOLERANCE:
            return
        if hint.get("site"):
            self.point_updates.append({"site": hint["site"], "text": text,
                                       "point": list(new),
                                       "old": list(old) if old else None})

    def _marks_box(self, img, target, needle_path=None):
        """The set-of-marks choice as (x, y, w, h); AssertionError if none."""
        boxes = candidate_boxes(img)
        if needle_path:
            try:
                hits = needle_filter(img, boxes, needle_path)
            except ValueError as e:
                raise AssertionError(str(e))   # so that main() catches it
            if not hits:
                raise AssertionError("needle %s matches no candidate"
                                     % needle_path)
            boxes = [b for b, _ in hits]
            print("  needle %s: %d of %d candidates, best score %.3f"
                  % (needle_path, len(boxes), len(candidate_boxes(img)),
                     hits[0][1]))

        vis = draw_marks(img, boxes)
        question = ("Elements in the image are numbered in red. Which number "
                    "is: %s\n"
                    'Answer ONLY as {"number": <int>, "conf": 0.0}' % target)
        out, _ = self.vlm._chat(vis, question)
        n = int(out["number"])
        if not 1 <= n <= len(boxes):
            raise AssertionError("model named number %d, there are 1..%d"
                                 % (n, len(boxes)))
        x, y, w, h = boxes[n - 1]
        print("  '%s' -> number %d, centre (%d,%d)"
              % (target, n, x + w // 2, y + h // 2))
        return x, y, w, h

    def screenshot(self, name="screenshot"):
        """Named screenshot as a step of its own."""
        filename = "%02d_%s.png" % (len(self.steps), _slug(name))
        path = os.path.join(self.dir, filename)
        cv2.imwrite(path, self.s.screenshot())
        print("  screenshot: %s" % path)
        self.steps.append({"type": "screenshot", "name": name,
                           "file": filename, "success": True})
        return path

    def error_screenshot(self, name="error"):
        """Image of the state at abort - must not fail itself."""
        try:
            img = self.s.screenshot()
        except Exception as e:
            print("  screenshot after error not possible: %s" % e)
            return None
        path = os.path.join(self.dir, "%s.png" % _slug(name))
        cv2.imwrite(path, img)
        return path

    def key(self, k, note=""):
        """Send a key. Readable names work too: 'Enter', 'ControlKey-c',
        ['ControlKey', 'c']; the log holds the translated vncdotool name."""
        k = resolve_key(k)
        self.s.key(k)
        self.steps.append({"type": "key", "key": k, "note": note})
        time.sleep(2)

    def type_text(self, text):
        """Type text. A list is a TypeText sequence: key names in
        it are keys, modifiers combine with the next item - see keys.py."""
        if isinstance(text, (list, tuple)):
            send_sequence(self.s, list(text))
            text = list(text)
        else:
            self.s.type_text(text)
        self.steps.append({"type": "type", "text": text})

    def type_sequence(self, seq):
        """Text and keys in order: [("text", "geheim"), ("key", "enter")].

        TypeText in commands.py builds the list - it knows which items are
        keys, so a plain "Enter" is typed as a word, not pressed.
        """
        for kind, value in seq:
            if kind == "key":
                self.s.key(value)
            else:
                self.s.type_text(value)
            time.sleep(0.1)
        print("  type %s" % " ".join(
            "<%s>" % v if k == "key" else repr(v) for k, v in seq))
        self.steps.append({"type": "type", "sequence": [list(p) for p in seq]})

    def log(self, text):
        """Marker in output and log, e.g. 'ready for step 2'."""
        print(log_marker(text))
        self.steps.append({"type": "log", "text": text})

    def click_needle(self, needle_path, timeout=20, interval=2.0, threshold=0.9):
        """Search a needle by template and click it - without a model.

        For targets that exist only once on screen. If an element looks the
        same several times, the global maximum of match() wins; then use
        click_marks with a needle, where the model decides.
        """
        needle = cv2.imread(needle_path)
        if needle is None:
            raise AssertionError("needle not readable: %s" % needle_path)
        deadline = time.time() + timeout
        while True:
            score, cx, cy = match(self._shot("needle"), needle)
            if score >= threshold:
                break
            if time.time() >= deadline:
                self.steps.append({"type": "click_needle", "needle": needle_path,
                                   "threshold": threshold, "score": score,
                                   "success": False})
                raise AssertionError("needle %s not found (best score %.3f)"
                                     % (needle_path, score))
            time.sleep(interval)
        print("  needle %s at (%d, %d), score %.3f" % (needle_path, cx, cy, score))
        self.s.click(cx, cy)
        self.steps.append({"type": "click_needle", "needle": needle_path,
                           "threshold": threshold, "point": [cx, cy],
                           "score": score, "success": True})
        time.sleep(1)

    def mouse(self, x, y):
        """Only move the mouse, no click - e.g. away from the target, so no
        hover effect skews the next needle or judgement."""
        self.s.move(x, y)
        print("  mouse to (%d, %d)" % (x, y))
        self.steps.append({"type": "mouse", "point": [x, y], "success": True})
        time.sleep(0.5)

    def click_point(self, x, y, target=""):
        """Click a stored position without letting the model search."""
        self._shot("point")
        print("  '%s' -> stored position (%d, %d)" % (target, x, y))
        self.s.click(x, y)
        self.steps.append({"type": "click_point", "target": target,
                           "point": [x, y], "success": True})
        time.sleep(1)

    # ------------------------------------------------- targets & actions --
    # The actions behind the commands: each takes a target (parse_target),
    # waits for it up to 'timeout' and logs an entry replay can repeat.

    def _needle(self, path):
        if path not in self._needles:
            needle = cv2.imread(path)
            if needle is None:
                raise AssertionError(
                    "image not readable: %s (a description needs 'text:')"
                    % path)
            self._needles[path] = needle
        return self._needles[path]

    def _find_once(self, img, spec):
        """One attempt on one screenshot -> {"point", "box", ...} or None."""
        if "point" in spec:
            return {"point": list(spec["point"]), "box": None}
        if "rect" in spec:
            x1, y1, x2, y2 = spec["rect"]
            return {"point": [(x1 + x2) // 2, (y1 + y2) // 2],
                    "box": [x1, y1, x2, y2]}
        hint = spec.get("hint")
        if hint and "text" in spec:
            hit, why = self._recall(img, spec["text"], hint)
            if hit:
                return hit
            if hint.get("strict"):               # --nollm: no model
                return {"why": why}
        if "image" in spec and "text" in spec:
            self._needle(spec["image"])          # readable at all?
            try:
                x, y, w, h = self._marks_box(img, spec["text"], spec["image"])
            except AssertionError as e:
                return {"why": str(e)}
            return {"point": [x + w // 2, y + h // 2],
                    "box": [x, y, x + w, y + h], "via": "model"}
        if "image" in spec:
            needle = self._needle(spec["image"])
            nh, nw = needle.shape[:2]
            if nh > img.shape[0] or nw > img.shape[1]:
                return None
            score, cx, cy = match(img, needle)
            if score < spec.get("threshold", 0.9):
                return {"why": "best score %.3f" % score}
            return {"point": [cx, cy], "score": round(float(score), 3),
                    "box": [cx - nw // 2, cy - nh // 2,
                            cx - nw // 2 + nw, cy - nh // 2 + nh]}
        try:
            hit = self.vlm.locate(img, spec["text"])
        except AssertionError as e:
            # empty answer - see click_element; counts as 'not found'
            return {"why": str(e)}
        if not hit:
            return None
        x1, y1, x2, y2 = hit["box"]
        return {"point": [(x1 + x2) // 2, (y1 + y2) // 2],
                "box": hit["box"], "conf": hit.get("conf"), "via": "model"}

    def _find(self, spec, timeout=20, interval=2.0, tag="find"):
        """Poll until found or timeout -> (img, hit or None, why).

        timeout=0 is exactly one attempt. A fixed point needs no screenshot
        to be 'found', but one is still taken - it shows what was clicked.
        """
        deadline = time.time() + float(timeout)
        while True:
            img = self._shot(tag)
            hit = self._find_once(img, spec)
            if hit and "point" in hit:
                return img, hit, ""
            why = (hit or {}).get("why", "")
            if time.time() >= deadline:
                return img, None, why
            time.sleep(interval)

    def _crop(self, img, box, pad=4):
        """Cut what was found as NN_needle.png, for replay. -> name or None"""
        if not box:
            return None
        x1, y1, x2, y2 = box
        h, w = img.shape[:2]
        crop = img[max(0, y1 - pad):min(h, y2 + pad),
                   max(0, x1 - pad):min(w, x2 + pad)]
        if crop.size == 0:
            return None
        name = "%02d_needle.png" % len(self.steps)
        cv2.imwrite(os.path.join(self.dir, name), crop)
        return name

    POINTER_ACTIONS = ("click", "double_click", "right_click", "move_to",
                       "drag", "drop")

    def act(self, action, target, timeout=20, interval=2.0, hint=None,
            required=True):
        """Click, DoubleClick, RightClick, MoveTo, Drag, Drop on a target.

        required=False: a target that doesn't show up is logged as skipped
        and None returned, instead of an AssertionError - except for a
        text target under --nollm (strict), which always fails.

        'drag' presses the button on the target and holds it; the next
        'drop' moves to its target in a few steps and releases there.
        hint: a remembered point for a text target, {"point", "site",
        "strict"} - see _recall; strict (--nollm) never asks the model.
        """
        if action not in self.POINTER_ACTIONS:
            raise SystemExit("unknown action: %s" % action)
        spec = parse_target(target)
        if hint and "text" in spec:
            spec["hint"] = hint
        desc = describe_target(spec)
        if action == "drop" and self._held is None:
            raise AssertionError("drop without a drag before it")
        img, hit, why = self._find(spec, timeout, interval)
        if not hit:
            self.steps.append({"type": action, "target": desc,
                               "success": False, "required": required})
            # --nollm stays strict: a text target it can't confirm without
            # the model fails, required or not - skipping it would hide that
            strict = (spec.get("hint") or {}).get("strict")
            if not required and not strict:
                # the replay skips it like every step with success False
                print("  %s '%s' skipped: not there%s"
                      % (action, desc, " (%s)" % why if why else ""))
                return None
            raise AssertionError("%s: not found: %s%s"
                                 % (action, desc, " (%s)" % why if why else ""))
        cx, cy = hit["point"]
        needle = self._crop(img, hit.get("box"))
        if "hint" in spec:
            self._learn(spec["text"], spec["hint"], hit, img)
        print("  %s '%s' at (%d, %d)" % (action, desc, cx, cy))
        if action == "click":
            self.s.click(cx, cy)
        elif action == "double_click":
            self.s.double_click(cx, cy)
        elif action == "right_click":
            self.s.right_click(cx, cy)
        elif action == "move_to":
            self.s.move(cx, cy)
        elif action == "drag":
            self.s.mouse_down(cx, cy)
            self._held = (cx, cy)
        else:
            _glide(self.s, self._held, (cx, cy))
            self.s.mouse_up(cx, cy)
            self._held = None
        entry = {"type": action, "target": desc, "point": [cx, cy],
                 "box": hit.get("box"), "needle": needle, "success": True}
        for k in ("score", "via"):
            if k in hit:
                entry[k] = hit[k]
        self.steps.append(entry)
        time.sleep(0.5 if action in ("move_to", "drag") else 1)
        return entry

    def scroll(self, direction, count=1, target=None, timeout=20):
        """ScrollWheelDown/Up: 'count' notches, over 'target' if given."""
        if direction not in ("up", "down", "left", "right"):
            raise SystemExit("scroll direction '%s' - allowed are up, down, "
                             "left, right" % direction)
        if target is not None:
            self.act("move_to", target, timeout)
        self.s.scroll(direction, int(count))
        print("  scroll %s x%d" % (direction, int(count)))
        self.steps.append({"type": "scroll", "direction": direction,
                           "count": int(count), "success": True})
        time.sleep(0.5)

    def key_down(self, k):
        k = resolve_key(k)
        self.s.key_down(k)
        self.steps.append({"type": "key_down", "key": k, "success": True})

    def key_up(self, k):
        k = resolve_key(k)
        self.s.key_up(k)
        self.steps.append({"type": "key_up", "key": k, "success": True})

    # ------------------------------------------------- waiting & queries --

    def wait(self, seconds):
        """A hard pause - use wait_for where something is awaited."""
        seconds = float(seconds)
        print("  wait %.1f s" % seconds)
        time.sleep(seconds)
        self.steps.append({"type": "wait", "seconds": seconds})

    def wait_for(self, target, timeout=20, interval=1.0):
        """WaitFor: until the target is visible; AssertionError otherwise."""
        spec = parse_target(target)
        desc = describe_target(spec)
        img, hit, why = self._find(spec, timeout, interval, "wait")
        if not hit:
            self.steps.append({"type": "wait_for", "target": desc,
                               "timeout": timeout, "success": False})
            raise AssertionError("wait_for: %s not visible after %s s%s"
                                 % (desc, timeout, " (%s)" % why if why else ""))
        print("  '%s' visible at (%d, %d)" % (desc, hit["point"][0], hit["point"][1]))
        self.steps.append({"type": "wait_for", "target": desc,
                           "timeout": timeout, "point": hit["point"],
                           "needle": self._crop(img, hit.get("box")),
                           "success": True})

    def wait_while(self, target, timeout=60, interval=1.0):
        """WaitWhile: until the target is gone (a spinner, a dialog)."""
        spec = parse_target(target)
        desc = describe_target(spec)
        deadline = time.time() + float(timeout)
        while True:
            hit = self._find_once(self._shot("wait"), spec)
            if not (hit and "point" in hit):
                break
            if time.time() >= deadline:
                self.steps.append({"type": "wait_while", "target": desc,
                                   "timeout": timeout, "success": False})
                raise AssertionError("wait_while: %s still visible after %s s"
                                     % (desc, timeout))
            time.sleep(interval)
        print("  '%s' gone" % desc)
        self.steps.append({"type": "wait_while", "target": desc,
                           "timeout": timeout, "success": True})

    def image_found(self, target, timeout=0, interval=1.0):
        """ImageFound(): True/False, never raises for 'not there'."""
        spec = parse_target(target)
        _, hit, _ = self._find(spec, timeout, interval, "found")
        found = hit is not None
        print("  image_found('%s') -> %s" % (describe_target(spec), found))
        self.steps.append({"type": "image_found", "target": describe_target(spec),
                           "found": found,
                           "point": hit["point"] if hit else None})
        return found

    def read_text(self, region, timeout=0, interval=1.0):
        """ReadText(): the text in a region, read by the vision model.

        region: a rectangle [x1, y1, x2, y2], an image (its matched area,
        or 'area' relative to its centre) or 'text:<description>' - then
        the model finds and reads in one go, e.g. 'text:the total amount'.
        """
        spec = parse_target(region)
        desc = describe_target(spec)
        prompt_exact = ("Read the text in this image exactly as written. "
                        "Answer with ONLY that text - no quotes, no "
                        "explanation. If there is no text, answer with "
                        "nothing.")
        if "text" in spec and "image" not in spec and "area" not in spec:
            img = self._shot("read")
            answer = self.vlm.raw(img, (
                "Read the text of: %s\nAnswer with ONLY that text - no "
                "quotes, no explanation." % spec["text"]))
        else:
            img, hit, why = self._find(spec, timeout, interval, "read")
            if not hit:
                raise AssertionError("read_text: %s not found%s"
                                     % (desc, " (%s)" % why if why else ""))
            box = hit["box"]
            if "area" in spec:
                cx, cy = hit["point"]
                dx1, dy1, dx2, dy2 = spec["area"]
                box = [cx + dx1, cy + dy1, cx + dx2, cy + dy2]
            if not box:
                raise AssertionError("read_text: %s has no area - give a "
                                     "rectangle or 'area'" % desc)
            h, w = img.shape[:2]
            x1, y1 = max(0, box[0]), max(0, box[1])
            x2, y2 = min(w, box[2]), min(h, box[3])
            crop = img[y1:y2, x1:x2]
            if crop.size == 0:
                raise AssertionError("read_text: area %s is outside the screen"
                                     % box)
            # small crops read badly - give the model something to look at
            if crop.shape[0] < 64:
                f = 64.0 / crop.shape[0]
                crop = cv2.resize(crop, None, fx=f, fy=f,
                                  interpolation=cv2.INTER_CUBIC)
            cv2.imwrite(os.path.join(self.dir, "%02d_read.png" % len(self.steps)),
                        crop)
            answer = self.vlm.raw(crop, prompt_exact)
        text = answer.strip().strip("\"'`").strip()
        print("  read_text('%s') -> %r" % (desc, text))
        self.steps.append({"type": "read_text", "region": desc, "text": text})
        return text

    def ask(self, question):
        """One yes/no judgement by the model, as a value (no polling)."""
        img = self._shot("ask")
        res = self.vlm.ask(img, question)
        print("  ask: %s -> %s (%s)" % (question, res["ok"], res["seen"]))
        self.steps.append({"type": "ask", "question": question,
                           "result": res})
        return res["ok"]

    def describe(self, question):
        """The model's answer in words, as a value - no verdict, no polling."""
        img = self._shot("describe")
        answer = self.vlm.raw(img, (
            "You are looking at a screenshot of a desktop.\n"
            "Answer in one to three plain sentences, without JSON or "
            "Markdown. Only say what is visible.\n"
            "Question: %s" % question)).strip()
        print("  describe: %s -> %s" % (question, answer))
        self.steps.append({"type": "describe", "question": question,
                           "answer": answer})
        return answer

    # ---------------------------------------------------------- logging --

    def log_warning(self, text):
        """LogWarning: noted in output and run.json, the run goes on."""
        print("WARNING: %s" % text)
        self.warnings.append(text)
        self.steps.append({"type": "log_warning", "text": text})

    def log_error(self, text):
        """LogError: the run goes on but ends as failed."""
        print("ERROR: %s" % text, file=sys.stderr)
        self.errors.append(text)
        self.steps.append({"type": "log_error", "text": text})
        # a picture of the moment is what makes such an entry useful later
        self.error_screenshot("error_%02d" % len(self.errors))

    @property
    def failed(self):
        return bool(self.errors)

    def save(self):
        path = os.path.join(self.dir, "run.json")
        with open(path, "w") as f:
            json.dump({"server": SERVER, "model": VLM_MODEL,
                       "status": "failed" if self.errors else "passed",
                       "errors": self.errors, "warnings": self.warnings,
                       "steps": self.steps}, f, indent=2,
                      ensure_ascii=False, default=str)
        return path


def _glide(session, start, end, steps=5):
    """Move from start to end in a few steps - some toolkits only start a
    drag after the pointer has moved with the button held."""
    (x0, y0), (x1, y1) = start, end
    for i in range(1, steps + 1):
        session.move(x0 + (x1 - x0) * i // steps, y0 + (y1 - y0) * i // steps)
        time.sleep(0.05)


# ----------------------------------------------------------------- Replay --

def replay(rundir, session):
    """Same step sequence, but without a model: clicks via template matching.

    run.json is the trace of what actually happened, so loops appear
    unrolled and only the branches that ran are in it - the replay takes
    exactly that path again. Decisions (if, case, image_found, read_text,
    ask) and asserts are not re-evaluated. Steps that failed inside a 'try'
    are skipped; the run went on without them.
    """
    with open(os.path.join(rundir, "run.json")) as f:
        data = _english_keys(json.load(f))

    held = None
    for i, st in enumerate(data["steps"]):
        kind = st["type"]
        if st.get("success") is False:
            continue
        if kind == "key":
            session.key(st["key"])
            time.sleep(2)
        elif kind == "type":
            if "sequence" in st:
                for k, v in st["sequence"]:
                    session.key(v) if k == "key" else session.type_text(v)
                    time.sleep(0.1)
            elif isinstance(st["text"], list):
                send_sequence(session, st["text"])
            else:
                session.type_text(st["text"])
        elif kind == "click_needle" or (kind == "click" and "box" not in st
                                         and st.get("needle")):
            # click_needle: the needle itself, path relative to the
            # workspace; old click entries: crop from the run
            path = st["needle"]
            if kind == "click":
                path = os.path.join(rundir, path)
            cx, cy = _replay_find(session, path, st.get("threshold", 0.9),
                                  i, st.get("target") or st["needle"])
            session.click(cx, cy)
            time.sleep(1)
        elif kind in Run.POINTER_ACTIONS or kind == "wait_for":
            # crop from the run if there is one, else the fixed point
            if st.get("needle"):
                cx, cy = _replay_find(session, os.path.join(rundir, st["needle"]),
                                      0.9, i, st.get("target"))
            else:
                cx, cy = st["point"]
            if kind == "click":
                session.click(cx, cy)
            elif kind == "double_click":
                session.double_click(cx, cy)
            elif kind == "right_click":
                session.right_click(cx, cy)
            elif kind == "move_to":
                session.move(cx, cy)
            elif kind == "drag":
                session.mouse_down(cx, cy)
                held = (cx, cy)
            elif kind == "drop":
                _glide(session, held or (cx, cy), (cx, cy))
                session.mouse_up(cx, cy)
                held = None
            time.sleep(1 if kind != "wait_for" else 0)
        elif kind == "click_point":
            session.click(*st["point"])
            time.sleep(1)
        elif kind == "mouse":
            session.move(*st["point"])
            time.sleep(0.5)
        elif kind == "scroll":
            session.scroll(st["direction"], st.get("count", 1))
            time.sleep(0.5)
        elif kind == "key_down":
            session.key_down(st["key"])
        elif kind == "key_up":
            session.key_up(st["key"])
        elif kind == "wait":
            time.sleep(float(st["seconds"]))
        elif kind in ("log", "log_warning", "log_error"):
            print(log_marker(st["text"]))
        # assert steps are skipped in the replay - that would need either
        # the model or needles of their own.
    print("Replay finished.")


def _replay_find(session, path, threshold, i, what, timeout=20):
    needle = cv2.imread(path)
    if needle is None:
        raise AssertionError("step %d: needle not readable: %s" % (i, path))
    deadline = time.time() + timeout
    while True:
        score, cx, cy = match(session.screenshot(), needle)
        if score >= threshold:
            break
        if time.time() >= deadline:
            raise AssertionError("step %d: '%s' not found (score %.2f)"
                                 % (i, what, score))
        time.sleep(0.5)
    print("  step %d: hit %.2f at (%d, %d)" % (i, score, cx, cy))
    return cx, cy


# --------------------------------------------------------------- Selftest --

def selftest():
    """Checks scaling, box back-transformation and matching without hardware."""
    desk = np.full((1080, 1920, 3), 40, np.uint8)
    cv2.rectangle(desk, (200, 150), (900, 650), (30, 30, 30), -1)
    cv2.rectangle(desk, (200, 150), (900, 180), (90, 90, 90), -1)
    cv2.putText(desk, "X", (870, 175), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    true_box = [858, 155, 890, 178]

    small, scale = _shrink(desk)
    assert max(small.shape[:2]) == MAX_SIDE, small.shape
    print("shrink: %s -> %s (scale %.4f)" % (desk.shape[:2], small.shape[:2], scale))

    class FakeLocate(Vlm):
        def __init__(self):
            self.calls = 0
            self.seconds = 0.0

        def _chat(self, bgr, prompt):
            # the model answers normalised to 0..LOCATE_NORM - regardless
            # of how far _shrink scaled the image down
            h, w = bgr.shape[:2]
            s = min(1.0, MAX_SIDE / float(max(h, w)))
            x1, y1, x2, y2 = true_box
            box = [int(round(v * LOCATE_NORM / d))
                   for v, d in ((x1, w), (y1, h), (x2, w), (y2, h))]
            return {"found": True, "box": box, "conf": 0.88}, s

    hit = FakeLocate().locate(desk, "X button")
    cx = (hit["box"][0] + hit["box"][2]) // 2
    cy = (hit["box"][1] + hit["box"][3]) // 2
    want = ((true_box[0] + true_box[2]) // 2, (true_box[1] + true_box[3]) // 2)
    error = max(abs(cx - want[0]), abs(cy - want[1]))
    print("locate: click (%d,%d), want %s, off by %d px" % (cx, cy, want, error))
    assert error <= 2, "back-transformation inaccurate: %d px" % error

    print("json:", _extract_json('```json\n{"ok": true, "seen": "x"}\n```'))

    # old German files must stay readable
    old = _english_keys({"schritte": [{"typ": "assert", "erwartet": False,
                                       "prompt": "typ stays a value"}]})
    assert old == {"steps": [{"type": "assert", "expected": False,
                              "prompt": "typ stays a value"}]}, old
    print("keys:", old)

    crop = desk[151:182, 854:894]
    score, mx, my = match(desk, crop)
    print("match: score %.3f at (%d,%d)" % (score, mx, my))
    assert score > 0.99 and abs(mx - 874) <= 2 and abs(my - 166) <= 2

    # Needle filter: the own crop must be found again among the
    # candidates - that is the path that clicks in practice.
    npath = tmp_path("_selftest_needle.png")
    cv2.imwrite(npath, crop)
    try:
        boxes = candidate_boxes(desk)
        hits = needle_filter(desk, boxes, npath)
        assert hits, "needle filter doesn't find its own crop"
        bx, by, bw, bh = hits[0][0]
        nx, ny = bx + bw // 2, by + bh // 2
        print("needle: %d of %d candidates, best (%d,%d) score %.3f"
              % (len(hits), len(boxes), nx, ny, hits[0][1]))
        assert abs(nx - 874) <= 25 and abs(ny - 166) <= 25, \
            "needle filter points to (%d,%d) instead of the X" % (nx, ny)
        # click_needle: same crop, without a model, via Run
        class FakeSession:
            clicked = None

            def screenshot(self):
                return desk

            def click(self, x, y):
                self.clicked = (x, y)

        sess = FakeSession()
        outdir = tmp_path("_selftest_run")
        run = Run(sess, None, outdir)
        run.click_needle(npath, timeout=0)
        print("click_needle: click %s" % (sess.clicked,))
        assert abs(sess.clicked[0] - 874) <= 2 and abs(sess.clicked[1] - 166) <= 2

    finally:
        os.remove(npath)
        if os.path.isdir(tmp_path("_selftest_run")):
            import shutil
            shutil.rmtree(tmp_path("_selftest_run"))

    # both sit above runner - imported here, not at the top
    from .points import selftest as points_selftest
    points_selftest()
    from .commands import selftest as commands_selftest
    commands_selftest()
    try:
        from .pytest_plugin import selftest as plugin_selftest
    except ImportError:
        print("pytest plugin: skipped, pytest missing "
              "(.venv/bin/pip install pytest)")
    else:
        plugin_selftest()

    print("\nSelftest ok.")
