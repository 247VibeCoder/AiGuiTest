# AiGuiTest

Semantic GUI tests over VNC with a vision LLM (Qwen3-VL).

Instead of maintaining click coordinates, the test is written in sentences:
*"Is a terminal window with a shell prompt open?"*, *"the close button of
the Geany window"*. A vision model looks at the screenshot and answers.
Where an element looks the same every time, an image of it (a *needle*) is
found by template matching instead - fast and without a model.

Tests are **Python with the aiguitest commands**, run by **pytest**:

```python
from aiguitest import *


def test_login():
    tries = 0
    while ImageFound("LoginDialog") and tries < 3:
        tries += 1
        Click("PasswordField")
        TypeText("secret", Enter)
        Wait(2)
    if not ImageFound("StartPage", timeout=10):
        LogError("not logged in after %d tries" % tries)
```

**Commands:** [doc/commands.md](doc/commands.md) · **API reference:**
[doc/api.md](doc/api.md) · **VS Code:** [vscode/](vscode/README.md)

## Layout

```
aiguitest/              importable package - the API
    config.py           constants and paths
    keys.py             key names (ControlKey, Enter) -> vncdotool
    marks.py            candidate_boxes, needle_filter, draw_marks, match
    vnc.py              VncSession (real desktop), ImageSource (PNG)
    vlm.py              Vlm.ask / locate / raw, FakeVlm, VlmError
    runner.py           Run (actions and their log), replay, selftest
    commands.py         the commands tests are written in: Click, TypeText ...
    pytest_plugin.py    one Run per test, VNC once per session, options
aiguitest-run           test run (CLI): pytest with the plugin, --replay, --selftest
aiguitest-bridge        the package over stdio for the VS Code extension (CLI)
vscode/                 VS Code extension: command list, live view, recorder
tests/                  the tests: test_*.py, shared steps in common.py
images/                 needles (example images), versioned
doc/                    commands.md, api.md (API reference), website.md
aiguitest-architektur.drawio
                        diagram: components, layers, step flow (by hand)
archiv/vnc_test.py      first spike, plain VNC without a model
```

The CLIs import the package, never the other way round. Inside the package
all dependencies point downwards: `pytest_plugin` → `commands` → `runner`
→ `vlm`/`vnc` → `marks` → `config`.

## Requirements

- Python 3.12
- Reachable VNC server with an X desktop (default `172.19.0.10::5901`)
- OpenAI-compatible endpoint with a vision model (default: Ollama at
  `http://ctollama.example.com:11434/v1`, model `qwen3-vl:8b`)

```bash
python3 -m venv .venv
.venv/bin/pip install vncdotool opencv-python-headless numpy requests pytest
```

`pip` lives in the venv, not on the `PATH` — so call `.venv/bin/pip`. The
same goes for the interpreter: the shebangs point to the system Python,
which lacks `cv2`. So start via `./start.sh`, which creates the venv when
needed and picks the right interpreter.

```bash
./start.sh                                   # = aiguitest-run: all tests
./start.sh aiguitest-run --selftest
./start.sh archiv/vnc_test.py --wait 3
```

### Internal package index

`http://` indexes need `PIP_TRUSTED_HOST`, otherwise pip refuses the
unencrypted connection:

```bash
export PIP_INDEX_URL="http://arcane01.example.com:3141/root/pypi/+simple/"
export PIP_TRUSTED_HOST="arcane01.example.com"
```

## Writing tests

A test is a function `test_...` in `tests/test_<name>.py`. `from
aiguitest import *` brings the commands and key constants; the pytest plugin gives
every test its own run and binds the commands to it. Everything else is
plain Python: variables, `if`/`while`/`for`, `try`/`except`, helper
functions. [tests/test_xeyes.py](tests/test_xeyes.py) and
[tests/test_geany.py](tests/test_geany.py) are complete examples;
[tests/common.py](tests/common.py) holds steps several tests share.

### Targets

Every pointer and wait command takes a target the same way:

