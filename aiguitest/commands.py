"""The commands tests are written in.

    from aiguitest import *

    def test_login():
        Click("PasswortFeld")
        TypeText("geheim", Enter)
        if not ImageFound("StartSeite", timeout=10):
            LogError("not logged in")

The commands act on the current run. The pytest plugin
(aiguitest.pytest_plugin) creates one per test and binds it; outside
pytest, bind(run) does the same. Control flow, variables and reuse are
plain Python.

Targets - the same for every pointer and wait command:

    Click("OkButton")                  image images/OkButton.png (template)
    Click("text:the OK button")        found by the vision model
    Click(text="the OK button")        the same
    Click(image="close", text="the X of the editor")
                                       template narrows, model picks
    Click((412, 87))                   a fixed point
    Click(text="...", point=(412, 87)) the remembered point: checked against
                                       images/points/ by template, the model
                                       only if the element changed; the run
                                       writes new points back (points.py)

Commands fail like an assert (AssertionError) when their target does not
show up in time; ImageFound and Ask only answer True/False. LogError lets
the test go on and fails it at the end.

Built on Run (runner.py) - this module adds names and argument handling,
no behaviour of its own. Imports nothing above runner.
"""

import os
import time

from .keys import _NAMES, MODIFIERS, key_name
from .points import LEARNED, call_site, site_key
from .runner import parse_target

__all__ = [
    # pointer
    "Click", "DoubleClick", "RightClick", "MoveTo", "Drag", "Drop",
    "ClickMarks",
    "ScrollWheelDown", "ScrollWheelUp", "ScrollWheelLeft", "ScrollWheelRight",
    # keyboard
    "TypeText", "KeyDown", "KeyUp",
    # waiting and queries
    "Wait", "WaitFor", "WaitWhile", "ImageFound", "ReadText", "Ask", "Describe",
    "Assert",
    # results
    "CaptureScreen", "Log", "LogWarning", "LogError",
    # keys
    "Key", "Enter", "Return", "Tab", "Escape", "Backspace", "Delete",
    "Home", "End", "PageUp", "PageDown", "UpArrow", "DownArrow",
    "LeftArrow", "RightArrow", "Space",
    "ControlKey", "ShiftKey", "AltKey", "WindowsKey", "CommandKey",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
]


# --------------------------------------------------------------- Run --

class _State:
    run = None
    nollm = False


def bind(run, nollm=False):
    """Make 'run' the one the commands act on; returns the previous one.

    nollm=True: a text target is only clicked where its remembered point
    and reference image say (Click(text=..., point=...), see points.py) -
    never by the model, so a run without a model either passes or says
    which point to relearn. Asserts and Ask still ask the model; they are
    the actual test.
    """
    prev = (_State.run, _State.nollm)
    _State.run, _State.nollm = run, bool(nollm)
    return prev


def unbind(prev):
    _State.run, _State.nollm = prev


def current():
    """The Run the commands act on."""
    # getattr, not _State.run: editors type the attribute as None (its only
    # value in the class body), so every command looked like it never returns
    # and the lines after a Click were greyed out as unreachable
    run = getattr(_State, "run", None)
    if run is None:
        raise RuntimeError("no test run: run the test with aiguitest-run or "
                           "pytest -p aiguitest.pytest_plugin, or bind(run)")
    return run


# ------------------------------------------------------------- Keys --

class Key(str):
    """A key name, as opposed to text: TypeText("Enter") types the word,
    TypeText(Enter) presses the key."""

    __slots__ = ()

    def __repr__(self):
        return self


Enter, Return, Tab, Escape = Key("Enter"), Key("Return"), Key("Tab"), Key("Escape")
Backspace, Delete, Space = Key("Backspace"), Key("Delete"), Key("Space")
Home, End, PageUp, PageDown = Key("Home"), Key("End"), Key("PageUp"), Key("PageDown")
UpArrow, DownArrow = Key("UpArrow"), Key("DownArrow")
LeftArrow, RightArrow = Key("LeftArrow"), Key("RightArrow")
ControlKey, ShiftKey, AltKey = Key("ControlKey"), Key("ShiftKey"), Key("AltKey")
WindowsKey, CommandKey = Key("WindowsKey"), Key("CommandKey")
F1, F2, F3, F4, F5, F6 = (Key("F%d" % i) for i in range(1, 7))
F7, F8, F9, F10, F11, F12 = (Key("F%d" % i) for i in range(7, 13))


