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
                     log_path, script_path, tmp_path)
from .marks import candidate_boxes, draw_marks, match, needle_filter
from .vlm import Vlm, _extract_json, _shrink


def _slug(text):
    """File-name-safe name from free text."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text or "").strip("_") or "screenshot"


# Keys from the time the file formats were German. Versioned step files and
# old run folders must stay readable.
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


def _yaml():
    # lazy: --selftest and runs with old JSON files don't need PyYAML
    try:
        import yaml
    except ImportError:
        raise SystemExit("PyYAML missing: .venv/bin/pip install pyyaml")
    return yaml


def load_steps(path):
    """Read and check a step file.

    Returns (data, steps). Besides 'steps' the file may carry an optional
    'vnc' with server/password - then the connection lives where the test
    lives. Order: command line beats file beats environment.

    Step files are YAML; .json is still read, for older files.
    """
    with open(path) as f:
        text = f.read()
    fmt = "JSON" if path.lower().endswith(".json") else "YAML"
    try:
        if fmt == "JSON":
            data = json.loads(text)
        else:
            yaml = _yaml()
            try:
                data = yaml.safe_load(text)
            except yaml.YAMLError as e:
                raise ValueError(str(e))
    except ValueError as e:        # JSONDecodeError is a ValueError
        # Most common case: someone saved the workbench session transcript
        # as a step file. Then the raw parser line doesn't help.
        hint = ""
        if text.lstrip().startswith(">"):
            hint = ("\nThe file looks like a transcript of workbench "
                    "lines ('> key ...'). That is not a step file - use "
                    "'export' in the workbench.")
        raise SystemExit("%s is not valid %s: %s%s" % (path, fmt, e, hint))
    data = _english_keys(data)
    if not isinstance(data, dict) or "steps" not in data:
        raise SystemExit(
            "%s has no 'steps' field. Expected a 'steps:' block with a list "
            "of steps, optionally 'vnc:' before it." % path)
    return data, data["steps"]


def save_steps(path, data):
    """Write a step file as YAML: 2 spaces, 'type' first.

    Lists of numbers ('point') go on one line, everything else in block
    style. The order type, name, rest makes the file readable from the
    left: '- type: click' says right away what the step does.
    """
    yaml = _yaml()

    class Dumper(yaml.SafeDumper):
        def increase_indent(self, flow=False, indentless=False):
            # indent lists under 'steps:' instead of flush below it
            return super(Dumper, self).increase_indent(flow, False)

    def _list(dumper, seq):
        flow = all(isinstance(v, (int, float)) for v in seq)
        return dumper.represent_sequence("tag:yaml.org,2002:seq", seq,
                                         flow_style=flow)
    Dumper.add_representer(list, _list)

    out = dict(data)
    if isinstance(out.get("steps"), list):
        out["steps"] = [_step_order(st) for st in out["steps"]]
    text = yaml.dump(out, Dumper=Dumper, indent=2, sort_keys=False,
                     allow_unicode=True, default_flow_style=False,
                     width=4096)  # don't wrap long prompts
    with open(path, "w") as f:
        f.write(text)


def _step_order(st):
    if not isinstance(st, dict):
        return st
    first = [k for k in ("type", "name") if k in st]
    return dict([(k, st[k]) for k in first] +
                [(k, v) for k, v in st.items() if k not in first])


def log_marker(text):
    """One form for markers - the same in workbench, run and replay, so a
    search for '===' finds them in the log."""
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
    belong only in the log (such as the workbench input)."""

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
        # _Tee passes fileno/isatty through: input() then keeps using
        # readline, so the workbench keeps Tab and arrow keys.
        sys.stdout, sys.stderr = _Tee(out, f), _Tee(err, f)
        try:
            yield RunLog(path, f)
        finally:
            sys.stdout, sys.stderr = out, err
            f.write("\n# end %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))


class Run:
    """Executes the steps and writes the replay artefact."""

    def __init__(self, session, vlm, outdir):
        self.s, self.vlm, self.dir = session, vlm, outdir
        self.steps = []
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

    def click_marks(self, target, needle_path=None):
        """Number the candidates, the model picks a number, then click.

        With needle_path the candidates are sieved by template first - 60
        candidates typically become 2, and only then can the model solve it.
        """
        img = self._shot("marks")
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
        cx, cy = x + w // 2, y + h // 2
        print("  '%s' -> number %d, centre (%d,%d)" % (target, n, cx, cy))
        self.s.click(cx, cy)
        self.steps.append({"type": "click_marks", "target": target,
                           "point": [cx, cy], "needle": needle_path,
                           "success": True})
        time.sleep(1)

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
        self.s.key(k)
        self.steps.append({"type": "key", "key": k, "note": note})
        time.sleep(2)

    def type_text(self, text):
        self.s.type_text(text)
        self.steps.append({"type": "type", "text": text})

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

    def save(self):
        path = os.path.join(self.dir, "run.json")
        with open(path, "w") as f:
            json.dump({"server": SERVER, "model": VLM_MODEL,
                       "steps": self.steps}, f, indent=2,
                      ensure_ascii=False, default=str)
        return path


# ------------------------------------------------------------------ Steps --

def run_steps(run, steps, points=False, inside=()):
    """Executes the steps exported from the workbench.

    'steps' is the list from load_steps(), not the file path. Old German
    keys are still accepted here too, in case the list didn't come via
    load_steps().

    points=True is the fast run: click/click_marks click on their stored
    'point' instead of letting the model search. Asserts still ask the
    model - they are the actual test. click_needle searches by template as
    always.

    Returns the log entry from run.steps for each step - the workbench reads
    from it where a click actually went ('point').

    'use' runs another script at this point, with the same 'points' -
    unless the step carries 'mode: nollm' or 'mode: llm'. Its 'vnc' block
    doesn't count, the connection is already up. 'inside' are the scripts
    the run is currently in - against loops; the caller passes its own file.

    A per-step 'mode' on 'click' / 'click_marks' overrides the caller too:
    a click recorded with 'mode: nollm' clicks on the stored point even
    when the parent run is llm, and 'mode: llm' forces the model search
    even when the parent run is fast. Without a per-step mode the
    caller's 'points' still decides.
    """
    log = []
    for i, st in enumerate(_english_keys(steps)):
        kind = st["type"]
        # Per-step 'mode' beats the caller. The same rule a recorded
        # 'use' step already follows: a click recorded with mode 'nollm'
        # stays deterministic even when the parent run opted into llm,
        # and a click recorded with mode 'llm' uses the model even when
        # the parent run is fast. Without a per-step mode the caller's
        # 'points' decides - same as before.
        step_mode = st.get("mode")
        if step_mode not in (None, "nollm", "llm"):
            raise SystemExit("step %d: mode '%s' - allowed are nollm and llm"
                             % (i, step_mode))
        step_points = points if step_mode is None else step_mode == "nollm"
        print("%d) %s %s%s" % (i, kind, st.get("name", ""),
                               " [%s]" % step_mode if step_mode else ""))
        if step_points and kind in ("click", "click_marks"):
            if not st.get("point"):
                raise AssertionError(
                    "step %d (%s) has no 'point'. Record it again in the "
                    "workbench or run without nollm." % (i, kind))
            run.click_point(st["point"][0], st["point"][1], st["prompt"])
        elif kind == "key":
            run.key(st["key"])
        elif kind == "type":
            run.type_text(st["text"])
        elif kind == "assert":
            run.assert_visible(st["prompt"], expect=st.get("expected", True))
        elif kind == "click":
            run.click_element(st["prompt"])
        elif kind == "click_marks":
            run.click_marks(st["prompt"],
                            image_path(st["needle"]) if st.get("needle") else None)
        elif kind == "click_needle":
            run.click_needle(image_path(st["needle"]),
                             threshold=st.get("threshold", 0.9))
        elif kind == "mouse":
            run.mouse(st["point"][0], st["point"][1])
        elif kind == "screenshot":
            run.screenshot(st.get("name") or "screenshot")
        elif kind == "log":
            run.log(st["text"])
        elif kind == "use":
            path = os.path.abspath(script_path(st["script"]))
            inside = tuple(os.path.abspath(p) for p in inside)
            if path in inside:
                raise SystemExit("use loop: %s" % " -> ".join(
                    os.path.basename(p) for p in inside + (path,)))
            if not os.path.isfile(path):
                raise SystemExit("step %d: no step file %s"
                                 % (i, os.path.relpath(path)))
            # 'mode' in the step beats the run: that way a script with fixed
            # points can run fast even when the rest searches
            mode = st.get("mode")
            inner_points = points if mode is None else mode == "nollm"
            _, inner = load_steps(path)
            print(log_marker("use %s%s" % (st["script"],
                                           " (%s)" % mode if mode else "")))
            run_steps(run, inner, inner_points, inside + (path,))
            run.steps.append({"type": "use", "script": st["script"],
                              "success": True})
        else:
            raise SystemExit("unknown step type: %s" % kind)
        log.append(run.steps[-1])
    return log


def scenario(run):
    """Built-in example: open a terminal, start xeyes, close the terminal."""
    print("1) open terminal")
    # ctrl-alt-t is the XFCE default; ctrl-t opens nothing there.
    run.key("ctrl-alt-t", "open terminal")

    print("2) check: terminal visible")
    run.assert_visible("Is a terminal window with a shell prompt open?")

    print("3) start xeyes")
    run.type_text("xeyes &")
    run.key("enter", "submit command")
    time.sleep(2)

    print("4) check: xeyes running")
    run.assert_visible(
        "Is the program xeyes visible, i.e. a small window "
        "with two drawn eyes?")

    print("5) close terminal")
    run.click_element(
        "the close button (X) in the title bar of the TERMINAL window, "
        "not the one of the xeyes window")

    print("6) check: terminal closed, xeyes still there")
    run.assert_visible("Is a terminal window with a shell prompt still visible?",
                       expect=False, timeout=15)
    run.assert_visible("Is the xeyes window with the two eyes still visible?")


# ----------------------------------------------------------------- Replay --

def replay(rundir, session):
    """Same step sequence, but without a model: clicks via template matching."""
    with open(os.path.join(rundir, "run.json")) as f:
        data = _english_keys(json.load(f))

    for i, st in enumerate(data["steps"]):
        if st["type"] == "key":
            session.key(st["key"])
            time.sleep(2)
        elif st["type"] == "type":
            session.type_text(st["text"])
        elif st["type"] in ("click", "click_needle"):
            # click: crop from the run; click_needle: the needle itself,
            # path relative to the project as in the step file
            path = st["needle"]
            if st["type"] == "click":
                path = os.path.join(rundir, path)
            needle = cv2.imread(path)
            deadline = time.time() + 20
            while True:
                score, cx, cy = match(session.screenshot(), needle)
                # click_needle brings its threshold from the workbench
                if score >= st.get("threshold", 0.9):
                    break
                if time.time() >= deadline:
                    raise AssertionError(
                        "step %d: '%s' not found (score %.2f)"
                        % (i, st.get("target") or st["needle"], score))
                time.sleep(0.5)
            print("  step %d: hit %.2f at (%d, %d)" % (i, score, cx, cy))
            session.click(cx, cy)
            time.sleep(1)
        elif st["type"] == "click_point":
            session.click(*st["point"])
            time.sleep(1)
        elif st["type"] == "mouse":
            session.move(*st["point"])
            time.sleep(0.5)
        elif st["type"] == "log":
            print(log_marker(st["text"]))
        # assert steps are skipped in the replay - that would need either
        # the model or needles of their own.
    print("Replay finished.")


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

        # nollm: stored position instead of locate, the assert still runs
        from .vlm import FakeVlm
        run.vlm = FakeVlm()
        run_steps(run, [{"type": "assert", "prompt": "whatever"},
                        {"type": "click", "prompt": "X", "point": [57, 15]}],
                  points=True)
        assert sess.clicked == (57, 15), sess.clicked
        assert run.steps[-2]["type"] == "assert", run.steps[-2]

        # without nollm: the log entry carries the point for the workbench
        log = run_steps(run, [{"type": "click_needle", "needle": npath}])
        assert len(log) == 1 and log[0]["point"] == list(sess.clicked), log
        try:
            run_steps(run, [{"type": "click", "prompt": "X"}], points=True)
            raise RuntimeError("click without point should have failed")
        except AssertionError:
            pass
        print("nollm: click %s" % (sess.clicked,))
    finally:
        os.remove(npath)
        if os.path.isdir(tmp_path("_selftest_run")):
            import shutil
            shutil.rmtree(tmp_path("_selftest_run"))

    print("\nSelftest ok.")
