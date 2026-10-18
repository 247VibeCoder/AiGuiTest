"""Configuration and shared paths.

Everything several modules need lives here - so no module has to import
another one just for a constant.
"""

import json
import os
import sys

# Two levels up, because this file sits inside the package:
# <project>/aiguitest/config.py -> <project>
PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Where the tests live: scripts/, images/, runs/, tmp/, log/, config.json.
# Standalone that is the project itself; as a git submodule the test repo
# sets AIGUITEST_HOME to itself, so its data stays out of the submodule.
WORKSPACE = os.path.abspath(os.environ.get("AIGUITEST_HOME") or PROJECT)
CONFIG_FILE = os.path.join(WORKSPACE, "config.json")

# Allowed keys in config.json, per section. Anything else is almost always
# a typo and gets reported instead of silently ignored.
_CONFIG_KEYS = {"vnc": ("server", "password"), "vlm": ("base", "model", "key", "verify")}


def _load_config(path):
    """Read config.json; without it the built-in defaults apply."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        # At import time there is no command loop yet that would have to
        # catch this; carrying on with a broken file would mean testing
        # against the wrong server.
        raise SystemExit("%s not readable: %s" % (path, e))
    if not isinstance(data, dict):
        raise SystemExit("%s: expected a JSON object" % path)
    for section, block in data.items():
        if section not in _CONFIG_KEYS or not isinstance(block, dict):
            print("%s: unknown section '%s', ignored" % (path, section),
                  file=sys.stderr)
            continue
        for k in block:
            if k not in _CONFIG_KEYS[section]:
                print("%s: unknown key '%s.%s', ignored" % (path, section, k),
                      file=sys.stderr)
    return data


_CONFIG = _load_config(CONFIG_FILE)


def _setting(env, section, key, default):
    """Order: environment beats config.json beats default."""
    if env in os.environ:
        return os.environ[env]
    block = _CONFIG.get(section)
    if isinstance(block, dict) and key in block:
        return block[key]
    return default


# --- Target system ------------------------------------------------------
# CAUTION: one colon is the display number (:1 -> port 5901),
# two colons are the actual port.
SERVER = _setting("VNC_SERVER", "vnc", "server", "172.19.0.10::5901")
# The default is the lab password; an empty value (or null in config.json)
# means "server without password".
PASSWORD = _setting("VNC_PASSWORD", "vnc", "password", "123456") or None

# --- Vision model -------------------------------------------------------
VLM_BASE = _setting("VLM_BASE", "vlm", "base", "http://ctollama.home.arpa:11434/v1")
VLM_MODEL = _setting("VLM_MODEL", "vlm", "model", "qwen3-vl:8b")
VLM_KEY = _setting("VLM_KEY", "vlm", "key", "none")
# When True, the HTTPS call to the model endpoint skips certificate
# verification. Useful for self-signed certificates on a private host.
VLM_VERIFY = _setting("VLM_VERIFY", "vlm", "verify", True)
if isinstance(VLM_VERIFY, str):
    VLM_VERIFY = VLM_VERIFY.strip().lower() not in ("false", "0", "no", "off", "")

# The image is scaled BEFORE sending, by us. That way the factor is known
# and the box back-transformation is our code, not the server's.
MAX_SIDE = 1280

# qwen3-vl returns boxes on a fixed 0..LOCATE_NORM scale per axis,
# regardless of image size - even when the prompt asks for pixels.
# Measured on a 900x600 desktop: read as pixels, 'Terminal Emulator' landed
# at y=121 instead of 69 (factor 1000/600); read as 0..1000 it hit - 5 of 6
# targets overall versus 1 of 6 as pixels.
LOCATE_NORM = 1000

# Answer formats for the model. The hit rates in AGENTS.md were measured
# with the earlier German keys (sehe/grund/gefunden); re-measure after
# changing the wording here.
ASK_SCHEMA = '{"seen": "<what is visible, 1 sentence>", "ok": true|false, "reason": "<1 sentence>"}'
LOCATE_SCHEMA = '{"found": true|false, "box": [x1, y1, x2, y2], "conf": 0.0}'

# --- Paths --------------------------------------------------------------
# Intermediate images land in the project, not in /tmp: that way they sit
# next to the runs and survive a reboot.
TMPDIR = os.path.join(WORKSPACE, "tmp")


def tmp_path(name):
    """Path in <workspace>/tmp/; the directory is created on demand."""
    os.makedirs(TMPDIR, exist_ok=True)
    return os.path.join(TMPDIR, name)


# Step files: YAML, .json only read for older files. The order decides
# which file a bare name resolves to.
SCRIPTS = os.path.join(WORKSPACE, "scripts")
SCRIPT_EXT = (".yaml", ".yml", ".json")

# When this repo is consumed as a submodule (path "AiGuiTest" inside the
# outer test repo), the outer repo's scripts/ is the workspace but users
# still want to reach the demo scripts shipped here. Subdirectory lookup
# searches both folders - the workspace first, then the sibling AiGuiTest/
# in case it is mounted as a submodule next to scripts/.
SCRIPT_DIRS = tuple(d for d in (
    SCRIPTS,
    os.path.join(WORKSPACE, "AiGuiTest", "scripts"),
) if os.path.isdir(d))


def script_path(name):
    """'openTerminal' -> scripts/openTerminal.yaml, paths stay as they are.

    Without an extension the first existing one from SCRIPT_EXT wins, so a
    bare name also finds an old .json; new files are always .yaml. All
    SCRIPT_DIRS are searched in order so the same bare name resolves the
    same way in the workbench's 'use' and in aiguitest-run. A workspace-
    relative path like 'scripts/foo.yaml' is anchored at SCRIPTS too, so
    the shell's cwd never enters the lookup.
    """
    scripts_dir = os.path.basename(SCRIPTS)
    if not name:
        return name
    if os.path.dirname(name):
        if os.path.dirname(name) == scripts_dir:
            bare = os.path.basename(name)
            name = bare
        else:
            return name
    if not os.path.splitext(name)[1]:
        base = name
        for ext in SCRIPT_EXT:
            for d in SCRIPT_DIRS:
                cand = os.path.join(d, base + ext)
                if os.path.exists(cand):
                    return cand
        name = base + ".yaml"
    if not os.path.dirname(name):
        name = os.path.join(SCRIPTS, name)
    return name


# Sibling of SCRIPTS: same rationale - the submodule's images/ is visible
# as a fallback so YAML step files written against the demo (click_needle
# images/close.png) keep working inside an outer test repo.
IMAGES = os.path.join(WORKSPACE, "images")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp")
IMAGE_DIRS = tuple(d for d in (
    IMAGES,
    os.path.join(WORKSPACE, "AiGuiTest", "images"),
) if os.path.isdir(d))


def image_path(name):
    """'close.png' -> images/close.png (any IMAGE_DIRS that has it).

    A bare name is searched in every IMAGE_DIRS. A workspace-relative
    path like 'images/close.png' is anchored at IMAGES so the shell's
    current directory does not leak into the lookup - the workspace is
    always the source of truth for relative paths.
    """
    if not name:
        return name
    images_dir = os.path.basename(IMAGES)
    if not os.path.dirname(name):
        bare = name
    elif os.path.dirname(name) == images_dir:
        bare = os.path.basename(name)
    else:
        # An explicitly prefixed path the user really meant, e.g.
        # 'AiGuiTest/images/close.png' - leave it alone, the caller is
        # responsible for the cwd here.
        return name

    if not os.path.splitext(bare)[1]:
        for ext in IMAGE_EXT:
            for d in IMAGE_DIRS:
                cand = os.path.join(d, bare + ext)
                if os.path.exists(cand):
                    return cand
    for d in IMAGE_DIRS:
        cand = os.path.join(d, bare)
        if os.path.exists(cand):
            return cand
    return os.path.join(IMAGES, name)


# Text log per run, independent of the run folder: runs/ holds images and
# run.json, log/ the console output - also of 'use' in the workbench.
LOGDIR = os.path.join(WORKSPACE, "log")


def log_path(name):
    """Path in <workspace>/log/; the directory is created on demand."""
    os.makedirs(LOGDIR, exist_ok=True)
    return os.path.join(LOGDIR, name)
