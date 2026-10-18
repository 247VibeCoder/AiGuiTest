# AGENTS.md

Notes for coding agents (Claude Code, Codex, ...) working in this repo.

## What it's about

GUI tests against an X desktop over VNC, where a vision LLM plays the
checker: asserts are questions in natural language, click targets are
descriptions instead of coordinates. See [README.md](README.md) for the
user's view.

[aiguitest-architektur.drawio](aiguitest-architektur.drawio) shows the
overall flow. It is **maintained by hand** (own commits) and is the
reference for naming — the package name `aiguitest` comes from the box
`aiguitest-api` there. Don't put a second diagram next to it; structural
changes belong in there.

## Layout

```
aiguitest/          API package, dependencies only point downwards
    config.py       constants, config.json, TMPDIR/LOGDIR, tmp_path(),
                    log_path(), script_path() - imports nothing from
                    the package
    marks.py        candidate_boxes, needle_filter, draw_marks, match
    vnc.py          VncSession, ImageSource (same methods)
    vlm.py          Vlm.ask/locate/raw, FakeVlm
    runner.py       Run, run_steps, run_log, load/save_steps, scenario,
                    replay, selftest
aiguitest-workbench interactive workbench (CLI, no file extension)
aiguitest-run       test run (CLI)
scripts/            step files (test1.yaml)
doc/                api.md (API reference), website.md
images/             versioned needles
archiv/vnc_test.py  first spike, plain VNC
```

The CLIs import `aiguitest`, never the other way round. The workbench class
belongs in the CLI, not in the package — it's a user interface, not API.

**Tool and tests can be separate.** `PROJECT` is where the code lives,
`WORKSPACE` where the tests live (`scripts/`, `images/`, `runs/`, `tmp/`,
`log/`, `config.json`). `WORKSPACE` is `AIGUITEST_HOME` or else `PROJECT`;
a test repo that has this repo as a submodule sets it, and `start.sh` cds
there so relative needle paths resolve in the test repo. New paths for test
data go under `WORKSPACE`, never `PROJECT`.

## Commands

```bash
./start.sh aiguitest-run --selftest          # without VNC/model
./start.sh aiguitest-run --steps steps.yaml
./start.sh aiguitest-run openTerminal          # = scripts/openTerminal.yaml
./start.sh aiguitest-run --steps steps.yaml --nollm   # clicks on 'point'
./start.sh aiguitest-run --replay runs/<ts>
./start.sh aiguitest-workbench --fake --image image.png
```

Use `.venv/bin/python` and `.venv/bin/pip` — there's no `pip` and no
suitable `python3` on the `PATH`. Packages come from an internal devpi
mirror, `PIP_INDEX_URL` and `PIP_TRUSTED_HOST` belong in the environment.

There is no test suite except `--selftest`. Whoever changes `_shrink`,
`Vlm.locate`, `match` or `needle_filter` runs it afterwards — that's
exactly what it's for.

## Data flow

**Exploratory with the model first, then deterministic.**

1. `aiguitest-workbench` — try out prompts; the steps collect by themselves
   in the history (`history`, `drop`), `export <name>` →
   `scripts/<name>.yaml` with `vnc:` and `steps:`, overwrites the file
   completely. Bare names land in the fixed folder as with `shot`
   (`scripts/` instead of `tmp/`), `.yaml` is added
2. `aiguitest-run --steps steps.yaml` — `run_steps()` executes,
   `Run` logs to `runs/<timestamp>/`
3. `aiguitest-run --replay runs/<ts>` — the same sequence without a model

