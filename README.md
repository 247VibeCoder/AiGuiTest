# AiGuiTest

Semantic GUI tests over VNC with a vision LLM (Qwen3-VL).

Instead of maintaining click coordinates, the test is written in sentences:
*"Is a terminal window with a shell prompt open?"*, *"Click the close
button of the Geany window"*. A vision model looks at the screenshot and
answers the question.

Because model calls are slow and not bit-exactly reproducible, the test
steps store **prompts, not pixels** and are evaluated afresh on every run.
For clicks, a template comparison sieves the candidates first.

**API reference:** [doc/api.md](doc/api.md).

## Layout

```
aiguitest/              importable package - the API
    config.py           constants and paths
    marks.py            candidate_boxes, needle_filter, draw_marks, match
    vnc.py              VncSession (real desktop), ImageSource (PNG)
    vlm.py              Vlm.ask / locate / raw, FakeVlm
    runner.py           Run, run_steps, scenario, replay, selftest
aiguitest-workbench     interactive prompt workbench (CLI)
aiguitest-run           test run (CLI)
scripts/                step files, e.g. test1.yaml
doc/                    api.md (API reference), website.md
images/                 needles (example images), versioned
aiguitest-architektur.drawio
                        diagram of the overall flow (maintained by hand)
archiv/vnc_test.py      first spike, plain VNC without a model
```

The CLIs import the package, never the other way round. Inside the package
all dependencies point downwards: `runner` → `vlm`/`vnc` → `marks` →
`config`. The package API is described in [doc/api.md](doc/api.md).

## Requirements

- Python 3.12
- Reachable VNC server with an X desktop (default `172.19.0.10::5901`)
- OpenAI-compatible endpoint with a vision model (default: Ollama at
  `http://ctollama.home.arpa:11434/v1`, model `qwen3-vl:8b`)

```bash
python3 -m venv .venv
.venv/bin/pip install vncdotool opencv-python-headless numpy requests pyyaml
```

`pip` lives in the venv, not on the `PATH` — so call `.venv/bin/pip`. The
same goes for the interpreter: the shebangs point to the system Python,
which lacks `cv2`. So start via `./start.sh`, which creates the venv when
needed and picks the right interpreter.

```bash
./start.sh                                   # = aiguitest-run
./start.sh aiguitest-run --selftest
./start.sh aiguitest-workbench --fake --image image.png
./start.sh archiv/vnc_test.py --wait 3
```

A first argument naming a file in the project selects the script; a typo
aborts with exit 2 instead of silently starting the default.

### Internal package index

`http://` indexes need `PIP_TRUSTED_HOST`, otherwise pip refuses the
unencrypted connection:

```bash
export PIP_INDEX_URL="http://arcane01.home.arpa:3141/root/pypi/+simple/"
export PIP_TRUSTED_HOST="arcane01.home.arpa"
```

## Usage

### Check without hardware

```bash
./start.sh aiguitest-run --selftest
```

Checks scaling, box back-transformation, JSON extraction, template matching
and the needle filter against a synthetic desktop. Needs neither VNC nor a
model.

### Develop prompts

```bash
./start.sh aiguitest-workbench                      # against VNC
./start.sh aiguitest-workbench --image screen.png   # offline
./start.sh aiguitest-workbench --fake --image x.png # without a model
./start.sh aiguitest-workbench -n 5                 # every prompt 5x
```

| Command | Effect |
| --- | --- |
| `see [question]` | free description of the screen |
| `ask <question>` | yes/no judgement, reports stability over `n` repetitions |
| `find <description>` | bounding box straight from the model — good for menu entries and icons, but scatters, see below |
| `find <image.png>` | search an image by template, **without a model** — `find close.png` searches `images/close.png`, `find <Tab>` lists the images; a `click` afterwards becomes a `click_needle` step; `--score 0.8` lowers the threshold (default 0.9) and goes into the step as `threshold` |
| `marks <description>` | numbered candidates, the model only picks a number |
| `marks <d> --needle <image>` | as above, sieved by template first — 60 typically become 2; bare name as with `find` from `images/` |
| `pick <n>` | pick a candidate by hand, number from `tmp/vlm_annot.png`, no model call |
| `click [x y]` | click the last hit or fixed coordinates |
| `mouse x y` | only move the mouse, no click — `mouse 0,0` moves it out of the way so no hover effect skews needle or judgement; becomes a `mouse` step |
| `key <key>` | **key name**: `enter`, `space`, `ctrl-alt-t`, `alt-f4` |
| `type <text>` | type text character by character |
| `n <number>` | repetitions per prompt |
| `shot [path]` | save a screenshot — local only, **not** a step |
| `log <text>` | marker `=== text ===` in the session log, e.g. `log "ready for step 2"`; becomes a `log` step and so also shows up in the test run |
| `history [n]` | show the last `n` inputs (default 10, `all` for all) |
| `drop [i]` | remove input `i`, the last one if not given |
| `export [name]` | write the steps to `scripts/<name>.yaml` (default `steps`); `.yaml` is added, a path with a directory applies as given |
| `use <name> [nollm\|llm]` | run `scripts/<name>.yaml` in the current session; if every click step has a `point`, automatically `nollm` (see below), otherwise with the model — `nollm`/`llm` forces the mode; e.g. `use openTerminal` to continue from there; names as with `export`, `use <Tab>` lists the scripts; becomes a `use` step, so `export` writes the reference instead of the steps |

