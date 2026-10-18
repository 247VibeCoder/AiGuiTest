# aiguitest API

Reference for the `aiguitest` package. The user-facing side (CLIs,
workbench, setup) is in [README.md](../README.md); the overall flow
is in [aiguitest-architektur.drawio](../aiguitest-architektur.drawio).

## Contents

- [Overview](#overview)
- [Examples](#examples)
- [config](#config)
- [marks](#marks)
- [vnc](#vnc)
- [vlm](#vlm)
- [runner](#runner)
- [File formats](#file-formats)
- [Error behaviour](#error-behaviour)

## Overview

The package is not installed. Import it from the project directory using
the venv interpreter (`.venv/bin/python`); other interpreters lack `cv2`.

```python
from aiguitest import VncSession, Vlm, Run, run_steps, load_steps
```

Every name can be imported directly from `aiguitest`. The modules form
layers, and dependencies only point downwards:

| Module | Contents | imports |
| --- | --- | --- |
| `config` | constants, paths, `tmp_path()`, `log_path()`, `script_path()` | nothing from the package |
| `marks` | `candidate_boxes`, `needle_filter`, `draw_marks`, `match` | nothing from the package |
| `vnc` | `VncSession`, `ImageSource` | `config` |
| `vlm` | `Vlm`, `FakeVlm`, helpers | `config`, `marks` |
| `runner` | `Run`, `load_steps`, `run_steps`, `scenario`, `replay`, `selftest` | everything below |

Images are always **BGR `numpy` arrays** as returned by `cv2.imread`.
Boxes come in two notations — don't mix them up:

- `(x, y, w, h)` — from `candidate_boxes`/`needle_filter`
- `[x1, y1, x2, y2]` — from `Vlm.locate`

`requests` and `vncdotool` are only imported inside the `Vlm` and
`VncSession` constructors. `marks`, `ImageSource`, `FakeVlm` and `selftest`
therefore work without those packages.

## Examples

### A test in Python instead of JSON

```python
from aiguitest import Run, VncSession, Vlm

session = VncSession("172.19.0.10::5901", "123456")
run = Run(session, Vlm(), "runs/manual")
try:
    run.key("ctrl-alt-t")
    run.assert_visible("Is a terminal window with a shell prompt open?")
    run.click_marks("the close button (X) of the terminal window",
                    "images/close.png")
    run.assert_visible("Is a terminal window still visible?",
                       expect=False, timeout=15)
except Exception:
    run.error_screenshot()
    raise
finally:
    run.save()
    session.close()
```

Prompts may be in any language the model understands.

### Running a step file

This is essentially what `aiguitest-run --steps` does:

```python
from aiguitest import Run, VncSession, Vlm, load_steps, run_steps

data, steps = load_steps("scripts/test1.yaml")
vnc = data.get("vnc") or {}
session = VncSession(vnc.get("server", "172.19.0.10::5901"), vnc.get("password"))
run = Run(session, Vlm(), "runs/test1")
try:
    run_steps(run, steps)             # the list, not the path
finally:
    run.save()
    session.close()
```

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
| `VLM_BASE` | `VLM_BASE`, else `vlm.base`, else `http://ctollama.home.arpa:11434/v1` | OpenAI-compatible endpoint |
| `VLM_MODEL` | `VLM_MODEL`, else `vlm.model`, else `qwen3-vl:8b` | model name |
| `VLM_KEY` | `VLM_KEY`, else `vlm.key`, else `none` | bearer token |
| `MAX_SIDE` | `1280` | longest image side sent to the model |
| `LOCATE_NORM` | `1000` | scale of the boxes the model returns |
| `ASK_SCHEMA` | JSON template | answer format for `Vlm.ask` |
| `LOCATE_SCHEMA` | JSON template | answer format for `Vlm.locate` |
| `PROJECT` | path | directory of the tool (code, `start.sh`, `.venv`) |
| `WORKSPACE` | `AIGUITEST_HOME`, else `PROJECT` | directory of the tests: `scripts/`, `images/`, `runs/`, `tmp/`, `log/`, `config.json` |
| `CONFIG_FILE` | `<workspace>/config.json` | optional configuration file |
| `TMPDIR` | `<workspace>/tmp` | location for intermediate images |
| `LOGDIR` | `<workspace>/log` | console output per run, not versioned |
| `SCRIPTS` | `<workspace>/scripts` | step files |

### `tmp_path(name)`

Returns `<workspace>/tmp/<name>` and creates `tmp/` if needed. Use it for
all intermediate images — never `/tmp`, never the project root.

### `log_path(name)`

Like `tmp_path`, for `<workspace>/log/<name>`.

### `script_path(name)`

Resolves a script name: `openTerminal` → `scripts/openTerminal.yaml`
(without an extension the first existing one from `SCRIPT_EXT` =
`.yaml`, `.yml`, `.json` wins, else `.yaml`), `name.yaml` without a
directory → `scripts/name.yaml`, paths with a directory stay. Does not
check that the file exists. Used by `use`/`export` and `aiguitest-run`.

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
| `close()` | disconnect | nothing |

### `VncSession(server=SERVER, password=PASSWORD)`

Connects in the constructor and waits 1 s for the first frame. If the
connection fails (wrong password, server down), the `vncdotool` exception
propagates out of the constructor.

- `screenshot(path=None)` — writes to `path` (default `tmp/_frame.png`),
  reads the file back and returns the image. `RuntimeError` if unreadable.
- `key(k)` — `k` is a **key name** from `vncdotool.keys.KEYMAP`
  (`enter`, `space`, `ctrl-alt-t`, `alt-f4`), not text. Unknown names end
  in a `TypeError` from `vncdotool`.
- `type_text(text, delay=0.05)` — one key press per character, upper-case
  letters sent as `shift-<lower>`.
- `click(x, y)` — moves the mouse, waits 0.2 s, left-clicks.
- `move(x, y)` — only moves the mouse.
- `close()` — shuts down the `vncdotool` reactor. No new session is
  possible in the same process afterwards.

### `ImageSource(path)`

A static PNG instead of a desktop, for prompt tuning and offline tests.
Raises `SystemExit` if the image is unreadable. Here `screenshot()` takes
no path.

## vlm

### `Vlm(base=VLM_BASE, model=VLM_MODEL, key=VLM_KEY)`

Client for `POST <base>/chat/completions` (OpenAI format). Every method
call is exactly one HTTP request.

Common to all calls:

- The image is first shrunk to `MAX_SIDE` via `_shrink`.
- `temperature=0`, `seed=1`, `max_tokens=4000`, timeout 180 s.
- HTTP errors surface as `requests.HTTPError`.
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

### `load_steps(path)`

Reads a step file.

- **Format:** YAML; files ending in `.json` are read as JSON (older step
  files).
- **Returns:** `(data, steps)` — the whole document and the list under
  `steps`.
- **Raises:** `SystemExit` with a plain-text message on invalid YAML/JSON
  (with a hint if the file is a workbench transcript), a missing `steps`,
  or missing PyYAML.
- `load_steps` does not evaluate the `vnc` block; that is the caller's job.

### `save_steps(path, data)`

Writes `data` as a YAML step file: 2-space indent, the list under `steps:`
indented, `type` and `name` first in each step, number lists (`point`) on
one line, long prompts not wrapped. Comments in an existing file are lost.

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
before, 1 s pause after. Used by `run_steps(..., points=True)`.

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

#### `type_text(text)`

Type text and log it, no pause afterwards.

#### `screenshot(name="screenshot")`

Named screenshot as a step of its own. The name is sanitised for the file
name (`NN_<name>.png`). **Returns:** full path.

#### `error_screenshot(name="error")`

Screenshot after an abort, saved as `<name>.png` without
a number and without a log entry. Never raises itself: if the screenshot
fails, that is printed and `None` returned. **Returns:** path or `None`.

#### `save()`

Writes `outdir/run.json` and returns the path. Can be called at any time,
including after a failure — belongs in a `finally`.

`server` in the log is `config.SERVER`, not the address `session` is
actually connected to. If the server was overridden via the file or
`--server`, the log still shows the default.

### `run_steps(run, steps, points=False, inside=())`

Executes a step list from `load_steps` in order on `run`. With
`points=True` (`aiguitest-run --nollm`), `click` and `click_marks` go to
`run.click_point(*st["point"], st["prompt"])` instead; a missing `point`
raises `AssertionError`. Assertions ask the model either way. **Returns**
the log entry from `run.steps` for each step (see `run.json`), so clicks
include the actual `point`. `use` loads the named script via `script_path`
and runs it with the same `points` — unless the step carries `mode: nollm`
or `mode: llm`, which then applies to that script; `inside` lists the files the run is
already in — callers pass their own, a loop ends in `SystemExit`. Mapping
to `Run` methods:

| `type` | call |
| --- | --- |
| `key` | `run.key(st["key"])` |
| `type` | `run.type_text(st["text"])` |
| `assert` | `run.assert_visible(st["prompt"], expect=st.get("expected", True))` |
| `click` | `run.click_element(st["prompt"])` |
| `click_marks` | `run.click_marks(st["prompt"], st.get("needle"))` |
| `click_needle` | `run.click_needle(st["needle"], threshold=st.get("threshold", 0.9))` |
| `screenshot` | `run.screenshot(st.get("name") or "screenshot")` |
| `mouse` | `run.mouse(st["point"][0], st["point"][1])` |
| `use` | `run_steps(run, <steps from script_path(st["script"])>, points, ...)` |
| `log` | `run.log(st["text"])` |

Timeouts and intervals are the method defaults and cannot be set from the
file. Unknown `type` → `SystemExit`. Step failures are not caught; they
propagate to the caller.

### `run_log(name)`

Context manager: mirrors `sys.stdout` and `sys.stderr` into
`log/<timestamp>_<name>.log` as well (header: time and command line,
footer `# Ende <time>`) and yields a `RunLog` with `path` and
`note(text)` — `note` writes to the log only, not to the console (the
workbench stores its inputs that way). The file is line-buffered, so it is
complete even after an abort. `aiguitest-run` runs inside it per run, the
workbench per session (`workbench`). `fileno`/`isatty` are passed through,
so `input()` keeps using readline.

```python
with run_log("openTerminal") as log:
    run_steps(run, steps)
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
| `type` | typed |
| `click` | find `NN_needle.png` via `match` (score ≥ 0.9, up to 20 s), click centre |
| `assert` | **skipped** (by design) |
| `click_marks` | **skipped** — the run stores no needle for it |
| `click_needle` | search the same needle (path relative to the project) like `click`, click; threshold from `threshold` (else 0.9) |
| `click_point` | click `point` |
| `mouse` | move mouse to `point` |
| `use` | marker only — the script's steps precede it individually in `run.json` |
| `screenshot` | skipped |
| `log` | marker printed |

`AssertionError` if a click target is not found in time.

### `scenario(run)`

Built-in XFCE example: open a terminal, start `xeyes &`, close the terminal
via its ×, verify only xeyes remains. Runs when `aiguitest-run` is started
without a step file.

### `selftest()`

Checks, without VNC or model, against a synthetic desktop: `_shrink`, the
box back-transformation in `Vlm.locate`, `_extract_json`, `match` and
`needle_filter`. Raises `AssertionError` on deviation. Run it after any
change to those functions:

```bash
./start.sh aiguitest-run --selftest
```

## File formats

### `steps.yaml` — input

Written by the workbench (`export`), read by `load_steps`. Contains
**prompts**, no coordinates.

```yaml
name: Start Geany and close it again
vnc:
  server: 172.19.0.10::5901
  password: '123456'
steps:
  - type: use
    script: openTerminal
    mode: nollm
  - type: type
    text: geany &
  - type: key
    name: submit
    key: enter
  - type: screenshot
    name: after_start
  - type: assert
    prompt: Is Geany open?
  - type: mouse
    point: [0, 0]
  - type: click_needle
    needle: images/close.png
    threshold: 0.8
  - type: assert
    prompt: Is Geany still open?
    expected: false
```

`name` (top level and per step) and `vnc` are optional. Fields per step
type:

| `type` | fields |
| --- | --- |
| `key` | `key` — key name from `vncdotool.keys.KEYMAP` |
| `type` | `text` |
| `screenshot` | `name` |
| `log` | `text` |
| `assert` | `prompt`, `expected` (default `true`) |
| `click` | `prompt`, `point` (only used with `points=True`) |
| `click_marks` | `prompt`, `needle`, `point` |
| `click_needle` | `needle`, `threshold` (default 0.9) |
| `mouse` | `point` |
| `use` | `script` (name as for `script_path`), `mode` (`nollm`/`llm`, default: like the run) |

### `run.json` — log

Written by `Run.save`, read by `replay`. Contains **results**: points,
boxes, file names.

```json
{
  "server": "172.19.0.10::5901",
  "model": "qwen3-vl:8b",
  "steps": [ ... ]
}
```

| `type` | fields |
| --- | --- |
| `key` | `key`, `note` |
| `type` | `text` |
| `assert` | `question`, `expected` (on success only), `result` (`ok`/`seen`/`reason`), `success` |
| `click` | `target`, `box`, `point`, `needle` (file in run dir), `offset`, `success` |
| `click_marks` | `target`, `point`, `needle` (path as given, or `null`), `success` |
| `click_needle` | `needle` (path as given), `threshold`, `point` (on success only), `score`, `success` |
| `click_point` | `target`, `point`, `success` |
| `mouse` | `point`, `success` |
| `use` | `script`, `success` (after the script's entries) |
| `screenshot` | `name`, `file`, `success` |
| `log` | `text` |

Of the failed steps, only `assert` and `click_needle` are logged. If a click fails, it has no
entry; the state is shown by `error.png`.

### Run directory

```
runs/<timestamp>/
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
`grund`). `load_steps`, `run_steps` and `replay` translate them on read, so
old step files and run directories keep working unchanged. If both spellings
are present, the English one wins. Only English is written.

The prompts and answer formats sent to the model (`ASK_SCHEMA` with
`seen`/`reason`, `LOCATE_SCHEMA` with `found`, `{"number": ...}` in
`click_marks`) are English too. The hit rates quoted in this reference were
measured with the earlier German prompts and keys; they still need to be
re-measured with the English ones.

## Error behaviour

| Exception | Raised by | Meaning |
| --- | --- | --- |
| `AssertionError` | `Run.*`, `replay`, `_extract_json`, `selftest` | test failure: wrong verdict, target not found, unusable answer |
| `ValueError` | `needle_filter` | needle unreadable or too large (turned into `AssertionError` in `Run.click_marks`) |
| `SystemExit` | `load_steps`, `run_steps`, `ImageSource` | unusable input; plain-text message |
| `RuntimeError` | `VncSession.screenshot`, `_to_data_url` | image unreadable / not encodable |
| `requests.*` | `Vlm` | endpoint unreachable, HTTP error, timeout |
| `vncdotool` exceptions | `VncSession()` | connection / authentication failed |

Catching `Exception` in an interactive loop does not catch `SystemExit` —
call `load_steps` and `ImageSource` before entering the loop.