_VNC_NAMES = set(_NAMES.values()) | set(MODIFIERS)


def _vnc_key(k):
    # a readable name (ControlKey), or vncdotool's own (ctrl, caplk)
    name = key_name(k) or (k if k in _VNC_NAMES else None)
    if name is None:
        raise ValueError("unknown key %r - use Enter, ControlKey, ... or a "
                         "vncdotool name like 'ctrl-alt-t'" % (k,))
    return name


# ---------------------------------------------------------- Targets --

def _target(target=None, image=None, text=None, point=None, threshold=None,
            area=None):
    """What Run.act and friends take, from the commands' arguments.

    Checked here, so a bad target is a plain error in the test and not
    the SystemExit parse_target gives the command line.
    """
    if target is not None and (image or text):
        raise TypeError("give a target, or image=/text= - not both")
    if target is None and not (image or text or point):
        raise TypeError("no target: give an image name, 'text:...', "
                        "(x, y), or image=/text=/point=")
    if target is not None:
        t = list(target) if isinstance(target, tuple) else target
        model = isinstance(t, str) and t.strip().lower().startswith("text:")
        if isinstance(t, str) and not model and (threshold is not None or
                                                 area is not None):
            t = {"image": t[6:] if t.lower().startswith("image:") else t}
            if threshold is not None:
                t["threshold"] = threshold
            if area is not None:
                t["area"] = list(area)
    else:
        t = {}
        if image:
            t["image"] = image
        if text:
            t["text"] = text
        if threshold is not None:
            t["threshold"] = threshold
        if area is not None:
            t["area"] = list(area)
        if not (image or text):
            t = list(point)
    try:
        parse_target(t)
    except SystemExit as e:
        raise ValueError(str(e.code))
    return t


def _hint(t, point):
    """For a target the model searches: the remembered point, where the
    call is written (so the point can be written back) and whether the
    model is off (--nollm). None for image targets and fixed points."""
    if isinstance(t, dict):
        text = t.get("text")
    else:
        text = isinstance(t, str) and t.strip().lower().startswith("text:")
    if not text:
        return None
    site = call_site(os.path.dirname(os.path.abspath(__file__)))
    # what this process learned beats the point in the loaded code
    point = LEARNED.get(site_key(site)) or point
    return {"point": [int(v) for v in point] if point is not None else None,
            "site": site, "strict": _State.nollm}


def _pointer(action, target, image, text, point, threshold, timeout,
             required=True):
    t = _target(target, image, text, point, threshold)
    return current().act(action, t, timeout=timeout, hint=_hint(t, point),
                         required=required)


def Click(target=None, image=None, text=None, point=None, threshold=None,
          timeout=20, required=False):
    """Click a target - waits up to 'timeout' s for it to show up.

    A target that doesn't show up is skipped (a cookie banner that only
    comes sometimes) and Click returns None, so 'if Click(...):' works;
    required=True fails the test instead.
    """
    return _pointer("click", target, image, text, point, threshold, timeout,
                    required)


def DoubleClick(target=None, image=None, text=None, point=None,
                threshold=None, timeout=20, required=False):
    """Double-click a target - skipped if it isn't there, unless required=True."""
    return _pointer("double_click", target, image, text, point, threshold,
                    timeout, required)


def RightClick(target=None, image=None, text=None, point=None,
               threshold=None, timeout=20, required=False):
    """Right-click a target - skipped if it isn't there, unless required=True."""
    return _pointer("right_click", target, image, text, point, threshold,
                    timeout, required)


def MoveTo(target=None, image=None, text=None, point=None, threshold=None,
           timeout=20):
    """Move the mouse onto a target, no click - MoveTo((0, 0)) moves it
    out of the way, so no hover effect spoils the next image search."""
    return _pointer("move_to", target, image, text, point, threshold, timeout)


def Drag(target=None, image=None, text=None, point=None, threshold=None,
         timeout=20):
    """Press the button on a target and hold it - Drop releases it."""
    return _pointer("drag", target, image, text, point, threshold, timeout)