`--nollm` (workbench: `use <name> nollm`, or by itself with a plain
`use <name>` if every `click`/`click_marks` has a `point` —
`_all_points`; `use <name> llm` forces the model) sits in between:
`run_steps(..., points=True)` clicks `click`/`click_marks` on the `point`
the workbench records on `click`, **asserts keep running with the model** —
intended that way, don't "clean it up". The name `nollm` comes from the
user; in the API it's called `points`, because `llm=False` with model calls
would be a lie. Step without `point` → `AssertionError`. `run_steps`
returns the log entry per step; from it `use <name>` (with the model)
fills **missing** `point`s into history and script file (`_write_points`,
only replaces entries in `steps`, everything else stays). Never overwrite
existing points — otherwise every run changes the versioned file. Old files
with `schritte` aren't rewritten.

Two formats, don't mix them up: `steps.yaml` (input, prompts, YAML) and
`run.json` (log, with points and needle names, stays JSON).

**Step files are YAML** (`scripts/*.yaml`), written only via
`save_steps()`: 2 spaces, lists under `steps:` indented, `type` and `name`
first, number lists like `point` on one line, no line breaks in long
prompts. `load_steps()` still reads `.json` (by extension), but `export`
never writes JSON. PyYAML drops comments when writing back — that's why
`use` doesn't write points into files with `#`, but prints them.

Step types: `key`, `type`, `screenshot`, `assert`, `click`, `click_marks`,
`click_needle` (optional `threshold`), `mouse` (only move, `point`), `use`
(another script, `script`, optional `mode`), `log` (marker, form from
`log_marker()`). `load_steps()` reads the file and returns
`(data, steps)`; `run_steps()` gets the **list**, not the path. The
optional `vnc` block carries `server`/`password` — order: command line
beats file beats environment beats `config.json` beats default.
`config.json` isn't versioned (template: `config.example.json`); unknown
keys there are reported by `config.py` on stderr — so new settings also go
into `_CONFIG_KEYS`. `cmd_export` deliberately writes only `server`, never
the password.

Old files with German keys (`schritte`, `typ`, `erwartet`, ...) stay
readable: `_english_keys()` in `runner.py` translates them in
`load_steps`, `run_steps` and `replay`. The run folders under `runs/` are
versioned and still in the old format — don't rewrite them, that's what the
translation is for. New keys go into `_OLD_KEYS` only if there are old
files for them.

On every abort `Run.error_screenshot()` saves the screen; the method
catches an error while taking the screenshot itself, so a test failure
doesn't turn into a follow-up error. `aiguitest-run` catches `Exception`
for that, not just `AssertionError`.

## Design decisions that must not be "cleaned up"

- **Needle before model.** `needle_filter` sieves the candidates before the
  model is asked. Measured: 60 candidates → no answer (2942 tokens, empty
  `content`); 2 candidates → correct answer in 205 tokens. Four of four
  control runs correct, also with swapped target (terminal instead of
  Geany), so real discrimination and no position bias.
- **`max_tokens = 4000`.** qwen3-vl thinks in a separate `reasoning` field
  and needs ~2000 tokens for that; capped, an answer comes back with empty
  `content`. Ollama 0.32.5 ignores `think=false`, `reasoning_effort` and
  `/no_think` — the only option is to leave room.
- **`_shrink()` before sending.** `locate` converts the 0..1000 box
  straight to the original size and doesn't need the factor; `--selftest`
  checks exactly that (a pixel reading fails there).
- **`ask()` has the model describe first, then judge**, strictly. Don't
  simplify to a direct yes/no question, that was measurably worse.
- **`temperature=0`, `seed=1`**; asserts poll until the timeout.
- **`cv2.RETR_LIST`** in `candidate_boxes`: with `RETR_EXTERNAL` the window
  frame swallows all buttons in it.
- **`replay()` skips asserts.** Deliberately, not a bug.
- **Lazy imports** for `requests`, `vncdotool`, `vncdotool.keys` and
  `yaml`: that way `--selftest` and offline mode run without these
  packages. Don't move them to the top.

## Known pitfalls

- **The prompts were switched from German to English** (2026-10-11),
  including the answer keys (`seen`/`reason`, `found`, `number`). All hit
  rates in this file were measured with the German prompts. Until they are
  re-measured, treat a drop in hit rate as a possible consequence of the
  translation, not of the code.
