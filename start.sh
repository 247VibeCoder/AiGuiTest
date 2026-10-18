#!/usr/bin/env bash
# Starts a project script in its own virtual environment.
# Without a script name aiguitest-run runs; all further arguments are
# passed through:
#
#   ./start.sh                                      # = aiguitest-run
#   ./start.sh aiguitest-run --selftest
#   ./start.sh scripts/test1.yaml                   # = aiguitest-run scripts/test1.yaml
#   ./start.sh aiguitest-workbench --fake --image image.png
#   ./start.sh archiv/vnc_test.py --wait 3
#
# As a submodule of a test repo, set AIGUITEST_HOME to that repo: scripts/,
# images/, runs/, tmp/, log/ and config.json are then taken from there.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$DIR/.venv"
DEPS="vncdotool opencv-python-headless numpy requests pyyaml"
INDEX="${PIP_INDEX_URL:-https://pypi.org/simple/}"

# Fetch pip from a wheel on the package index - needed when python3-venv
# (ensurepip) is missing and no sudo apt is wanted.
bootstrap_pip() {
    python3 - "$INDEX" "$VENV" <<'EOF'
import re, subprocess, sys, tempfile, urllib.request
from urllib.parse import urljoin

index, venv = sys.argv[1], sys.argv[2]
page_url = urljoin(index if index.endswith("/") else index + "/", "pip/")
html = urllib.request.urlopen(page_url, timeout=60).read().decode()

wheels = {}
for href in re.findall(r'href="([^"]+)"', html):
    m = re.search(r"pip-(\d+(?:\.\d+)*)-py3-none-any\.whl", href)
    if m:
        wheels[tuple(map(int, m.group(1).split(".")))] = urljoin(page_url, href.split("#")[0])
if not wheels:
    sys.exit("No pip wheel found at %s" % page_url)

url = wheels[max(wheels)]
with tempfile.TemporaryDirectory() as tmp:
    whl = "%s/%s" % (tmp, url.rsplit("/", 1)[1])
    urllib.request.urlretrieve(url, whl)
    subprocess.check_call([venv + "/bin/python", whl + "/pip", "install", "-q", whl])
EOF
}

# create the venv on first start and install the dependencies
if [ ! -x "$VENV/bin/pip" ]; then
    echo "Creating virtual environment in $VENV ..."
    rm -rf "$VENV"
    if ! python3 -m venv "$VENV" >/dev/null 2>&1; then
        echo "ensurepip missing - fetching pip from $INDEX"
        rm -rf "$VENV"
        python3 -m venv --without-pip "$VENV"
        bootstrap_pip
    fi
    "$VENV/bin/pip" install -q $DEPS
fi

# Since the step files are YAML: older venvs get PyYAML added
if ! "$VENV/bin/python" -c "import yaml" 2>/dev/null; then
    echo "Installing pyyaml ..."
    "$VENV/bin/pip" install -q pyyaml
fi

# A first argument naming a file in the project selects the script.
# Don't check for '.py': the CLIs are called aiguitest-run and
# aiguitest-workbench, without an extension.
SCRIPT="aiguitest-run"
case "${1:-}" in
    "" | -*)
        ;;                      # nothing given or an option right away
    *.yaml | *.yml | *.json)
        # A step file is not a script: Python would otherwise run it as code
        # and fail. It goes to aiguitest-run.
        ;;
    *)
        if [ -f "$DIR/$1" ]; then
            SCRIPT="$1"
            shift
        else
            # Don't silently fall back to the default: a typo would
            # otherwise start the wrong program unnoticed.
            echo "No such script: $1" >&2
            exit 2
        fi
        ;;
esac

if [ ! -f "$DIR/$SCRIPT" ]; then
    echo "No such script: $SCRIPT" >&2
    exit 2
fi

# Relative paths in step files (images/close.png, runs/...) mean the
# workspace: the project itself, or the test repo that uses this one as a
# submodule and sets AIGUITEST_HOME.
WORK="${AIGUITEST_HOME:-$DIR}"
if [ ! -d "$WORK" ]; then
    echo "AIGUITEST_HOME is not a directory: $WORK" >&2
    exit 2
fi
cd "$WORK"
exec "$VENV/bin/python" "$DIR/$SCRIPT" "$@"