def Drop(target=None, image=None, text=None, point=None, threshold=None,
         timeout=20):
    """Move to a target and release the button held by Drag."""
    return _pointer("drop", target, image, text, point, threshold, timeout)


def ClickMarks(prompt, needle=None, point=None):
    """Number the candidate elements, let the model pick one, click it.

    needle: an example image (images/close.png) that sieves the candidates
    first - needed when there are many. point: the remembered point, kept
    up to date by the run like that of Click(text=...).
    """
    return current().click_marks(prompt, needle, _hint({"text": prompt}, point))


def _scroll(direction, count, target, image, text, point, timeout):
    t = None
    if target is not None or image or text or point is not None:
        t = _target(target, image, text, point)
    current().scroll(direction, count, t, timeout)


def ScrollWheelDown(count=1, target=None, image=None, text=None, point=None,
                    timeout=20):
    """Scroll down 'count' notches, over a target if given."""
    _scroll("down", count, target, image, text, point, timeout)


def ScrollWheelUp(count=1, target=None, image=None, text=None, point=None,
                  timeout=20):
    """Scroll up 'count' notches, over a target if given."""
    _scroll("up", count, target, image, text, point, timeout)


def ScrollWheelLeft(count=1, target=None, image=None, text=None, point=None,
                    timeout=20):
    """Scroll left 'count' notches, over a target if given."""
    _scroll("left", count, target, image, text, point, timeout)


def ScrollWheelRight(count=1, target=None, image=None, text=None,
                     point=None, timeout=20):
    """Scroll right 'count' notches, over a target if given."""
    _scroll("right", count, target, image, text, point, timeout)


# ---------------------------------------------------------- Keyboard --

def TypeText(*items):
    """Type text and press keys, in order: TypeText("geheim", Enter).

    Modifiers combine with what follows: TypeText(ControlKey, "c") is
    ctrl-c, TypeText(ControlKey, ShiftKey, "t") ctrl-shift-t. Plain strings
    are always typed as text - TypeText("Enter") types the word.
    """
    seq, mods = [], []
    for item in items:
        if isinstance(item, Key):
            name = _vnc_key(item)
            if name in MODIFIERS:
                mods.append(name)
                continue
            seq.append(("key", "-".join(mods + [name])))
            mods = []
        elif isinstance(item, str):
            if mods and item:
                # a modifier applies to the first character only
                first, item = item[0], item[1:]
                keys = list(mods)
                if first.isupper():
                    keys.append("shift")
                    first = first.lower()
                seq.append(("key", "-".join(
                    keys + ["minus" if first == "-" else first])))
                mods = []
            if item:
                seq.append(("text", item))
        else:
            raise TypeError("TypeText takes text and keys, not %r" % (item,))
    if mods:
        seq.append(("key", "-".join(mods)))   # a modifier alone: WindowsKey
    current().type_sequence(seq)


def KeyDown(key):
    """Hold a key until KeyUp: KeyDown(ShiftKey)."""
    current().key_down(_vnc_key(key))


def KeyUp(key):
    """Release a key held by KeyDown."""
    current().key_up(_vnc_key(key))


# ------------------------------------------------ Waiting and queries --

def Wait(seconds):
    """A hard pause - WaitFor where something is awaited."""
    current().wait(seconds)


def WaitFor(target=None, image=None, text=None, threshold=None, timeout=20):
    """Wait until a target is visible; fails after 'timeout' s.

    Returns True, so 'if WaitFor(...)' doesn't silently take the else
    branch - but it never returns False: for if/else use ImageFound(...,
    timeout=...), which answers instead of failing.
    """
    current().wait_for(_target(target, image, text, None, threshold),
                       timeout=timeout)
    return True


def WaitWhile(target=None, image=None, text=None, threshold=None,
              timeout=60, interval=1.0):
    """Wait while a target is visible (a spinner, a dialog) - or, given a
    function, while it returns true: WaitWhile(lambda: n < 3)."""
    if callable(target):
        deadline = time.time() + float(timeout)
        while target():
            if time.time() >= deadline:
                raise AssertionError("WaitWhile: still true after %s s"
                                     % timeout)
            time.sleep(interval)
        return
    current().wait_while(_target(target, image, text, None, threshold),
                         timeout=timeout, interval=interval)