The history records every input **verbatim**, including `find`, `n` or one
that failed — only `history`, `drop`, `export` and `help` are left out.
Behind some lines `->` shows the step that `export` writes from it into the
file: `ask` becomes `assert`, `key`, `type`, `mouse` and `log` stand for
themselves, and the `click` after `find`/`marks` becomes `click`/
`click_marks`/`click_needle` with the prompt (and needle) from there. A
`use` becomes a single `use` step, but only if it ran through; if it aborts,
the workbench saves the screen to `tmp/use_<name>/error.png`. A `click`
after `pick` or on fixed coordinates yields no step — there is no prompt a
run could repeat. Whatever was only tried out, `drop` takes out again.

The arrow-key history persists across sessions, in `~/.aiguitest_history`
(the last 1000 lines). On start the workbench reports where it writes; if
the line is missing, no real terminal is attached. Tab completes commands,
after `use`/`export` the names from `scripts/`, and after `find` and
`--needle` the images from `images/`.

All intermediate images land in the project's own `tmp/`, not in `/tmp`.
The directory is created when needed and is in `.gitignore`.

### Example session

```
> key ctrl-alt-t
> ask Is a terminal window open?
> marks the close button (X) of the Geany window --needle images/close.png
  2 candidates, annotated: tmp/vlm_annot.png  ('pick <n>' picks by hand)  [needle images/close.png: 2 of 60, best score 1.000]
  -> number 1, centre (531,138)
> click
  + #3 -> click_marks  the close button (X) of the Geany window  [needle images/close.png]  at (531, 138)
> history
   0 key ctrl-alt-t                           -> key          ctrl-alt-t
   1 ask Is a terminal window open?           -> assert       Is a terminal window open?
   2 marks the close button (X) of the Geany window --needle images/close.png
   3 click                                    -> click_marks  the close button (X) of the Geany window  [needle images/close.png]  at (531, 138)
> export geanyClose
  3 steps -> scripts/geanyClose.yaml
```

`export` always writes the **whole** list and overwrites the file.

### Running steps

```bash
./start.sh aiguitest-run scripts/test1.yaml            # run a step file
./start.sh aiguitest-run --steps scripts/test1.yaml    # same thing
./start.sh aiguitest-run test1                         # bare name: scripts/test1.yaml
./start.sh aiguitest-run scripts/openTerminal.yaml --nollm   # faster, see below
./start.sh aiguitest-run --replay runs/20260912-064300
```

**`--nollm`** makes `click` and `click_marks` steps click their stored
`point` instead of letting the model search. The workbench records `point`
on the `click` after `find`/`marks`. Asserts still ask the model, they are
the actual test. If a click step lacks `point` (older file), the run aborts
with a hint. In the workbench the same thing is `use <name> nollm`; a plain
`use <name>` picks it by itself as soon as every `click`/`click_marks` step
has a `point`, and `use <name> llm` forces the model. A `use <name>`
**with** the model fills missing points into the script file (`2 point(s)
filled in in scripts/openTerminal.yaml`); existing ones stay untouched, so
the versioned file doesn't drift a few pixels with every run. A point only
holds as long as windows and resolution stay where they are.

Every run logs to `runs/<timestamp>/`: a screenshot per step, needle crops
and `run.json`. The console output also goes to
`log/<timestamp>_<name>.log`. The workbench writes **one log per session**,
`log/<timestamp>_workbench.log`, with all inputs (`> ...`) and outputs,
including those of `use`. `log/` is not versioned. `--replay` plays the
same sequence without a model, clicks via template matching; assert steps
are skipped.

**If a step fails**, the screen is saved as `error.png` in the run folder
and the path is printed — also on an unexpected error, not just on a failed
assert.

### Step file format

