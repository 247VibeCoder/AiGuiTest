# aiguitest commands

The commands tests are written in: pointer actions, keys, waits and checks
on the desktop under test. The language around them is plain Python —
variables, `if`/`while`/`for`, `try`/`except` and functions.
[tests/test_xeyes.py](../tests/test_xeyes.py) is a complete example; the
API behind the commands is in [api.md](api.md).

```python
from aiguitest import *


def test_save_dialog():
    Click("FileMenu")
    Click(text="the 'Save as…' entry")
    WaitFor("SaveDialog", timeout=10)
    TypeText("report.txt", Enter)
    WaitWhile("SaveDialog")
    if ImageFound("OverwriteQuestion"):
        Click("YesButton")
    Assert("Is the title of the editor window 'report.txt'?")
```

`from aiguitest import *` brings the commands and the key constants, and
nothing else. The connection is not part of a test: it comes from `--vnc`
/ `config.json` and is made once per pytest session; programs are started
by typing into a terminal or a run dialog.

## Contents

- [Targets](#targets)
- [Commands](#commands)
- [Keys](#keys)
- [Variables, conditions and loops](#variables-conditions-and-loops)
- [Errors](#errors)
- [Shared steps](#shared-steps)
- [Result of a run](#result-of-a-run)
- [Remembered points and --nollm](#remembered-points-and---nollm)
- [Replay](#replay)

## Targets

Every pointer and wait command takes a target the same way:

| Written as | Meaning |
| --- | --- |
| `Click("SaveButton")` | image by name: `images/SaveButton.png` (`.png/.jpg/.jpeg/.bmp`, also the submodule's `images/`), found by template matching |
| `Click("image:close.png")` | the same, explicitly |
| `Click("text:Log in")` or `Click(text="the Log in button")` | found by the vision model; any description works: `text="the close button (X) of the Geany window"` |
| `Click(image="close", text="the X of the Geany window")` | template narrows the candidates, the model picks one |
| `Click((x, y))` | a fixed point |
| `Click(text="...", point=(x, y))` | the remembered point, checked by its reference image — see [Remembered points](#remembered-points-and---nollm) |
| `ReadText((x1, y1, x2, y2))` | a fixed rectangle |
| `threshold=0.8` | template threshold, default 0.9 |

Every command that takes a target **waits** for it: `timeout=` (seconds,
default 20). `timeout=0` is a single attempt. `ImageFound` defaults to a
single attempt; `ImageFound("Dialog", timeout=5)` waits up to 5 s.

What happens when the target doesn't show up depends on the command:
`Click`, `DoubleClick` and `RightClick` **skip** it (unless
`required=True`), `ImageFound` answers `False`, everything else fails the
test — see [Errors](#errors).

## Commands

The same list, with each command's description, is in the VS Code view
*AiGuiTest Commands*.

| Command | Effect |
| --- | --- |
| `Click(target)`, `DoubleClick(target)`, `RightClick(target)` | pointer action on a target; skipped if it doesn't show up (returns `None`), `required=True` fails instead |
| `MoveTo(target)` | move the pointer there; `MoveTo((0, 0))` moves it out of the way |
| `Drag(target)`, `Drop(target)` | `Drag` presses and holds, `Drop` moves there in steps and releases |
| `ClickMarks(prompt, needle=...)` | numbered candidates, the model picks a number |
| `ScrollWheelDown(count, target=...)`, `...Up/Left/Right` | `count` notches (default 1), over a target if given |
| `TypeText("text", Enter, ...)` | text and keys in order — see [Keys](#keys) |
| `KeyDown(ShiftKey)`, `KeyUp(ShiftKey)` | hold and release a key |
| `Wait(seconds)` | a hard pause |
| `WaitFor(target, timeout=20)` | until visible, returns `True`; fails if it doesn't appear — the assert for an image |
| `WaitWhile(target, timeout=60)` | until gone; fails if it stays. `WaitWhile(lambda: ...)` waits while a condition holds |
| `ImageFound(target, timeout=0)` | `True`/`False`, never fails — for `if` and `while` |
| `ReadText(target)` | the text of a target, read by the vision model |
| `Ask("question?")` | the model's yes/no as `True`/`False` |
| `Describe("question?")` | the model's answer in words, also shown at the end of the run; never fails. Default question: what is on the screen |
| `Assert("question?", expected=True)` | the model judges the screen, asks again until `timeout` |
| `Log(text)` | a marker in the output and in `run.json` |
| `LogWarning(text)` | noted, the test goes on and passes |
| `LogError(text)` | the test goes on, but **ends as failed**; a screenshot `error_NN.png` is taken |
| `CaptureScreen("name")` | named screenshot into the run folder |

`ReadText` takes a target as well: an image (the area it matched; with
`area=(dx1, dy1, dx2, dy2)` a rectangle relative to its centre — "the value
right of this label"), a rectangle, or `text="the total amount"` — the
model finds and reads in one step.

## Keys

`TypeText` takes text and keys in order. Keys are constants; modifiers
combine with what follows:

```python
TypeText(WindowsKey, "r")            # super-r: the run dialog
TypeText(ControlKey, "c")            # ctrl-c
TypeText(ControlKey, ShiftKey, "t")  # ctrl-shift-t
TypeText("admin123", Enter)          # text, then the enter key
TypeText("Enter")                    # the word "Enter" - a string is text
```

Key constants: `Enter`, `Return`, `Tab`, `Escape`, `Backspace`, `Delete`,
`Home`, `End`, `PageUp`, `PageDown`, `UpArrow` … `RightArrow`, `Space`,
`F1`–`F12`, and the modifiers `ControlKey`, `ShiftKey`, `AltKey`,
`WindowsKey`, `CommandKey`. Others by name: `Key("CapsLock")`,
`Key("F15")`.

## Variables, conditions and loops

Python's own:

```python
amount = ReadText("text:the total amount")
if float(amount) > 100:
    Log("large order: %s" % amount)

for name in ["UserA", "UserB", "UserC"]:
    TypeText(name, Enter)

while not ImageFound("ReadyButton"):
    Click("NextButton")
    Wait(1)

for i in range(30):
    if ImageFound("DoneButton"):
        Click("DoneButton")
        break
    Wait(2)
else:
    LogError("DoneButton did not appear")

status = ReadText("StatusField")
if status == "Success":
    Log("all good")
elif status in ("Failed", "Cancelled"):
    LogError("the system reports an error")
else:
    LogWarning("unknown status: %s" % status)
```

## Errors

`Click`, `DoubleClick` and `RightClick` skip a target that doesn't show
up - after waiting up to `timeout` s - and return `None`, so a cookie
banner or a "set as default browser" question that only comes sometimes
needs no `if`. A click the test depends on gets `required=True` and then
fails with `AssertionError`:

```python
Click("ebayCookie", timeout=5)              # skipped if not there
Click("LoginButton", required=True)         # fails if not there
```

Under `--nollm` a `text=` click that its remembered point can't confirm
fails anyway - skipping it would hide that it needed the model.

Other commands whose target doesn't show up, and an `Assert` that isn't
met, raise `AssertionError` too.

`try`/`except` catches the error in general:

```python
try:
    Click("FlakyElement", timeout=5)
except AssertionError as e:
    LogWarning("click failed: %s" % e)
    CaptureScreen("flaky")
```

**`WaitFor` or `ImageFound`?** `WaitFor` is an assert: it fails the test
when the image doesn't come, so it never reaches an `else`. To handle both
cases yourself, ask with `ImageFound` and a timeout:

```python
WaitFor("historyScreen", timeout=5)          # must be there, else the test fails

if ImageFound("historyScreen", timeout=5):   # the test goes on either way
    Log("History appears")
else:
    LogError("no History appears")           # the test ends as failed
    CaptureScreen("Error, no History")
```

`raise AssertionError("reason")` (or a plain `assert`) fails the test
when it isn't caught. A model endpoint that is down raises `VlmError`
instead — infrastructure, not a verdict, so `except AssertionError` doesn't
take it for a failed check.

## Shared steps

A step sequence several tests need is a plain function in a module under
`tests/` — any name that doesn't start with `test_`, e.g.
`tests/common.py`:

```python
# tests/common.py
from aiguitest import *

def open_terminal():
    Click(text="the Applications button", point=(60, 14))
    Click(text="the 'Terminal Emulator' entry", point=(77, 71))
    WaitFor(text="a terminal window with a shell prompt")
```

```python
# tests/test_xeyes.py
from aiguitest import *
from common import open_terminal

def test_xeyes():
    open_terminal()
    TypeText("xeyes &", Enter)
```

`from common import *` takes all of them. Parameters and return values
pass data in and out. pytest fixtures (`conftest.py`) work as usual, e.g.
for a login every test of a file needs. In VS Code, Ctrl+Enter (*Run
Line*) also works inside such a helper: it debugs a test that calls it up
to that line.

## Result of a run

Every step prints as it happens (`aiguitest-run` passes pytest's `-s`;
`--capture=fd` turns that off). Every test logs to
`runs/<timestamp>/<test>/`: a screenshot per step, needle crops and
`run.json` with every step and its outcome — a skipped click as
`"success": false, "required": false`. pytest reports
the result; with `LogError` entries the test fails at the end with the
list of them, and `aiguitest-run` exits with 1. `--junitxml=report.xml`
gives a report for CI.

## Remembered points and --nollm

```python
Click(text="the OK button", point=(412, 87))
```

The point is where the element was found; `images/points/` holds a
reference image of it (named after the description). On every run:

1. The reference image is looked for around the point by template —
   a hit is a click without the model, in milliseconds.
2. It matches elsewhere: the element moved, the new place is clicked.
3. It doesn't match any more, or there is no point or reference image yet:
   the model searches by the description, as without a point.

Points found anew (2 and 3) are **written back into the source** after
each test — `point=` is added or corrected, nothing else in the line
changes. A call inside a helper like `open_terminal()` is corrected in
`tests/common.py`, where it is written. Not written: a file edited during
the run, and a line that found different points in one run (a loop over
different elements). pytest lists what was written under *aiguitest:
remembered points*; git shows it in the diff.

`ClickMarks(prompt, needle=..., point=...)` works the same way.

**`--nollm`** is the strictly model-free run: a `text=` target is only
clicked by its point and reference image (1 and 2). If they don't match
or are missing, the test fails, saying which target to relearn — run it
once without `--nollm`. `Assert`, `Ask`, `Describe` and `ReadText` still ask the
model.

Change the description, and the element gets a new reference image on
the next run with the model. Delete `images/points/` to relearn
everything.

## Replay

`aiguitest-run --replay runs/<ts>/<test>` repeats the recorded path
without a model: loops appear unrolled and only the branches that ran are
in `run.json`, so the replay takes exactly that path again. Clicks are
found by template from the crops of the run; decisions (`if`,
`ImageFound`, `ReadText`, `Ask`, `Describe`) and asserts are not re-evaluated, a
failed attempt inside `try` and a skipped click are skipped.