def ImageFound(target=None, image=None, text=None, threshold=None,
               timeout=0):
    """True if the target is visible (within 'timeout' s), else False -
    never fails, for use in if and while."""
    return current().image_found(_target(target, image, text, None,
                                         threshold), timeout=timeout)


def ReadText(target=None, image=None, text=None, area=None, timeout=0):
    """The text of a target, read by the vision model.

    ReadText("text:the total amount"), ReadText((x1, y1, x2, y2)), or an
    image plus area=(dx1, dy1, dx2, dy2) relative to its centre.
    """
    if isinstance(target, tuple) and len(target) == 4:
        t = list(target)
    else:
        t = _target(target, image, text, None, None, area)
    return current().read_text(t, timeout=timeout)


def Ask(question):
    """One yes/no judgement of the screen by the model - True or False."""
    return current().ask(question)


def Describe(question="What is on the screen?"):
    """The model's answer in words - the run's summary shows it, it never fails.

    answer = Describe() returns the text. Assert is what checks something.
    """
    return current().describe(question)


def Assert(question, expected=True, timeout=20):
    """The model judges a question about the screen; fails unless the
    answer is 'expected' within 'timeout' s (it asks again meanwhile)."""
    current().assert_visible(question, timeout=timeout, expect=expected)


# ----------------------------------------------------------- Results --

def CaptureScreen(name="screenshot"):
    """A named screenshot into the run folder."""
    return current().screenshot(name)


def Log(text):
    """A marker in the output and in run.json."""
    current().log(str(text))


def LogWarning(text):
    """A warning; the test goes on and passes."""
    current().log_warning(str(text))


def LogError(text):
    """An error; the test goes on but fails at the end."""
    current().log_error(str(text))


# ------------------------------------------------------------ Editor --

def run_line(code, file, line, g, l):
    """Run one statement of a test file in a paused test -> the value of
    its last expression (None for an assignment or a block).

    What the editor's Run Line sends to the Debug Console:
    run_line(<the statement>, <its file>, <its first line>, globals(),
    locals()). The code is compiled as that file at that line, with its
    own indentation - so a Click(text=...) finds its call site like the
    test itself would, and its point is learned and written back. 'l' is
    the frame's locals as the debugger hands them out; it saves them back
    into the frame afterwards, so assignments stick.
    """
    import ast
    lines = code.splitlines()
    indented = bool(lines) and lines[0][:1] in (" ", "\t")
    # an indented statement needs a block around it to compile; the
    # 'if 1:' sits on the line above, so line numbers and columns stay
    head = "\n" * (line - 2) + "if 1:\n" if indented else "\n" * (line - 1)
    tree = ast.parse(head + code, file)
    body = tree.body[0].body if indented else tree.body
    last = None
    if body and isinstance(body[-1], ast.Expr):
        last = ast.Expression(body.pop().value)
        if not body:
            body.append(ast.Pass(lineno=line, col_offset=0))
    exec(compile(tree, file, "exec"), g, l)
    return eval(compile(last, file, "eval"), g, l) if last else None


# ---------------------------------------------------------- Selftest --

# How the editor lists the commands; every function in exactly one group.
GROUPS = (
    ("Mouse", ("Click", "DoubleClick", "RightClick", "MoveTo", "Drag", "Drop",
               "ClickMarks", "ScrollWheelDown", "ScrollWheelUp",
               "ScrollWheelLeft", "ScrollWheelRight")),
    ("Keyboard", ("TypeText", "KeyDown", "KeyUp")),
    ("Wait and check", ("WaitFor", "WaitWhile", "Wait", "ImageFound",
                        "ReadText", "Ask", "Describe", "Assert")),
    ("Results", ("Log", "LogWarning", "LogError", "CaptureScreen")),
)

# The commands that always ask the vision model. The target commands ask it
# only for a text= target; command_list tells those by their parameters.
AI_ALWAYS = ("ClickMarks", "ReadText", "Ask", "Describe", "Assert")