| Target | Found by |
| --- | --- |
| `Click("OkButton")` | template: `images/OkButton.png` (extension optional) |
| `Click("text:the OK button")` or `Click(text="the OK button")` | the vision model |
| `Click(image="close", text="the X of the Geany window")` | template finds the candidates, the model picks one |
| `Click((412, 87))` | a fixed point |
| `Click(text="the OK button", point=(412, 87))` | the remembered point, checked against `images/points/` — see [Running tests](#running-tests) |

`threshold=0.8` lowers the template threshold (default 0.9), `timeout=`
sets how long a command waits for its target (default 20 s).

### Commands

| Command | Effect |
| --- | --- |
| `Click`, `DoubleClick`, `RightClick`, `MoveTo` | pointer action on a target, waits for it |
| `Drag(target)`, `Drop(target)` | press on one target, release on another |
| `ClickMarks(prompt, needle=...)` | numbered candidates, the model picks a number |
| `ScrollWheelDown(count, target=...)`, `...Up/Left/Right` | scroll, over a target if given |
| `TypeText("text", Enter, ControlKey, "c")` | text and keys in order; modifiers combine with what follows |
| `KeyDown(ShiftKey)`, `KeyUp(ShiftKey)` | hold and release a key |
| `WaitFor(target)`, `WaitWhile(target)` | until visible / gone; `WaitWhile(lambda: ...)` while true |
| `Wait(seconds)` | a hard pause |
| `ImageFound(target)` | `True`/`False`, never fails - for `if` and `while` |
| `ReadText(target)` | the text of a target, read by the model |
| `Ask("question?")` | the model's yes/no as `True`/`False` |
| `Describe("question?")` | the model's answer in words, also shown at the end of the run |
| `Assert("question?", expected=False)` | the model judges; fails unless the answer is expected |
| `Log`, `LogWarning`, `LogError` | markers; `LogError` lets the test go on and fails it at the end |
| `CaptureScreen("name")` | named screenshot into the run folder |

Key constants: `Enter`, `Tab`, `Escape`, `Backspace`, `Delete`, `Home`,
`End`, `PageUp`, `PageDown`, the arrows (`UpArrow` ...), `Space`, `F1`-`F12`
and the modifiers `ControlKey`, `ShiftKey`, `AltKey`, `WindowsKey`,
`CommandKey`. A plain string is always text: `TypeText("Enter")` types the
word.

Commands fail like an `assert` when their target doesn't show up in time;
pytest reports the test as failed and the screen is saved as `error.png`.
A model endpoint that is down raises `VlmError` with a plain-text report
(endpoint, proxy, a short `GET <base>/models`) — it is not a test verdict,
so `except AssertionError` doesn't catch it.

## Running tests

```bash
./start.sh aiguitest-run                         # every test in tests/
./start.sh aiguitest-run login                   # tests/test_login.py
./start.sh aiguitest-run tests/test_login.py::test_locked -x
./start.sh aiguitest-run login --nollm           # strictly without the model, see below
./start.sh aiguitest-run login --vnc host::5901 --vnc-password secret
./start.sh aiguitest-run login --image desk.png --fake-vlm    # offline
./start.sh aiguitest-run --junitxml=report.xml   # for CI
./start.sh aiguitest-run --replay runs/20261104-183154/test_login
```

Everything besides `--selftest` and `--replay` goes to pytest: `-k`, `-x`,
`-v`, `--junitxml` work as always. Plain `pytest` works too —
[pytest.ini](pytest.ini) loads the plugin.

**Remembered points make runs fast.** A `text=` target carries the point
where it was found: `Click(text="the OK button", point=(412, 87))`. Next
to the test, `images/points/` holds a reference image of the element. A
run first looks for the reference image around the point by template — a
hit is a click in milliseconds, without the model. If the element moved,
the new place is clicked; if it looks different now, the model searches
it again. Every point found anew is **written back into the test** after
each test (`point=` added or corrected, the rest of the line stays
as it is); pytest lists them under *aiguitest: remembered points*. So the
first run of a hand-written test asks the model, the following ones don't.
A file you edited during the run is left alone. The VS Code recorder
saves point and reference image right when it records.

**`--nollm`** is the strictly model-free run: a `text=` target is only
clicked where its remembered point and reference image say. If they
don't match — or there is no point yet — the test fails with a message
instead of asking the model. `Assert`, `Ask`, `Describe` and `ReadText` still ask
the model — they are the actual test.

Every test logs to `runs/<timestamp>/<test>/`: a screenshot per step,
needle crops and `run.json`. The console output also goes to
`log/<timestamp>_<name>.log`. `--replay` plays a test's recorded path
again without a model, clicks via template matching; decisions (`if`,
`ImageFound`) and asserts are not re-evaluated.

If the VNC connection fails, the run stops with exit 2 and plain text — no
traceback:

```
No VNC connection to 172.19.0.10::5901
  AuthenticationError: password required, but none provided
  Check --vnc, config.json or VNC_SERVER/VNC_PASSWORD.
```

### Check without hardware

```bash
./start.sh aiguitest-run --selftest
```

Checks scaling, box back-transformation, JSON extraction, template
matching, the needle filter, every command and the pytest plugin
against a synthetic desktop. Needs neither VNC nor a model.

## Writing tests in VS Code

[vscode/](vscode/README.md) holds a VS Code extension: a list of the
commands with their descriptions (insert as a snippet), a live view of the
desktop that records clicks and dragged regions as lines of the test —
cutting the needles into `images/` — and *Run* / *Debug* above every
test. *Debug* runs the test under VS Code's Python debugger: breakpoints,
stepping, *Run to Cursor*, and in the Debug Console the commands act on
the desktop while the test is paused (`Click(text="the OK button")`).
**Ctrl+Enter** runs the line at the cursor and moves on to the next one.

## Using it as a submodule in a test repo

The tool and the tests can live in separate repos. The test repo holds the
tests, needles and results; AiGuiTest is pulled in as a git submodule:

```bash
cd my-tests
git submodule add ssh://git@git-ssh.example.com:2222/vibecoder/AiGuiTest.git AiGuiTest
mkdir -p tests images
printf 'tmp/\nlog/\nruns/\nconfig.json\n' >> .gitignore
```

`AIGUITEST_HOME` tells the tool where the tests are. A thin wrapper in the
test repo sets it:

```bash
#!/usr/bin/env bash
# Delegates to the AiGuiTest submodule's start.sh; this repo is the
# workspace (tests/, images/, runs/, tmp/, log/, config.json).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUBMODULE="$DIR/AiGuiTest"

if [ ! -x "$SUBMODULE/start.sh" ]; then
    echo "AiGuiTest submodule not initialised: $SUBMODULE/start.sh is missing." >&2
    echo "Run: git submodule update --init" >&2
    exit 2
fi

cd "$DIR"
export AIGUITEST_HOME="$DIR"

# accept submodule-rooted paths like AiGuiTest/aiguitest-run too
if [ "${1:-}" != "" ] && [ "${1#AiGuiTest/}" != "$1" ]; then
    set -- "${1#AiGuiTest/}" "${@:2}"
fi

exec "$SUBMODULE/start.sh" "$@"
```

| Where | What |
| --- | --- |
| test repo (`AIGUITEST_HOME`) | `tests/`, `images/`, `runs/`, `config.json`, `tmp/`, `log/` |
| submodule (`AiGuiTest/`) | code, `start.sh`, `.venv/` (ignored by the submodule) |

`aiguitest-run` passes `--rootdir` and the plugin itself, so the test repo
needs no `pytest.ini`. Image names resolve in the test repo's `images/`
first, then in the submodule's. After cloning the test repo, fetch the
submodule with `git submodule update --init`; to move to a newer
AiGuiTest, run `git submodule update --remote AiGuiTest` and commit the
new pointer.

## Programmatic use

The commands are a thin layer over `Run`; the same primitives work in any
Python script. The full reference is [doc/api.md](doc/api.md).

```python
from aiguitest import Run, VncSession, Vlm, bind, unbind, Click, Assert

session = VncSession("172.19.0.10::5901", "123456")
run = Run(session, Vlm(), "runs/manual")
prev = bind(run)                  # what the pytest plugin does per test
try:
    Click(text="the applications button")
    Assert("Is the applications menu open?")
finally:
    unbind(prev)
    run.save()                    # run.json - --replay can repeat it
    session.close()
```

`ImageSource("screen.png")` replaces `VncSession` with a PNG and
`FakeVlm()` answers without a model — both for trying things offline.

The four functions in `marks` are independent of VNC and the model:

```python
import cv2
from aiguitest import candidate_boxes, draw_marks, match, needle_filter

img = cv2.imread("screenshot.png")
boxes = [b for b, _ in needle_filter(img, candidate_boxes(img), "images/close.png")]
score, cx, cy = match(img, cv2.imread("images/close.png"))
cv2.imwrite("annotated.png", draw_marks(img, boxes))
```

## Configuration

The values come from an optional `config.json` in the workspace (the
project directory, or `AIGUITEST_HOME`) or from environment variables; the
**environment beats the file**, the file beats the default. The command
line (`--vnc`, `--vnc-password`) beats both. `config.json` is in
`.gitignore` because address and password differ per machine —
[config.example.json](config.example.json) serves as the template:

```bash
cp config.example.json config.json
```

```json
{
  "vnc": { "server": "172.19.0.10::5901", "password": "123456" },
  "vlm": { "base": "http://ctollama.example.com:11434/v1", "model": "qwen3-vl:8b", "key": "none", "verify": true }
}
```

Every key is optional. Unknown keys are reported on stderr and ignored, a
broken file aborts with a plain-text message.

| `config.json` | Variable | Default |
| --- | --- | --- |
| `vnc.server` | `VNC_SERVER` | `172.19.0.10::5901` |
| `vnc.password` | `VNC_PASSWORD` | `123456` (empty/`null` = server without password) |
| `vlm.base` | `VLM_BASE` | `http://ctollama.example.com:11434/v1` |
| `vlm.model` | `VLM_MODEL` | `qwen3-vl:8b` |
| `vlm.key` | `VLM_KEY` | `none` |
| `vlm.verify` | `VLM_VERIFY` | `true`; path of a CA file for a private CA, `false` turns the check off |

**About the server address:** one colon is the *display number* (`host:1` →
port 5901), two colons are the *actual port* (`host::5901`).

**Live view and test run at the same time** need a VNC server that shares
the desktop between clients (TigerVNC `-AlwaysShared`, x11vnc `-shared`).

## Why the detour via needles

Measured on a desktop with a terminal and Geany:

| Approach | Candidates | Result | Tokens |
| --- | --- | --- | --- |
| box straight from the model | — | off target, partly outside the image | 1965 |
| `ClickMarks` without needle | 60 | no answer (`content` empty) | 2942 |
| `ClickMarks` with needle | 2 | correct | 205 |

The first row is outdated: the model returns boxes on a 0..1000 scale
instead of pixels, and that's exactly how they were misread back then.
Since `Vlm.locate` converts that, a `text=` target hit 5 of 6 targets on an
Xfce desktop (menu entries, dock icons, panel button); in exchange an empty
answer occasionally comes back. For elements that look the same several
times (the × of two windows), `image=` plus `text=` or `ClickMarks` with a
needle remain the way.

All these numbers were measured with the earlier German prompts. The
prompts and answer formats are English now; the measurements still need
repeating.

`candidate_boxes` finds edges, and rendered text consists of edges — of 60
candidates, 20 were mere text fragments, and the model missed (it picked
the menu entry "Help" instead of the ×). The template reliably answers
*"is this a close button"*, the model reliably *"in which window"*. Only
together do they make a usable click.

`candidate_boxes` sorts row by row and returns at most 60 boxes. On
`runs/.../03_nach_dem_start.png` there are 106; the cut falls at `y=195`,
everything below is unreachable for `ClickMarks`. The status line "This is
Geany 2.0" at `y≈464` is in the list as four word boxes — behind the
limit. For text further down the image use `Ask` or `ReadText`.

A needle is a small image crop of the element you're looking for, such as
`images/close.png`. It depends on resolution and theme: every widget kind
needs one, and with a different window style it no longer matches.