- **A running REPL process doesn't see code changes.** In practice this led
  to "doesn't work" several times although the code was right. Telltale
  signs in the output: missing `History:` line at start,
  `/tmp/vlm_annot.png` instead of `<project>/tmp/...`, `60 candidates`
  without the `[needle ...]` suffix, or German output.
- **`Vlm.locate` reads boxes as 0..1000, not as pixels** (`LOCATE_NORM`).
  qwen3-vl answers that way even when the prompt asks for pixels — that was
  the cause of "27 px off, box beyond the image edge". Measured on a 900x600
  desktop: as pixels 1 of 6 targets hit, as 0..1000 5 of 6. The prompt
  therefore names **no** format: with "normalised to 0..1000" the model
  converts with a guessed image size in its `reasoning` and runs into the
  context limit (Ollama: 4096 tokens total, empty `content`). Empty answers
  still happen occasionally, and hits scatter despite `temperature=0` — for
  fixed targets a needle stays more deterministic.
- **The `marks` numbers sit inside the box.** Text falls apart into word
  boxes (46 candidates for an Xfce menu). Above the box the number sat under
  the row above and was assigned to it ('File Manager' instead of 'Terminal
  Emulator'); inside at the top left, numbers moved together and were read
  as one ('1' at the icon, '2' at the text of 'Applications' -> '12'). So
  `draw_marks` moves to another corner if a label would come closer than
  `GAP` to another. After that: 6 of 6 menu hits (3 targets twice each).
- **`match()` only returns the global maximum.** If an element looks the
  same several times (the × of two windows), noise in the third decimal
  place decides which wins. Remedy: cut context into the needle or restrict
  a region (`find_needle` in the archive can do that).
- **`needle_filter` computes via centres, not box edges.** `res[y][x]` is
  the *top left corner* of the hit. If the needle is larger than the
  candidate, it lies outside the box — that was a real bug and is now
  covered by the selftest.
- **Candidate numbers only hold for one frame.** The same × was #16, #17,
  #14, #33 depending on window position. That's why the history stores the
  prompt, never the number.
- **`candidate_boxes` cuts off at 60 boxes** (`out[:60]`, sorted row by row
  before) — so by *image height*, not by importance. Measured on
  `runs/20260912-104717/03_nach_dem_start.png`: 106 candidates, cut at
  `y=195`, everything below is missing. The Geany status line at `y≈464` is
  in the list as four word boxes, but behind the limit — `marks` and
  `--needle` can't get there, `ask` can.
- **The model always returns `conf` as `0.0`** — no threshold can be built
  on it.
- **`key` takes key names** from `vncdotool.keys.KEYMAP` (77 of them),
  `type` takes text. Unknown names used to run into a bare
  `TypeError: ord() expected a character...`; `cmd_key` now checks that
  beforehand.
- **The history is verbatim, the steps hang off it.** `run()` creates every
  input as `{"cmd": line, "steps": []}` *before* the command runs (except
  `META`: history/drop/export/help) — failed ones stay too. `_record()`
  appends to the running input; `steps` is a property over the history,
  `drop` removes inputs. `ask` immediately becomes an `assert`, as do
  `key`/`type`/`mouse`/`log`. `find`/`marks` only set `last_target`; only
  the `click` without coordinates carries the
  `click`/`click_marks`/`click_needle` step — the `find` line itself stays
  without one. Don't merge into a single entry, the user wants to see their
  inputs. `pick`, `click x y` and failures clear `last_target`: there's no
  repeatable prompt for them. `see` never yields a step (free text, no
  judgement).
- **`use` catches `SystemExit`.** `load_steps` and `run_steps` report errors
  via `SystemExit`; in the workbench that would end the session. The log
  goes to `tmp/use_<name>/`, not `runs/` — a by-product, not a result. Only
  on success does a step `{"type": "use", "script": name}` go into the
  history — a reference, not the steps themselves: if `openTerminal`
  changes, every script using it follows. `run_steps` only loads the script
  when executing (`script_path`), with the same `points`, unless the step
  carries `mode: nollm|llm` (the workbench only writes that for an explicit
  `use <name> nollm|llm`); `inside` holds the chain against loops, the
  caller passes its own file. `_all_points` looks into included scripts.
  `use` only fills points into the directly used file, not into included
  ones.
- **`find` with an image name searches by template, without a model**
  (`_find_needle`, threshold 0.9 like `Run.click_needle`, `--score` sets
  another one and stores it as `threshold` in the step). Recognised by
  extension (`IMAGE_EXT`), quotes are dropped; a bare name becomes
  `images/<name>` — that's how, relative, it also appears in the step file
  (`start.sh` cds into the project). `marks --needle` resolves the same way.
  `match()` only knows the global maximum, for identical-looking targets
  `marks --needle` remains.
- **Tab completion** only interactively (`_init_completion`, next to
  `_init_history`): commands at the start of the line, after `use`/`export`
  the files from `scripts/`, after `find` and `--needle` those from
  `images/`, re-read on every Tab. Separators only spaces, otherwise a `-`
  in the script name breaks completion. libedit (macOS) needs its own
  `parse_and_bind` line.
- **Negative asserts come from the majority.** If `ask` answers no by
  majority, `_record` writes `"expected": false` (`run_steps` reads
  `st.get("expected", True)`). A wrong model judgement lands in the file
  that way too — `history` marks it with `[expected: no]`, `drop` helps.
- **The VNC password is in plain text as the default** (`VNC_PASSWORD`,
  otherwise `123456`) and additionally in the `vnc` block of
  `scripts/test1.yaml`. Deliberately so for the lab setup; if the repo
  points elsewhere, it belongs out — into `config.json`, which isn't
  versioned.
- **`aiguitest-run` and the workbench catch connection errors themselves**
  (wrong password, server unreachable) and end with exit 2 and plain text
  instead of a traceback. Before connecting there's a `sys.stdout.flush()`:
  otherwise the stderr message lands before the stdout lines already
  printed.
- Server address: one colon = display number, two = actual port.

## Style

- Comments, docstrings and console output in **English**.
- **The API is English**: function, method and parameter names, return
  keys and JSON keys (`steps`, `type`, `target`, `expected`, `success`).
  The reference for it is [doc/api.md](doc/api.md), keep it up to date on
  API changes.
- **Prompts and answer formats to the model** (`ASK_SCHEMA` with
  `seen`/`reason`, `LOCATE_SCHEMA` with `found`, `{"number": ...}`) are
  English too. Change their wording only with a measurement — they decide
  the hit rate.
- **`%` formatting**, no f-strings. No type hints.
- Only stdlib + `cv2`/`numpy`/`requests`/`vncdotool`/`yaml` (PyYAML, lazily
  imported in `runner._yaml()`, for the step files); no test or CLI
  framework, `argparse` is enough.
- Intermediate images via `tmp_path("name.png")` into `<project>/tmp/`,
  never into `/tmp` and never into the root directory. `runs/<timestamp>/`
  is unaffected by this, results live there; `images/` holds versioned
  needles. `log/` (not versioned) gets the console output of every
  `aiguitest-run` (except `--selftest`) via `run_log()` and **one file per
  workbench session** (`_workbench.log`), with the inputs via
  `RunLog.note`; `use` no longer creates a log of its own. Print errors
  inside `run_log` there, don't pass them on — a traceback after the `with`
  would otherwise be missing from the log.
- Section banners of the form `# ------------ Name ---`, right-aligned to
  ~76 characters.
- Report errors that can hit the user as plain text instead of a traceback
  — and never raise `SystemExit` in the workbench, the command loop doesn't
  catch it and it ends the session including the step list.
- Comments explain the *why*, not the obvious.