# Placeholder of a command's first argument, by parameter name - the
# snippet the editor inserts: Click("${1:image_name}").
_FIRST = {
    "target": '"${1:image_name}"', "prompt": '"${1:description}"',
    "question": '"${1:question about the screen}"', "text": '"${1:text}"',
    "seconds": "${1:1}", "count": "${1:1}", "key": "${1:ShiftKey}",
    "items": '"${1:text}", ${2:Enter}', "name": '"${1:name}"',
}


def command_list():
    """The commands for the editor:
    [{name, group, signature, params, doc, help, snippet, ai}].

    doc is the first paragraph of the docstring (the list shows it), help
    the whole docstring (the description panel) - the docstrings above are
    the one place a command is described. ai is how the command uses the
    vision model: "always", "text" (only for a text= target) or "".
    params are the parameter names in order - the editor offers image names
    in a string that lands on target, image or needle.
    """
    import inspect
    out = []
    g = globals()
    for group, names in GROUPS:
        for name in names:
            f = g[name]
            sig = inspect.signature(f)
            full = inspect.getdoc(f) or ""
            doc = full.split("\n\n")[0].replace("\n", " ")
            first = next(iter(sig.parameters), None)
            arg = _FIRST.get(first, "")
            # image and text together: Log(text) is not a target
            targeted = "image" in sig.parameters and "text" in sig.parameters
            ai = ("always" if name in AI_ALWAYS else
                  "text" if targeted else "")
            out.append({"name": name, "group": group,
                        "signature": name + str(sig),
                        "params": list(sig.parameters), "doc": doc,
                        "help": full,
                        "snippet": "%s(%s)$0" % (name, arg),
                        "ai": ai})
    return out