Step files are **YAML** with 2-space indentation;
[scripts/test1.yaml](scripts/test1.yaml) is a complete example. Older
`.json` files are still read, but `export` only writes YAML. Comments
(`# ...`) are allowed — `use` doesn't rewrite a file with comments, it only
prints filled-in points then.

```yaml
name: Start Geany and close it again
vnc:
  server: 172.19.0.10::5901
  password: '123456'
steps:
  - type: use
    script: openTerminal
  - type: type
    text: geany &
  - type: key
    key: enter
  - type: screenshot
    name: after_start
  - type: assert
    prompt: Is Geany open?
  - type: click_marks
    prompt: the close button (X) of the Geany window
    needle: images/close.png
```

| `type` | Fields | Effect |
| --- | --- | --- |
| `key` | `key` | send a key name |
| `type` | `text` | type text character by character |
| `screenshot` | `name` | named screenshot into the run folder |
| `log` | `text` | marker `=== text ===` in output, log and `run.json` |
| `mouse` | `point` | move the mouse to `[x, y]`, no click |
| `use` | `script`, `mode` | run another script at this point, name as with `use` (`openTerminal` = `scripts/openTerminal.yaml`); its `vnc` block doesn't count. `mode: nollm` or `mode: llm` sets how that script clicks, otherwise like the run; `use <name> nollm` in the workbench writes it along |
| `assert` | `prompt`, `expected` | the model judges, polls until timeout |
| `click` | `prompt`, `point` | box straight from the model — hit 5 of 6, occasionally an empty answer |
| `click_marks` | `prompt`, `needle`, `point` | sieve candidates, the model picks, click |
| `click_needle` | `needle`, `threshold` | search an image by template and click, without a model — only for targets that exist once; `threshold` optional, default 0.9 |

`name` is optional everywhere and only used for output. `point` (`[x, y]`)
is optional and only used with `--nollm`. For `assert`, `expected: false`
expects the **opposite** ("window is gone now"); without it `true` applies.
The workbench sets `expected: false` if `ask` answered no by majority —
`history` shows that as `[expected: no]`.

Older files with German keys (`schritte`, `typ`, `erwartet`, `passwort`)
are still read and translated on load; only English is written.

The `vnc` block is optional. Order: **command line** (`--server`) beats
**file** beats **environment** (`VNC_SERVER`/`VNC_PASSWORD`). A `password`
in the block is read, but `export` never writes it — the file is versioned.
The password in [scripts/test1.yaml](scripts/test1.yaml) is the lab
password that is in the repo anyway; if the test points to another system,
it belongs out of there and into `VNC_PASSWORD`.

If the connection fails, `aiguitest-run` reports it in plain text and exits
with 2 — no traceback:

```
No VNC connection to 172.19.0.10::5901
  AuthenticationError: password required, but none provided
  Check 'vnc' (server/password) in the step file, --server or ...
```

`click_marks` clicks by itself. If you translate a workbench transcript,
leave out the following `click` line, otherwise it clicks twice.

## Using it as a submodule in a test repo

The tool and the tests can live in separate repos. The test repo holds the
step files, needles and results; AiGuiTest is pulled in as a git submodule:

```bash
cd my-tests
git submodule add ssh://git@git-ssh.googlepost.de:2222/markus/AiGuiTest.git aiguitest
mkdir -p scripts images
printf 'tmp/\nlog/\nconfig.json\n' >> .gitignore
```

