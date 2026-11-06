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

# Where the tests live: tests/, images/, runs/, tmp/, log/, config.json.
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
VLM_BASE = _setting("VLM_BASE", "vlm", "base", "http://ctollama.example.com:11434/v1")
VLM_MODEL = _setting("VLM_MODEL", "vlm", "model", "qwen3-vl:8b")
VLM_KEY = _setting("VLM_KEY", "vlm", "key", "none")
# How the HTTPS call to the model endpoint checks the certificate. True uses
# certifi's bundle, which doesn't know private CAs - for those, give the path
# of a CA file. False skips the check, and the key then goes out unprotected.
VLM_VERIFY = _setting("VLM_VERIFY", "vlm", "verify", True)
if isinstance(VLM_VERIFY, str):
    _verify = VLM_VERIFY.strip()
    if _verify.lower() in ("false", "0", "no", "off", ""):
        VLM_VERIFY = False
    elif _verify.lower() in ("true", "1", "yes", "on"):
        VLM_VERIFY = True
    else:
        VLM_VERIFY = _verify
        if not os.path.isfile(_verify):
            print("vlm.verify: no such CA file: %s" % _verify, file=sys.stderr)

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


# Tests: pytest files (test_*.py) under tests/ of the workspace.
TESTS = os.path.join(WORKSPACE, "tests")


def test_path(name):
    """'login' -> tests/test_login.py, paths stay as they are.

    A bare name may also be the file name itself ('test_login',
    'test_login.py'); pytest's node ids ('tests/x.py::test_a') pass through.
    """
    if not name or os.path.dirname(name.split("::")[0]) or "::" in name:
        return name
    base = name[:-3] if name.endswith(".py") else name
    for cand in (base, "test_" + base):
        path = os.path.join(TESTS, cand + ".py")
        if os.path.exists(path):
            return path
    if not base.startswith("test_"):
        base = "test_" + base
    return os.path.join(TESTS, base + ".py")


# The submodule's images/ is visible as a fallback, so tests written
# against the demo images (images/close.png) keep working inside an outer
# test repo.
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

    # IMAGES first even if it did not exist at import time - the editor
    # bridge creates it with the first crop, after this module was loaded
    dirs = (IMAGES,) + tuple(d for d in IMAGE_DIRS if d != IMAGES)
    if not os.path.splitext(bare)[1]:
        for ext in IMAGE_EXT:
            for d in dirs:
                cand = os.path.join(d, bare + ext)
                if os.path.exists(cand):
                    return cand
    for d in dirs:
        cand = os.path.join(d, bare)
        if os.path.exists(cand):
            return cand
    return os.path.join(IMAGES, name)


# Text log per run, independent of the run folder: runs/ holds images and
# run.json, log/ the console output of aiguitest-run.
LOGDIR = os.path.join(WORKSPACE, "log")


def log_path(name):
    """Path in <workspace>/log/; the directory is created on demand."""
    os.makedirs(LOGDIR, exist_ok=True)
    return os.path.join(LOGDIR, name)