def selftest():
    """The commands on a synthetic desktop - no VNC, no model."""
    import os
    import shutil

    import cv2
    import numpy as np

    from .config import tmp_path
    from .runner import Run, replay

    desk = np.full((600, 900, 3), 40, np.uint8)
    cv2.rectangle(desk, (100, 80), (700, 500), (30, 30, 30), -1)
    cv2.rectangle(desk, (100, 80), (700, 110), (90, 90, 90), -1)
    cv2.putText(desk, "X", (670, 104), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (255, 255, 255), 2)
    needle = tmp_path("_st_needle.png")
    cv2.imwrite(needle, desk[81:110, 660:694])
    want = (677, 95)

    screen = {"img": desk}

    class Rec:
        def __init__(self):
            self.calls = []

        def screenshot(self):
            return screen["img"]

        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return lambda *a: self.calls.append((name,) + tuple(a))

    class Vlm:
        calls, seconds = 0, 0.0
        located = 0

        def ask(self, img, q):
            return {"ok": "eyes" in q, "seen": "fake", "reason": "fake"}

        def raw(self, img, q):
            return ' "Erfolgreich" '

        def locate(self, img, target):
            self.located += 1
            if "the X" in target:             # where the X was drawn
                return {"box": [666, 85, 688, 106], "conf": 0.0}
            return None

    def near(p, q, d=3):
        return abs(p[0] - q[0]) <= d and abs(p[1] - q[1]) <= d

    real_sleep = time.sleep
    time.sleep = lambda s: None          # the commands pause - not here
    outdir = tmp_path("_st_run")
    sess = Rec()
    prev = bind(Run(sess, Vlm(), outdir))
    try:
        assert ImageFound(needle) and not ImageFound(needle, threshold=1.01)
        DoubleClick(needle)
        RightClick((10, 20))
        Drag((100, 100))
        Drop(image=needle)
        ScrollWheelDown(3)
        TypeText("geheim", Enter, ControlKey, "c", "Enter")
        KeyDown(ShiftKey)
        KeyUp(ShiftKey)
        assert ReadText(text="the status field") == "Erfolgreich"
        assert Ask("are the eyes there?") and not Ask("a dialog?")
        assert "Erfolgreich" in Describe()
        Assert("are the eyes there?")
        Assert("a dialog?", expected=False)
        WaitFor(needle, timeout=0)
        n = [0]
        WaitWhile(lambda: n.__setitem__(0, n[0] + 1) or n[0] < 3)
        assert n[0] == 3
        try:
            Click(needle, threshold=1.01, timeout=0, required=True)
            raise RuntimeError("a missing target must fail")
        except AssertionError:
            pass
        for bad in (dict(), dict(target="x", text="y"), dict(target=[1, 2, 3])):
            try:
                Click(**bad)
                raise RuntimeError("Click(%r) was accepted" % bad)
            except (TypeError, ValueError):
                pass
        LogWarning("just a warning")
        run = current()
        assert not run.errors and run.warnings == ["just a warning"]
        LogError("boom")
        assert run.failed

        calls = sess.calls
        names = [c[0] for c in calls]
        assert near([c for c in calls if c[0] == "double_click"][0][1:], want)
        assert ("right_click", 10, 20) in calls
        assert calls[names.index("mouse_down")][1:3] == (100, 100)
        assert near([c for c in calls if c[0] == "mouse_up"][0][1:3], want)
        assert ("scroll", "down", 3) in calls
        typed = [c for c in calls if c[0] in ("type_text", "key")]
        assert typed == [("type_text", "geheim"), ("key", "enter"),
                         ("key", "ctrl-c"), ("type_text", "Enter")], typed
        assert ("key_down", "shift") in calls and ("key_up", "shift") in calls
        print("commands: %d actions, %d steps logged"
              % (len(calls), len(run.steps)))

        # remembered points: the model once, then the reference image
        global call_site
        real_site = call_site
        call_site = lambda skip: {"file": "test_x.py", "lineno": 7}
        run.points_dir = tmp_path("_st_points")
        shutil.rmtree(run.points_dir, ignore_errors=True)
        vlm = run.vlm
        try:
            Click(text="the X")                       # no point yet
            assert vlm.located == 1, vlm.located
            up = run.point_updates[-1]
            assert up["old"] is None and near(up["point"], want), up
            p = up["point"]
            n = len(run.point_updates)
            Click(text="the X", point=p)              # checked, no model
            assert vlm.located == 1 and len(run.point_updates) == n
            assert near(sess.calls[-1][1:], want), sess.calls[-1]
            screen["img"] = np.roll(desk, 30, axis=1)   # the window moved
            Click(text="the X", point=p)
            assert vlm.located == 1, "a moved element needs no model"
            assert near(run.point_updates[-1]["point"], (want[0] + 30, want[1]))
            gone = desk.copy()
            cv2.rectangle(gone, (660, 81), (694, 110), (90, 90, 90), -1)
            screen["img"] = gone                      # the element changed
            bind(run, nollm=True)
            try:
                Click(text="the X", point=p, timeout=0)
                raise RuntimeError("--nollm must not fall back to the model")
            except AssertionError as e:
                assert "--nollm" in str(e) and vlm.located == 1, e
            try:
                ClickMarks("the X", point=None)
                raise RuntimeError("--nollm without a point must fail")
            except AssertionError:
                pass
            bind(run, nollm=False)
            Click(text="the X", point=p, timeout=0)   # model, new reference
            assert vlm.located == 2, vlm.located
            screen["img"] = desk
            bind(run, nollm=True)
            Click(text="the X", point=p, timeout=0)   # model-free, passes
            assert vlm.located == 2
            bind(run, nollm=False)
            print("remembered points: model 2x for 5 clicks, moved, strict")
        finally:
            call_site = real_site
            LEARNED.clear()
            screen["img"] = desk
            shutil.rmtree(run.points_dir, ignore_errors=True)

        run.save()
        sess2 = Rec()
        replay(outdir, sess2)
        got = [c[0] for c in sess2.calls]
        assert got.count("double_click") == 1 and "mouse_up" in got, got
        print("replay: %d actions" % len(sess2.calls))
        listed = [c["name"] for c in command_list()]
        funcs = [n for n in __all__ if callable(globals()[n])
                 and not isinstance(globals()[n], type)]
        assert sorted(listed) == sorted(funcs), set(listed) ^ set(funcs)
        ai = dict((c["name"], c["ai"]) for c in command_list())
        assert set(AI_ALWAYS) <= set(ai), set(AI_ALWAYS) - set(ai)
        assert (ai["Ask"], ai["Click"], ai["WaitFor"], ai["ScrollWheelUp"],
                ai["Log"], ai["TypeText"]) == ("always", "text", "text",
                                               "text", "", ""), ai
    finally:
        unbind(prev)
        time.sleep = real_sleep
        os.remove(needle)
        shutil.rmtree(outdir, ignore_errors=True)