`AIGUITEST_HOME` tells the tool where the tests are. A thin wrapper
in the test repo sets it. The canonical one (taken from
[my-tests/start.sh](https://example.invalid/my-tests)) handles three
small things the inner script does not: it points the workspace at
the test repo (so `scripts/`, `images/`, `config.json` resolve
there), and it strips an `AiGuiTest/` prefix from the first argument
so callers can write either `./start.sh aiguitest-workbench` or
`./start.sh AiGuiTest/aiguitest-workbench`. The full source:

````bash
#!/usr/bin/env bash
# Thin wrapper that delegates to the AiGuiTest submodule's own start.sh.
#
# Usage (same as the inner script):
#   ./start.sh                                       # = aiguitest-run
#   ./start.sh aiguitest-run --selftest
#   ./start.sh scripts/test1.yaml                    # = aiguitest-run scripts/test1.yaml
#   ./start.sh aiguitest-workbench --fake --image image.png
#   ./start.sh archiv/vnc_test.py --wait 3
#
# This repo's files (scripts/, images/, runs/, tmp/, log/, config.json)
# are the workspace, so AIGUITEST_HOME is pointed at the parent directory.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SUBMODULE="$DIR/AiGuiTest"

if [ ! -x "$SUBMODULE/start.sh" ]; then
    echo "AiGuiTest submodule not initialised: $SUBMODULE/start.sh is missing." >&2
    echo "Run: git submodule update --init" >&2
    exit 2
fi

# Run from this repo so relative paths in step files resolve here.
cd "$DIR"
export AIGUITEST_HOME="$DIR"

# Strip an "AiGuiTest/" prefix from the first argument if the caller used
# a submodule-rooted path like "AiGuiTest/aiguitest-workbench". The inner
# start.sh lives in the submodule root and looks up scripts there
# without a prefix.
if [ "${1:-}" != "" ] && [ "${1#AiGuiTest/}" != "$1" ]; then
    set -- "${1#AiGuiTest/}" "${@:2}"
fi

exec "$SUBMODULE/start.sh" "$@"
````

Three lines do most of the work:

- `cd "$DIR"` — `start.sh` itself lives next to the test files, so
  the venv created under `.venv/` sits in the test repo's
  `.gitignore`. The wrapper then `cd`s back to the test repo so
  relative paths in step files resolve there.
- `export AIGUITEST_HOME="$DIR"` — tells the inner script where the
  tests are. Without this, `SCRIPT_DIRS` would resolve under the
  submodule and the workbench's `use <Tab>` would only see the
  submodule's own `scripts/`.
- The `AiGuiTest/` prefix strip — the inner script lives in the
  submodule root and looks up scripts by basename. Prefixed paths
  like `AiGuiTest/aiguitest-workbench` would be treated as "no
  such script" without this. With the strip, both styles work:

```bash
./start.sh                                 # = aiguitest-run
./start.sh aiguitest-run --selftest
./start.sh scripts/test1.yaml              # step file -> aiguitest-run
./start.sh aiguitest-workbench --fake --image images/foo.png
./start.sh archiv/vnc_test.py --wait 3
```

| Where | What |
| --- | --- |
| test repo (`AIGUITEST_HOME`) | `scripts/`, `images/`, `runs/`, `config.json`, `tmp/`, `log/` |
| submodule (`aiguitest/`) | code, `start.sh`, `.venv/` (ignored by the submodule) |

`start.sh` changes into `AIGUITEST_HOME`, so relative paths in step files
(`images/close.png`) refer to the test repo. Without `AIGUITEST_HOME`
everything stays as before: the tool's own directory is the workspace.

After cloning the test repo, fetch the submodule with
`git submodule update --init`; to move to a newer AiGuiTest, run
`git submodule update --remote aiguitest` and commit the new pointer.

## Programmatic use (as a Python library)

The CLI tools (`aiguitest-run`, `aiguitest-workbench`) are thin
wrappers over the `aiguitest` package. The same primitives are
importable, so Python can drive the test instead of a YAML file. The
full reference is in [doc/api.md](doc/api.md); the page below is the
short version.

### Always start with the venv interpreter

The package is **not installed** — it is imported from the project
directory. The interpreter at `.venv/bin/python` already has `cv2`,
`vncdotool`, `pyyaml` and `requests`; the system interpreter does
not. Run Python via `start.sh` (it accepts a path argument):

```bash
./start.sh my_script.py        # any *.py next to start.sh
./start.sh archiv/spike.py -- --image foo.png
```

The double dash separates the script's own arguments from those
`start.sh` consumes.

### Minimal end-to-end run

```python
from aiguitest import Run, VncSession, Vlm

session = VncSession("172.19.0.10::5901", "123456")
run = Run(session, Vlm(), "runs/manual")
try:
    run.click_element("the applications button")
    run.assert_visible("Is a terminal window open?")
finally:
    session.close()
```

`Run` writes every step into `runs/manual/run.json` as it executes,
so a crash leaves a partial log on disk. The session is entered
exactly once; calling `.close()` sends the VNC disconnect.

### Drive a step file from Python

`run_steps(...)` is the same function the CLI uses, so a recorded
file is replayable programmatically:

```python
from aiguitest import Run, VncSession, Vlm, load_steps, run_steps

session = VncSession("172.19.0.10::5901", "123456")
run = Run(session, Vlm(), "runs/replay")
data, steps = load_steps("scripts/openTerminal.yaml")  # bare name OK
try:
    run_steps(run, steps, points=True, inside=("scripts/openTerminal.yaml",))
finally:
    session.close()
```

Per-step `mode: nollm`/`mode: llm` override the global `points`
flag; without a per-step mode, `points=True` clicks on stored
positions and `points=False` asks the model. Asserts always query
the model regardless.

### Run without hardware

`ImageSource` replaces `VncSession` with a PNG and `FakeVlm` returns
deterministic answers. Both are useful in unit tests:

```python
from aiguitest import Run, ImageSource, FakeVlm, run_steps

src = ImageSource("images/screenshot.png")
run = Run(src, FakeVlm(), "tmp/fake")
run_steps(run, [{"type": "click", "prompt": "x", "point": [10, 10],
                 "mode": "nollm"}], points=True, inside=())
```

`FakeVlm.ask` accepts a `conf` parameter for the answer and
`FakeVlm.locate` returns a list of boxes — handy when a test must
assert that a particular prompt was sent through.

### Reuse the image analysis

The four functions in `marks` are independent of VNC and the model:

```python
from aiguitest import candidate_boxes, needle_filter, match, draw_marks
import cv2

img = cv2.imread("screenshot.png")
boxes = candidate_boxes(img)
boxes = [b for b, _ in needle_filter(img, boxes, "images/close.png",
                                     threshold=0.9)]
score, cx, cy = match(img, cv2.imread("images/close.png"))
cv2.imwrite("annotated.png", draw_marks(img, boxes))
```

These return / take the same `(x, y, w, h)` notation as the
internals, so a script can pre-filter candidates, pick the right
one, and hand the click coordinates to `Run.click_point(cx - w//2,
cy - h//2, "label")`.

### Layers and what to import from where

| Want to … | Import from `aiguitest` |
| --- | --- |
| drive a real desktop | `VncSession`, `Run`, `run_steps`, `load_steps`, `scenario`, `replay`, `selftest` |
| drive a PNG / stub the model | `ImageSource`, `FakeVlm` |
| talk to the model | `Vlm`, `_extract_json` (advanced) |
| analyse screenshots | `candidate_boxes`, `needle_filter`, `match`, `draw_marks` |
| resolve paths in scripts/ | `script_path`, `image_path` (also `SCRIPT_DIRS`, `IMAGE_DIRS`) |
| write logs and temp images | `log_path`, `tmp_path` |

`config.py` is intentionally not imported directly by user code;
the constants are re-exported (`WORKSPACE`, `SERVER`, `VLM_MODEL`,
…), and `SCRIPT_DIRS` / `IMAGE_DIRS` only appear when this repo is
consumed as a submodule.

## Configuration

The values come from an optional `config.json` in the workspace (the
project directory, or `AIGUITEST_HOME`) or
from environment variables; the **environment beats the file**, the file
beats the default. `config.json` is in `.gitignore` because address and
password differ per machine — [config.example.json](config.example.json)
serves as the template:

```bash
cp config.example.json config.json
```

```json
{
  "vnc": { "server": "172.19.0.10::5901", "password": "123456" },
  "vlm": { "base": "http://ctollama.home.arpa:11434/v1", "model": "qwen3-vl:8b", "key": "none" }
}
```

Every key is optional. Unknown keys are reported on stderr and ignored, a
broken file aborts with a plain-text message.

| `config.json` | Variable | Default |
| --- | --- | --- |
| `vnc.server` | `VNC_SERVER` | `172.19.0.10::5901` |
| `vnc.password` | `VNC_PASSWORD` | `123456` (empty/`null` = server without password) |
| `vlm.base` | `VLM_BASE` | `http://ctollama.home.arpa:11434/v1` |
| `vlm.model` | `VLM_MODEL` | `qwen3-vl:8b` |
| `vlm.key` | `VLM_KEY` | `none` |

**About the server address:** one colon is the *display number* (`host:1` →
port 5901), two colons are the *actual port* (`host::5901`).

## Why the detour via needles

Measured on a desktop with a terminal and Geany:

| Approach | Candidates | Result | Tokens |
| --- | --- | --- | --- |
| `find` (box straight from the model) | — | off target, partly outside the image | 1965 |
| `marks` without needle | 60 | no answer (`content` empty) | 2942 |
| `marks --needle` | 2 | correct | 205 |

The `find` row is outdated: the model returns boxes on a 0..1000 scale
instead of pixels, and that's exactly how they were misread back then.
Since `Vlm.locate` converts that, `find` hit 5 of 6 targets on an Xfce
desktop (menu entries, dock icons, panel button); in exchange an empty
answer occasionally comes back. For elements that look the same several
times (the × of two windows), `marks --needle` remains the way.

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
everything below is unreachable for `marks` and `--needle`. The status line
"This is Geany 2.0" at `y≈464` is in the list as four word boxes — behind
the limit. For text further down the image use `ask`, not `marks`.

A needle is a small image crop of the element you're looking for, such as
`images/close.png`. It depends on resolution and theme: every widget kind
needs one, and with a different window style it no longer matches.
