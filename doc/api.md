# aiguitest API

Reference for the `aiguitest` package. The user-facing side (writing and
running tests, setup) is in [README.md](../README.md), the commands with
examples in [commands.md](commands.md); the overall flow
is in [aiguitest-architektur.drawio](../aiguitest-architektur.drawio).

## Contents

- [Overview](#overview)
- [Examples](#examples)
- [config](#config)
- [marks](#marks)
- [vnc](#vnc)
- [vlm](#vlm)
- [runner](#runner)
- [keys](#keys)
- [commands](#commands)
- [points](#points)
- [pytest_plugin](#pytest_plugin)
- [File formats](#file-formats)
- [Error behaviour](#error-behaviour)

## Overview

The package is not installed. Import it from the project directory using
the venv interpreter (`.venv/bin/python`); other interpreters lack `cv2`.

```python
from aiguitest import VncSession, Vlm, Run
from aiguitest import *                    # what tests import: the commands
```

Every name can be imported directly from `aiguitest`. The modules form
layers, and dependencies only point downwards:

| Module | Contents | imports |
| --- | --- | --- |
| `config` | constants, paths, `tmp_path()`, `log_path()`, `test_path()` | nothing from the package |
| `keys` | `resolve_key`, `key_name`, `key_sequence`, `send_sequence` | nothing from the package |
| `marks` | `candidate_boxes`, `needle_filter`, `draw_marks`, `match` | nothing from the package |
| `points` | `reference_path`, `call_site`, `write_points` | `config` |
| `vnc` | `VncSession`, `ImageSource` | `config` |
| `vlm` | `Vlm`, `FakeVlm`, helpers | `config`, `marks` |
| `runner` | `Run`, `parse_target`, `run_log`, `replay`, `selftest` | everything below |
| `commands` | `Click`, `TypeText`, `WaitFor`, ... ; `bind`, `command_list` | `keys`, `runner` |
| `pytest_plugin` | fixtures, options, report hook | `config`, `runner`, `commands` |

`aiguitest/__init__.py` imports `commands` last and sets `__all__` to the
commands and key constants only: `from aiguitest import *` gives a test
exactly those, everything else is imported by name (`from aiguitest
import Run`). `pytest_plugin` is not imported by the package — pytest
loads it with `-p aiguitest.pytest_plugin`. `runner.selftest` imports
`commands` and the plugin only inside the function.

Images are always **BGR `numpy` arrays** as returned by `cv2.imread`.
Boxes come in two notations — don't mix them up:

- `(x, y, w, h)` — from `candidate_boxes`/`needle_filter`
- `[x1, y1, x2, y2]` — from `Vlm.locate`

`requests` and `vncdotool` are only imported inside the `Vlm` and
`VncSession` constructors. `marks`, `ImageSource`, `FakeVlm` and `selftest`
therefore work without those packages.

## Examples

### A test

A test is a pytest function; the plugin gives it a `Run` and binds the
commands to it:

```python
# tests/test_terminal.py
from aiguitest import *


def test_close_the_terminal():
    TypeText(ControlKey, AltKey, "t")
    WaitFor(text="a terminal window with a shell prompt")
    ClickMarks("the close button (X) of the terminal window",
               needle="images/close.png")
    Assert("Is a terminal window still visible?", expected=False, timeout=15)
```

```bash
./start.sh aiguitest-run terminal
```

### Without pytest

What the plugin does per test, by hand:

```python
from aiguitest import (Run, VncSession, Vlm, bind, unbind, TypeText, Assert,
                       ControlKey, AltKey)

session = VncSession("172.19.0.10::5901", "123456")
run = Run(session, Vlm(), "runs/manual")
prev = bind(run)
try:
    TypeText(ControlKey, AltKey, "t")
    Assert("Is a terminal window with a shell prompt open?")
except Exception:
    run.error_screenshot()
    raise
finally:
    unbind(prev)
    run.save()
    session.close()
```

Prompts may be in any language the model understands. The `Run` methods
below can be called directly too; the commands are a thin layer over them.

### Offline: a needle against a saved screenshot

No VNC, no model:

```python
import cv2
from aiguitest import (ImageSource, candidate_boxes, draw_marks,
                       needle_filter, tmp_path)

img = ImageSource("runs/20260912-104717/03_nach_dem_start.png").screenshot()
boxes = candidate_boxes(img)
hits = needle_filter(img, boxes, "images/close.png")
for (x, y, w, h), score in hits:
    print("centre (%d,%d) score %.3f" % (x + w // 2, y + h // 2, score))
cv2.imwrite(tmp_path("hits.png"), draw_marks(img, [b for b, _ in hits]))
```

## config

Values from `<project>/config.json` (optional) and the environment are read
**at import time**; the environment overrides the file. To change them from
code, set `os.environ` before the first `import aiguitest`, or pass the values
explicitly to the constructors. Format and keys: see the README, section
*Konfiguration*.

| Name | Source / value | Meaning |
| --- | --- | --- |
| `SERVER` | `VNC_SERVER`, else `vnc.server`, else `172.19.0.10::5901` | `host:N` = display N (port 5900+N), `host::P` = port P |
| `PASSWORD` | `VNC_PASSWORD`, else `vnc.password`, else `123456`; empty → `None` | VNC password |
| `VLM_BASE` | `VLM_BASE`, else `vlm.base`, else `http://ctollama.example.com:11434/v1` | OpenAI-compatible endpoint |
| `VLM_MODEL` | `VLM_MODEL`, else `vlm.model`, else `qwen3-vl:8b` | model name |
| `VLM_KEY` | `VLM_KEY`, else `vlm.key`, else `none` | bearer token |
| `VLM_VERIFY` | `VLM_VERIFY`, else `vlm.verify`, else `True` | certificate check: `True` (certifi bundle), path of a CA file, or `False` (off) |
| `MAX_SIDE` | `1280` | longest image side sent to the model |
| `LOCATE_NORM` | `1000` | scale of the boxes the model returns |
| `ASK_SCHEMA` | JSON template | answer format for `Vlm.ask` |
| `LOCATE_SCHEMA` | JSON template | answer format for `Vlm.locate` |
| `PROJECT` | path | directory of the tool (code, `start.sh`, `.venv`) |
| `WORKSPACE` | `AIGUITEST_HOME`, else `PROJECT` | directory of the tests: `tests/`, `images/`, `runs/`, `tmp/`, `log/`, `config.json` |
| `CONFIG_FILE` | `<workspace>/config.json` | optional configuration file |
| `TMPDIR` | `<workspace>/tmp` | location for intermediate images |
| `LOGDIR` | `<workspace>/log` | console output per run, not versioned |
| `TESTS` | `<workspace>/tests` | the pytest tests |

### `tmp_path(name)`

Returns `<workspace>/tmp/<name>` and creates `tmp/` if needed. Use it for
all intermediate images — never `/tmp`, never the project root.

### `log_path(name)`

Like `tmp_path`, for `<workspace>/log/<name>`.

### `test_path(name)`

Resolves a test name: `login` → `tests/test_login.py` (also if the file is
called `tests/login.py`), `test_login`/`test_login.py` the same; paths with
a directory and pytest node ids (`tests/x.py::test_a`) stay. Does not check
that the file exists. Used by `aiguitest-run`. `TESTS` is
`<workspace>/tests`.

## marks

Pure image analysis with OpenCV, no model involved.

### `candidate_boxes(img, min_side=10, max_side=260)`

Finds clickable candidates via edges (Canny, `RETR_LIST`).

- **Returns:** list of `(x, y, w, h)`, sorted row by row (40 px bands,
  then by `x`), **at most 60 entries**.
- Boxes whose top-left corner is within 6 px of an already accepted one
  are dropped.
- The cut at 60 is by image height, not importance: elements far down the
  screen may be missing.
- Rendered text produces candidates too (individual words).

### `needle_filter(img, boxes, needle_path, threshold=0.9, pad=6)`

Keeps only candidates whose centre matches an example image (needle).

- `needle_path` — path to the PNG, relative to the current directory.
- `threshold` — minimum score (`TM_CCOEFF_NORMED`, 0..1).
- `pad` — search window in pixels around the expected position.
- **Returns:** `[((x, y, w, h), score), ...]`, highest score first; empty
  if nothing matches.
- **Raises:** `ValueError` if the needle is unreadable or larger than the
  screenshot.

Needle and candidate are aligned by their **centres**, so the needle may
be larger than the candidate box.

### `draw_marks(img, boxes)`

Copy of `img` with red frames, numbered from 1, around each `(x, y, w, h)`
box. The number sits **inside** the top-left corner so that in dense lists it
is not attributed to the row above. If it would come closer than `GAP`
(6 px) to a number already placed, it moves to another corner of the box —
otherwise the model reads two adjacent numbers as one ('1' and '2' as '12').
The original is left untouched.

### `match(screen, needle, threshold=0.9)`

Template matching over the whole image.

- `needle` is an **image** (array), not a path.
- **Returns:** `(score, centre_x, centre_y)` of the best hit.
- `threshold` is **not evaluated**; the caller checks the score.
- Global maximum only: if several elements look identical, noise decides.
  Include surrounding context in the needle in that case.

## vnc

`VncSession` and `ImageSource` share the same methods. `Run` and `replay`
work with either, as long as only these methods are used.

| Method | `VncSession` | `ImageSource` |
| --- | --- | --- |
| `screenshot()` | fresh frame | copy of the loaded image |
| `key(k)` | send key | prints a note, does nothing |
| `type_text(text)` | type character by character | prints a note, does nothing |
| `click(x, y)` | move mouse, left button | prints a note, does nothing |
| `move(x, y)` | move mouse, no click | prints a note, does nothing |
| `double_click(x, y)` | two left presses 80 ms apart | prints a note, does nothing |
| `right_click(x, y)` | move, button 3 | prints a note, does nothing |
| `mouse_down(x, y, button=1)` / `mouse_up(...)` | move, press / release | prints a note, does nothing |
| `scroll(direction, count=1)` | `up/down/left/right`: buttons 4/5/6/7, one press per notch | prints a note, does nothing |
| `key_down(k)` / `key_up(k)` | hold / release a key | prints a note, does nothing |
| `close()` | disconnect | nothing |

### `VncSession(server=SERVER, password=PASSWORD)`

Connects in the constructor and waits 1 s for the first frame. vncdotool's
reactor thread is marked so a debugger (debugpy) does not suspend it with
the test — commands typed into the Debug Console keep working. If the
connection fails (wrong password, server down), the `vncdotool` exception
propagates out of the constructor.

- `screenshot(path=None)` — writes to `path` (default
  `tmp/_frame_<pid>.png`: one file per process, so the live view's bridge
  and a test run never read each other's half-written frame), reads it
  back and returns the image. Tries three times, 0.5 s apart;
  `RuntimeError` if it stays unreadable.
- `key(k)` — `k` is a **key name** from `vncdotool.keys.KEYMAP`
  (`enter`, `space`, `ctrl-alt-t`, `alt-f4`), not text. Unknown names end
  in a `TypeError` from `vncdotool`.
- `type_text(text, delay=0.05)` — one key press per character, upper-case
  letters sent as `shift-<lower>`.
- `click(x, y)` — moves the mouse, waits 0.2 s, left-clicks.
- `move(x, y)` — only moves the mouse.
- `double_click`, `right_click`, `mouse_down`, `mouse_up` — move first,
  wait 0.2 s, then act; `button` 1 = left, 3 = right.
- `scroll(direction, count)` — VNC knows no wheel events: the wheel is
  buttons 4 (up), 5 (down), 6 (left), 7 (right). `KeyError` for any other
  direction.
- `key_down(k)` / `key_up(k)` — vncdotool key names, as for `key`.
- `close()` — shuts down the `vncdotool` reactor. No new session is
  possible in the same process afterwards.

### `ImageSource(path)`

A static PNG instead of a desktop, for prompt tuning and offline tests.
Raises `SystemExit` if the image is unreadable. Here `screenshot()` takes
no path.

## vlm

### `Vlm(base=VLM_BASE, model=VLM_MODEL, key=VLM_KEY, verify=VLM_VERIFY)`

Client for `POST <base>/chat/completions` (OpenAI format). Every method
call is exactly one HTTP request.

Common to all calls:

- The image is first shrunk to `MAX_SIDE` via `_shrink`.
- `temperature=0`, `seed=1`, `max_tokens=4000`, timeout 180 s.
- Failed requests (endpoint unreachable, HTTP error, timeout) surface as
  `VlmError`, with the text naming the endpoint, the proxy and the result of
  a short `GET <base>/models`. It is no `AssertionError`, so `try` does not
  catch it.
- Counters: `calls` (number of calls), `seconds` (total model time).

`max_tokens` is deliberately high: qwen3-vl spends about 2000 tokens on
reasoning before answering, and with a tighter limit `content` comes back
empty.

#### `ask(bgr, question)`

Yes/no verdict on a screenshot. The model first describes what it sees and
then judges — strictly, `false` when in doubt.

- **Returns:** `{"ok": bool, "seen": str, "reason": str}`
- **Raises:** `AssertionError` if the answer contains no JSON.

#### `locate(bgr, target)`

Bounding box straight from the model.

- **Returns:** `{"box": [x1, y1, x2, y2], "conf": float}` in **full-image**
  coordinates (scaled back, clipped to the image), or `None` if not found
  or the box is empty.
- The model answers on a **0..1000** scale per axis (`LOCATE_NORM`), not
  in pixels; `locate` converts to the original size. Hit 5 of 6 targets;
  occasionally the answer is empty. `conf` is practically always `0.0`. For
  elements that look alike several times, use `Run.click_marks` with a
  needle.

#### `raw(bgr, question)`

Free-text answer as `str`, no JSON parsing.

### `FakeVlm()`

Offline test double with the same `ask`/`locate`/`raw` interface and the
same counters. Answers are derived from `candidate_boxes`:

- `ask` → `ok=True` as soon as there is at least one candidate.
- `locate` → first candidate with ±2 px random jitter, `conf=0.8`.
- `raw` → `'{"number": 1, "conf": 0.7}'` if the question contains
  "number", otherwise a descriptive sentence.

`FakeVlm` has **no** `_chat`. `Run.click_marks` needs it and therefore only
works with `Vlm` (or a subclass).

### Internal helpers

Exported because `runner` and `selftest` use them; not a stable API.

| Function | Effect |
| --- | --- |
| `_shrink(bgr)` | `(image, factor)`; shrinks to `MAX_SIDE`, never enlarges |
| `_to_data_url(bgr)` | PNG as `data:image/png;base64,...` |
| `_extract_json(text)` | JSON from model text, also inside ```` ```json ```` fences; `AssertionError` if none |

Coordinates from the model refer to the shrunk image and must be divided by
the factor from `_shrink`. Scaling anywhere else breaks this — `selftest()`
checks exactly this path.

## runner

### `Run(session, vlm, outdir)`

Performs actions, stores screenshots in `outdir` (created if needed) and
collects the log in `run.steps`.

Screenshot files are named `NN_<tag>.png`, where `NN` is the number of
steps logged so far. While polling, each attempt overwrites the same file,
so the last frame is kept.

#### `assert_visible(question, timeout=20, interval=2.0, expect=True)`

Calls `vlm.ask` until `ok == expect` or `timeout` seconds have passed.

- `expect=False` checks the opposite ("the window is gone now").
- Screenshot: `NN_assert.png`.
- **Raises:** `AssertionError` on timeout; the failed step is logged with
  `success: false` beforehand.

#### `click_marks(target, needle_path=None)`

The recommended way to click.

1. screenshot `NN_marks.png`, `candidate_boxes`
2. with `needle_path`: `needle_filter` narrows down (typically 60 → 2)
3. `draw_marks`, the model names a number
4. click the centre of that box, then pause 1 s

A single attempt, **no polling**. `AssertionError` if the needle is
unreadable, matches no candidate, or the model names an out-of-range
number.

#### `click_needle(needle_path, timeout=20, interval=2.0, threshold=0.9)`

Click by template, **without a model**. Searches the image with `match` in
one screenshot `NN_needle.png` per attempt, polls until `timeout`, clicks
the centre of the best hit at or above `threshold`, then pauses 1 s. Only
for targets that exist once — with several identical ones the global
maximum wins; use `click_marks` with a needle then. `AssertionError` if the
image is unreadable or nothing matches before `timeout` (logged with
`success: false` beforehand).

#### `click_point(x, y, target="")`

Clicks a stored position without searching; screenshot `NN_point.png`
before, 1 s pause after.

#### `mouse(x, y)`

Moves the mouse without clicking, 0.5 s pause after, logs
`{"type": "mouse", "point": [x, y]}`. Used for steps of type `mouse`, e.g.
to move the pointer out of the way before a needle or assert.

#### `click_element(target, timeout=20, interval=2.0, pad=4)`

Click via `vlm.locate`, polling until `timeout`. Crops the found box plus
`pad` as `NN_needle.png` — `replay` clicks from that later. An empty model
answer counts as "not found" and is retried. `AssertionError` if nothing is
found before `timeout`.

#### `log(text)`

Prints `log_marker(text)` and logs `{"type": "log", "text": ...}`. Used
for steps of type `log`.

#### `key(k, note="")`

Send a key, log it, then **pause 2 s**. `note` only goes into the log.
`k` goes through `resolve_key` first, so readable names work too
(`Enter`, `ControlKey-c`, `["WindowsKey", "r"]`); vncdotool names stay
unchanged. The log holds the translated name.

#### `type_sequence(seq)`

Text and keys in order: `[("text", "secret"), ("key", "enter")]`, logged
as one `type` entry with `sequence`. `TypeText` builds the list — it knows
which items are keys, so a plain `"Enter"` is typed as a word.

#### `type_text(text)`

Type text and log it, no pause afterwards. A **list** is a
`TypeText` sequence (`send_sequence`): key names in it are keys, modifiers
combine with the next item — `["admin", "Enter"]`, `["ControlKey", "c"]`.

#### `screenshot(name="screenshot")`

Named screenshot as a step of its own. The name is sanitised for the file
name (`NN_<name>.png`). **Returns:** full path.

#### `error_screenshot(name="error")`

Screenshot after an abort, saved as `<name>.png` without
a number and without a log entry. Never raises itself: if the screenshot
fails, that is printed and `None` returned. **Returns:** path or `None`.

#### Targets: `parse_target(t)` and `describe_target(spec)`

Module functions. `parse_target` turns a step's target into a dict with
the keys that apply: `image` (resolved via `image_path`), `text`, `point`,
`rect`, `threshold`, `area`.

| target | parsed |
| --- | --- |
| `"Name"`, `"image:close.png"` | `{"image": ".../images/Name.png"}` |
| `"text:the OK button"` | `{"text": "the OK button"}` |
| `[x, y]` / `[x1, y1, x2, y2]` | `{"point": ...}` / `{"rect": ...}` |
| `{image:, text:, point:, rect:, threshold:, area:}` | the same keys |

`SystemExit` if none of `image`, `text`, `point`, `rect` results.
`describe_target` gives the short form used in output and `run.json`.

How a target is found (one screenshot per attempt, `NN_find.png`):

| target | found by |
| --- | --- |
| `image` | `match` over the whole screen, score ≥ `threshold` (0.9); the box is the needle's size |
| `text` | `Vlm.locate`; an empty answer counts as not found |
| `image` + `text` | `_marks_box`: candidates sieved by the image, the model picks a number |
| `point` / `rect` | immediately |

An unreadable image raises `AssertionError` (with a hint that a
description needs `text:`), not "not found".

#### `act(action, target, timeout=20, interval=2.0, hint=None, required=True)`

`click`, `double_click`, `right_click`, `move_to`, `drag`, `drop` on a
target, polling until `timeout` (`0` = one attempt). The found area is cut
as `NN_needle.png` for `replay`. `drag` presses and holds the left button;
`drop` moves there in five steps and releases — `AssertionError` without a
preceding `drag`. Logged with `target`, `point`, `box`, `needle`,
`success` (and `score` for images); a target not found is logged with
`success: false` and raises `AssertionError`. **Returns** the log entry.

`required=False`: a target not found is logged with `success: false,
required: false`, prints `skipped: not there` and **returns** `None`
instead of raising — `replay` skips it like any failed step. Exception: a
`text` target under `strict` (`--nollm`) that its point can't confirm
always raises; skipping it would hide that it needed the model.
`Run.act` defaults to `required=True` (the bridge, direct `Run` users);
the click commands default to `False`.

`hint` — a remembered point for a `text` target: `{"point": [x, y] or None,
"site": call_site(), "strict": bool}`. The reference image
(`points.reference_path(text, run.points_dir)`) is matched around the
point, then on the whole screen (`via: "point"` / `"moved"` in the log);
without a match the model searches (`via: "model"`) and the crop becomes
the new reference image. `strict` (`--nollm`): no model — not found
instead. A new point, or one more than `points.TOLERANCE` px away, goes
into `run.point_updates` for `write_points`.

`click_marks(target, needle_path=None, hint=None)` takes the same `hint`.

#### `scroll(direction, count=1, target=None, timeout=20)`

`count` notches; with `target`, `move_to` it first. `SystemExit` for a
direction other than `up/down/left/right`.

#### `key_down(k)`, `key_up(k)`

Hold / release a key (`resolve_key` applies), logged.

#### `wait(seconds)`

Hard pause, logged.

#### `wait_for(target, timeout=20, interval=1.0)`

Until the target is visible; `AssertionError` after `timeout`. Stores a
crop like `act`, so `replay` waits for it too. Never returns false — for
an `if`/`else` use `image_found`.

#### `wait_while(target, timeout=60, interval=1.0)`

Until the target is gone; `AssertionError` if it is still there after
`timeout`.

#### `image_found(target, timeout=0, interval=1.0)`

`True`/`False`, never raises for "not there" (an unreadable image still
raises). One attempt by default.

#### `read_text(region, timeout=0, interval=1.0)`

Text in a region, read by the model (`Vlm.raw`). `region` is a target:
a rectangle, an image (its matched area, or `area: [dx1, dy1, dx2, dy2]`
relative to its centre), or `text:<description>` — then one model call
finds and reads. Crops lower than 64 px are enlarged before sending and
saved as `NN_read.png`. Quotes around the answer are stripped.
**Returns** `str`.

#### `ask(question)`

One `vlm.ask` on a fresh screenshot, as a value: **returns** `ok`. No
polling — that is what `assert_visible` is for.

#### `log_warning(text)`, `log_error(text)`

Both print and log. `log_warning` appends to `run.warnings`. `log_error`
appends to `run.errors` and takes `error_NN.png`; the run goes on, but
`run.failed` is then `True`, `run.json` says `"status": "failed"` and
`aiguitest-run` exits with 1 at the end.

#### `save()`

Writes `outdir/run.json` and returns the path. Can be called at any time,
including after a failure — belongs in a `finally`.

`server` in the log is `config.SERVER`, not the address `session` is
actually connected to. If the server was overridden via `--vnc`, the log
still shows the default.

### `run_log(name)`

Context manager: mirrors `sys.stdout` and `sys.stderr` into
`log/<timestamp>_<name>.log` as well (header: time and command line,
footer `# Ende <time>`) and yields a `RunLog` with `path` and
`note(text)` — `note` writes to the log only, not to the console. The
file is line-buffered, so it is complete even after an abort.
`aiguitest-run` runs the whole pytest session inside it. `fileno`/`isatty`
are passed through, so pytest still sees a terminal.

```python
with run_log("login") as log:
    pytest.main(["-p", "aiguitest.pytest_plugin", "tests/test_login.py"])
print(log.path)
```

### `log_marker(text)`

Returns `=== text ===` — the single form for markers from `log`,
`Run.log` and `replay`.

### `replay(rundir, session)`

Replays `rundir/run.json` **without a model**.

| logged step | in replay |
| --- | --- |
| `key` | sent, 2 s pause |
| `type` | typed (a `sequence`: text and keys in order) |
| `click` | find `NN_needle.png` via `match` (score ≥ 0.9, up to 20 s), click centre |
| `assert` | **skipped** (by design) |
| `click_marks` | **skipped** — the run stores no needle for it |
| `click_needle` | search the same needle (path relative to the project) like `click`, click; threshold from `threshold` (else 0.9) |
| `click_point` | click `point` |
| `mouse` | move mouse to `point` |
| `screenshot` | skipped |
| `log`, `log_warning`, `log_error` | marker printed |
| `double_click`, `right_click`, `move_to`, `drag`, `drop`, `wait_for` | find `needle` in the run dir like `click`, else use `point`; then the same action |
| `scroll`, `key_down`, `key_up`, `wait` | repeated |
| `image_found`, `read_text`, `ask` | skipped — the trace already holds the path that was taken |

`run.json` is a trace: loops appear unrolled, only branches that ran are
in it. Entries with `success: false` (a step that failed inside `try`)
are skipped. `AssertionError` if a click target is not found in time.
`aiguitest-run --replay runs/<ts>/<test>` calls it.

### `selftest()`

Checks, without VNC or model, against a synthetic desktop: `_shrink`, the
box back-transformation in `Vlm.locate`, `_extract_json`, `match` and
`needle_filter` — and, via `commands.selftest`, every command on a
synthetic desktop (targets, keys, `--nollm`, `LogError`, `replay` of the
result), and via `pytest_plugin.selftest` a pytest run of its own in an
offline workspace. Raises `AssertionError` on deviation. Run it after any
change to those functions:

```bash
./start.sh aiguitest-run --selftest
```

## keys

Key names (`ControlKey`, `Enter`) → vncdotool names. Imports nothing from the package.

- `key_name(name)` — `"ControlKey"` → `"ctrl"`, `"PageDown"` → `"pgdn"`,
  `"Enter"` → `"enter"`; `None` if it is no key name. Case, spaces and a
  trailing `Key` don't matter; single characters are never key names.
- `resolve_key(k)` — for `session.key`: key names and chords
  (`"ControlKey-c"`, `["WindowsKey", "r"]`) to `"ctrl-c"`, `"super-r"`.
  vncdotool names (`ctrl-alt-t`, `alt-f4`, `a`) come back unchanged.
- `key_sequence(items)` — a `TypeText` list to `[("text", s) | ("key", k)]`.
  Modifiers combine with the next item (the first character of a text, or
  a key); a modifier at the end is pressed alone; a string is plain text.
- `send_sequence(session, items, delay=0.1)` — presses/types that.

## commands

The commands tests are written in — a thin layer over `Run`. `from
aiguitest import *` brings the commands and the key constants.
Each command acts on the run `bind` set; the pytest plugin binds one per
test. [commands.md](commands.md) has examples, the docstrings the
details — they are also what the VS Code command list
shows.

**Targets** (every pointer and wait command): `target` — an image name,
`"image:<file>"`, `"text:<description>"` or `(x, y)` — or the keywords
`image=`, `text=` (both: template narrows, model picks), `point=`
(the remembered point of a `text=` target — see [points](#points)), `threshold=`.
A target and `image=`/`text=` together, or none at all, is a `TypeError`;
a malformed one a `ValueError`.

| Command | `Run` call |
| --- | --- |
| `Click`, `DoubleClick`, `RightClick` (target, `timeout=20`, `required=False`) | `run.act(action, target, timeout, hint, required)` → the log entry, or `None` if skipped; `required=True` fails instead |
| `MoveTo`, `Drag`, `Drop` (target, `timeout=20`) | `run.act(action, target, timeout, hint)` — fail if not found; `hint` for a `text` target: `point=`, the call site, `--nollm` |
| `ClickMarks(prompt, needle=None, point=None)` | `run.click_marks(prompt, needle, hint)` |
| `ScrollWheelDown/Up/Left/Right(count=1, target=...)` | `run.scroll(direction, count, target)` |
| `TypeText(*items)` | `run.type_sequence(...)` — `Key` items are keys, strings text, modifiers combine with what follows |
| `KeyDown(key)`, `KeyUp(key)` | `run.key_down`, `run.key_up` |
| `Wait(seconds)` | `run.wait` |
| `WaitFor(target, timeout=20)` | `run.wait_for` → `True`; fails if not visible — use `ImageFound(..., timeout=)` in `if` |
| `WaitWhile(target, timeout=60)` | `run.wait_while`; a callable: polls it until false |
| `ImageFound(target, timeout=0)` | `run.image_found` → `bool` |
| `ReadText(target, area=None, timeout=0)` | `run.read_text` → `str`; a 4-tuple is a rectangle |
| `Ask(question)` | `run.ask` → `bool` |
| `Describe(question="What is on the screen?")` | `run.describe` → `str` |
| `Assert(question, expected=True, timeout=20)` | `run.assert_visible` |
| `CaptureScreen(name)` | `run.screenshot` |
| `Log`, `LogWarning`, `LogError` (text) | `run.log`, `run.log_warning`, `run.log_error` |

**Keys:** `Key` is a `str` subclass that marks a key name: `Enter`, `Tab`,
`Escape`, `Backspace`, `Delete`, `Home`, `End`, `PageUp`, `PageDown`, the
arrows, `Space`, `F1`–`F12`, `ControlKey`, `ShiftKey`, `AltKey`,
`WindowsKey`, `CommandKey`; others as `Key("CapsLock")`. An unknown name
is a `ValueError`.

- `bind(run, nollm=False)` — make `run` the current one, returns the
  previous binding for `unbind(prev)`. `current()` returns it; without one
  the commands raise `RuntimeError`.
- `command_list()` — `[{name, group, signature, doc, help, snippet, ai}]` for
  every command, grouped by `GROUPS` (`doc`: first paragraph of the docstring,
  `help`: all of it; `ai`: `"always"` if it always asks the vision model,
  `"text"` if only for a `text=` target, else `""`); the bridge serves it to
  the editor.
- `run_line(code, file, line, g, l)` — runs a statement of a test file in
  a paused test (the editor's *Run Line* sends it to the Debug Console):
  compiled as `file` at `line` with its own indentation, executed in `g`
  and `l`; **returns** the value of a last expression, else `None`. Not
  in `__all__`.
- `selftest()` — part of `runner.selftest()`.

## points

Remembered points of `text=` targets. Imports only `config`.

- `POINTS_DIR` — `<workspace>/images/points`; `THRESHOLD` 0.9 (template
  score for "the same element"); `TOLERANCE` 3 px (closer is not written
  back).
- `reference_path(text, base=None)` — `images/points/<slug>_<hash6>.png`
  for a description.
- `call_site(skip_dir)` — the first frame outside the package: `{file,
  lineno, col, end_lineno, end_col}` (positions from Python 3.11+), or
  `None` outside the workspace.
- `write_points(updates, since=None, state=None)` — writes `point=(x, y)`
  into the calls: replaces an existing `point=`, else appends it after the
  last argument. Skips files changed after `since`, sites with two
  different points, and edits that would not parse. `state` (a dict kept
  across calls) allows writing after every test: each call edits the
  source as it was loaded again, and a file that is no longer what the
  last call wrote is left alone. **Returns** report lines.
- `LEARNED`, `site_key(site)` — points learned in this process, by call
  site; `commands` prefers them to the `point=` of the loaded code.
- `selftest()` — insert, replace, multi-line, non-ASCII, a clash.

## pytest_plugin

Loaded with `-p aiguitest.pytest_plugin` (`aiguitest-run` does that;
[pytest.ini](../pytest.ini) for plain `pytest`). `aiguitest-run` also
passes `--rootdir <workspace> --tb short` and `-s`, so every step prints
as it happens; a `-s` or `--capture=...` of its own on the command line
replaces that. The editor's *Debug* passes the same arguments.

| Fixture | Scope | |
| --- | --- | --- |
| `aiguitest_session` | session | `VncSession` from `--vnc`/`--vnc-password` or config; `ImageSource` with `--image`. No connection: `pytest.exit` with plain text, exit 2 |
| `aiguitest_vlm` | session | `Vlm()`, or `FakeVlm()` with `--fake-vlm` |
| `aiguitest_runs` | session | `--runs`, else `runs/<timestamp>` |
| `gui` | function, autouse | a `Run` in `<runs>/<test name>/`, bound for the commands (with `--nollm`); afterwards `run.save()`, and `error.png` if the test failed |

After every test (`gui` teardown) the `point_updates` of all runs so far
go to `points.write_points`, with one `state` for the session; so a
stopped debug session keeps what it learned. `pytest_terminal_summary`
lists them under *aiguitest: remembered points*.

The report hook fails a test that passed but logged `LogError` entries
(listing them), and shows a `VlmError` as its plain-text report instead of
a traceback. `pytest_report_header` names the VNC server or image.

## File formats

### `run.json` — log

Written by `Run.save`, read by `replay`. Contains **results**: points,
boxes, file names.

```json
{
  "server": "172.19.0.10::5901",
  "model": "qwen3-vl:8b",
  "status": "passed",
  "errors": [],
  "warnings": [],
  "steps": [ ... ]
}
```

| `type` | fields |
| --- | --- |
| `key` | `key`, `note` |
| `type` | `text`, or `sequence` (`[["text", ...], ["key", ...]]` from `TypeText`) |
| `assert` | `question`, `expected` (on success only), `result` (`ok`/`seen`/`reason`), `success` |
| `click` | `target`, `box`, `point`, `needle` (file in run dir), `offset`, `success` |
| `click_marks` | `target`, `point`, `needle` (path as given, or `null`), `success` |
| `click_needle` | `needle` (path as given), `threshold`, `point` (on success only), `score`, `success` |
| `click_point` | `target`, `point`, `success` |
| `mouse` | `point`, `success` |
| `screenshot` | `name`, `file`, `success` |
| `log`, `log_warning`, `log_error` | `text` |
| `double_click`, `right_click`, `move_to`, `drag`, `drop` (and `click` with a target) | `target`, `point`, `box`, `needle` (file in run dir or `null`), `score` (images), `success`; not found: `target`, `success: false`, `required` (`false` = skipped, the test went on) |
| `wait_for` | `target`, `timeout`, `point`, `needle`, `success` |
| `wait_while` | `target` or `condition`, `timeout`, `success` |
| `scroll` | `direction`, `count`, `success` |
| `key_down`, `key_up` | `key`, `success` |
| `wait` | `seconds` |
| `image_found` | `target`, `found`, `point` |
| `read_text` | `region`, `text` |
| `ask` | `question`, `result` |

`status` is `failed` as soon as a `LogError` happened; `errors` and
`warnings` hold their texts. Of the failed original steps, only `assert`
and `click_needle` are logged; the new actions and waits log `success:
false` before raising. If a click fails otherwise, it has no entry; the
state is shown by `error.png`.

### Run directory

```
runs/<timestamp>/<test>/
    00_assert.png       last frame of an assert
    01_marks.png        frame click_marks chose from
    02_locate.png       frame from click_element
    02_needle.png       crop used by replay
    03_nach_dem_start.png   named screenshot
    error.png           only after an abort
    run.json
```

### Old files with German keys

The keys used to be German (`schritte`, `typ`, `erwartet`, `passwort`,
`ziel`, `frage`, `ergebnis`, `erfolg`, `punkt`, `datei`, `modell`, `sehe`,
`grund`). `replay` translates them on read, so old run directories keep
working unchanged. If both spellings
are present, the English one wins. Only English is written.

The prompts and answer formats sent to the model (`ASK_SCHEMA` with
`seen`/`reason`, `LOCATE_SCHEMA` with `found`, `{"number": ...}` in
`click_marks`) are English too. The hit rates quoted in this reference were
measured with the earlier German prompts and keys; they still need to be
re-measured with the English ones.

## Error behaviour

| Exception | Raised by | Meaning |
| --- | --- | --- |
| `AssertionError` | `Run.*`, the commands, `replay`, `_extract_json`, `selftest` | test failure: wrong verdict, target not found (a click only with `required=True`, or a `text=` click under `--nollm`), unusable answer |
| `ValueError` | `needle_filter` | needle unreadable or too large (turned into `AssertionError` in `Run.click_marks`) |
| `SystemExit` | `parse_target`, `ImageSource` | unusable input; plain-text message |
| `TypeError`, `ValueError` | the commands | a malformed target or an unknown key - an error in the test, not a verdict |
| `RuntimeError` | commands without `bind` | no current run |
| `RuntimeError` | `VncSession.screenshot`, `_to_data_url` | image unreadable after three tries / not encodable |
| `VlmError` | `Vlm` | endpoint unreachable, HTTP error, timeout; a `RuntimeError` with a plain-text report |
| `vncdotool` exceptions | `VncSession()` | connection / authentication failed |

Catching `Exception` does not catch `SystemExit` — the commands
turn `parse_target`'s into `ValueError`, so a test only meets it from
`ImageSource`.
