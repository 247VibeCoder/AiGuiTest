"""pytest plugin: every test gets a Run the commands act on.

    aiguitest-run                          # all of tests/, plugin loaded
    pytest -p aiguitest.pytest_plugin tests/

One VNC connection for the whole session - vncdotool connects only once
per process. Per test:

- a Run logging to runs/<session timestamp>/<test>/ (run.json, images),
  so 'aiguitest-run --replay runs/<ts>/<test>' repeats it without a model;
- on failure a screenshot of the moment (error.png);
- LogError() lets the test go on and fails it at the end;
- a model endpoint that is down (VlmError) shows as its plain-text report,
  not as a traceback through requests.

After every test, each point a text target was found at anew (or moved
to) is written back into the test source as point=(x, y) - see
points.py. Per test, not at the end: a debug session that is stopped
never reaches the end.

Options: --vnc HOST::PORT, --vnc-password, --nollm (text targets only by
their remembered point and reference image, never by the model), --image PNG (a screenshot instead of VNC,
clicks go nowhere - for trying a test offline), --fake-vlm (answers
without a model, together with --image).
"""

import os
import time

import pytest

from .config import PASSWORD, SERVER, WORKSPACE
from .runner import Run, _slug
from .commands import bind, unbind
from .points import write_points


def pytest_addoption(parser):
    g = parser.getgroup("aiguitest")
    g.addoption("--vnc", default=None,
                help="VNC server, beats config.json and VNC_SERVER "
                     "(one colon: display, two: port)")
    g.addoption("--vnc-password", default=None)
    g.addoption("--nollm", action="store_true",
                help="text targets only by their remembered point and "
                     "reference image, never by the model (fails instead); "
                     "asserts still ask it")
    g.addoption("--image", default=None,
                help="a PNG instead of VNC - try a test offline")
    g.addoption("--fake-vlm", action="store_true",
                help="answer without a model (with --image)")
    g.addoption("--runs", default=None,
                help="folder for the run logs, default runs/<timestamp>")


def pytest_configure(config):
    # files changed after this are not rewritten: their lines moved
    config._aiguitest_started = time.time()
    config._aiguitest_points = []
    config._aiguitest_written = {}       # write_points' state across tests
    config._aiguitest_report = []
    config.addinivalue_line("markers", "aiguitest: a GUI test (all tests "
                            "here are; the marker is for selection only)")
    # vncdotool's VNC login uses TripleDES; nothing a test can act on
    config.addinivalue_line("filterwarnings",
                            "ignore:TripleDES has been moved")
    config._aiguitest_answers = []


@pytest.fixture(scope="session")
def aiguitest_session(request):
    """The desktop under test - one connection for all tests."""
    opt = request.config.getoption
    if opt("image"):
        from .vnc import ImageSource
        session = ImageSource(opt("image"))
    else:
        from .vnc import VncSession
        server = opt("vnc") or SERVER
        try:
            session = VncSession(server, opt("vnc_password") or PASSWORD)
        except Exception as e:
            # wrong password, server down: plain text, not a traceback
            pytest.exit("No VNC connection to %s\n  %s: %s\n  Check --vnc, "
                        "config.json or VNC_SERVER/VNC_PASSWORD."
                        % (server, type(e).__name__, e), returncode=2)
    yield session
    session.close()


@pytest.fixture(scope="session")
def aiguitest_vlm(request):
    if request.config.getoption("fake_vlm"):
        from .vlm import FakeVlm
        return FakeVlm()
    from .vlm import Vlm
    return Vlm()


@pytest.fixture(scope="session")
def aiguitest_runs(request):
    """runs/<timestamp>/ - one folder per session, one below per test."""
    return request.config.getoption("runs") or os.path.join(
        WORKSPACE, "runs", time.strftime("%Y%m%d-%H%M%S"))


@pytest.fixture(autouse=True)
def gui(request, aiguitest_session, aiguitest_vlm, aiguitest_runs):
    """The Run of this test; the commands act on it."""
    run = Run(aiguitest_session, aiguitest_vlm,
              os.path.join(aiguitest_runs, _slug(request.node.name)))
    request.node._aiguitest_run = run
    prev = bind(run, nollm=request.config.getoption("nollm"))
    try:
        yield run
    finally:
        unbind(prev)
        request.config._aiguitest_answers += [
            (request.node.name, s["question"], s["answer"])
            for s in run.steps if s["type"] == "describe"]
        _write_points(request.config, run.point_updates)
        rep = getattr(request.node, "_aiguitest_call", None)
        if rep is not None and rep.failed and not run.errors:
            # LogError already saved one; an assert or a missing target not
            path = run.error_screenshot()
            if path:
                print("Screenshot of the error: %s" % path)
        print("Run log: %s" % run.save())


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    if rep.when != "call":
        return
    item._aiguitest_call = rep
    run = getattr(item, "_aiguitest_run", None)
    if call.excinfo is not None:
        from .vlm import VlmError
        if call.excinfo.errisinstance(VlmError):
            # the report already says what is wrong and where to look
            rep.longrepr = str(call.excinfo.value)
        return
    if run is not None and run.errors and rep.passed:
        rep.outcome = "failed"
        rep.longrepr = "%d error(s) logged:\n%s" % (
            len(run.errors), "\n".join("  - %s" % e for e in run.errors))


def _write_points(config, updates):
    """Remembered points into the sources, after every test - a debug
    session stopped halfway (no session end) keeps what it learned, and
    a failed test's points up to the failure are right too."""
    config._aiguitest_points.extend(updates)
    if config._aiguitest_points:
        config._aiguitest_report = write_points(
            config._aiguitest_points, config._aiguitest_started,
            config._aiguitest_written)


def pytest_terminal_summary(terminalreporter, config):
    # pytest hides what a passing test prints; these are what it was run for
    answers = config._aiguitest_answers
    if answers:
        terminalreporter.section("model answers")
        for test, question, answer in answers:
            terminalreporter.line("%s: %s" % (test, question))
            terminalreporter.line("  %s" % answer)
    report = getattr(config, "_aiguitest_report", None)
    if report:
        terminalreporter.section("aiguitest: remembered points")
        for line in report:
            terminalreporter.write_line(line)


def pytest_report_header(config):
    if config.getoption("image"):
        where = "image %s" % config.getoption("image")
    else:
        where = "VNC %s" % (config.getoption("vnc") or SERVER)
    return "aiguitest: %s%s" % (where, ", nollm" if config.getoption("nollm")
                                else "")


# ---------------------------------------------------------- Selftest --

_DEMO = '''
import warnings

from aiguitest import *

def test_ok():
    assert ImageFound("OkButton")
    Click("OkButton")
    assert Click("OkButton", threshold=1.01, timeout=0) is None
    TypeText("hallo", Enter)

def test_logerror():
    warnings.warn("TripleDES has been moved")
    Describe()
    LogError("something is off")
    Log("goes on")

def test_missing():
    Click("OkButton", threshold=1.01, timeout=0, required=True)

def press_ok():
    Click(text="the OK button")

def test_point():
    press_ok()

def test_point_again():
    press_ok()
'''


def selftest():
    """The plugin in a pytest run of its own: an offline workspace with a
    PNG desktop - pass, LogError, a missing target, and a text target
    whose point is written into the test and then holds under --nollm."""
    import json
    import shutil
    import subprocess
    import sys

    import cv2
    import numpy as np

    from .config import PROJECT, tmp_path

    ws = tmp_path("_plugin_ws")
    shutil.rmtree(ws, ignore_errors=True)
    os.makedirs(os.path.join(ws, "tests"))
    os.makedirs(os.path.join(ws, "images"))
    try:
        desk = np.full((300, 400, 3), 40, np.uint8)
        cv2.rectangle(desk, (200, 100), (240, 130), (255, 255, 255), -1)
        cv2.putText(desk, "OK", (205, 122), 0, 0.6, (0, 0, 0), 2)
        cv2.imwrite(os.path.join(ws, "desk.png"), desk)
        cv2.imwrite(os.path.join(ws, "images", "OkButton.png"),
                    desk[96:134, 196:244])
        with open(os.path.join(ws, "tests", "test_demo.py"), "w") as f:
            f.write(_DEMO)
        env = dict(os.environ, AIGUITEST_HOME=ws, PYTHONPATH=PROJECT)
        runs = os.path.join(ws, "runs")
        def pytest(*extra):
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "-p", "aiguitest.pytest_plugin",
                 "-p", "no:cacheprovider", "--rootdir", ws, "-q",
                 "--image", os.path.join(ws, "desk.png"), "--fake-vlm",
                 "--runs", runs, os.path.join(ws, "tests")] + list(extra),
                cwd=ws, env=env, capture_output=True, text=True, timeout=300)
            return proc.stdout + proc.stderr
        out = pytest()
        assert "3 passed" in out and "2 failed" in out, out
        assert "1 error(s) logged" in out, out
        assert "warnings summary" not in out, out
        assert "model answers" in out and "Fake answer" in out, out
        with open(os.path.join(runs, "test_ok", "run.json")) as f:
            steps = json.load(f)["steps"]
        assert [s["type"] for s in steps] == ["image_found", "click", "click",
                                              "type"], steps
        assert steps[2]["success"] is False and steps[2]["required"] is False
        assert os.path.exists(os.path.join(runs, "test_missing", "error.png"))
        with open(os.path.join(ws, "tests", "test_demo.py")) as f:
            src = f.read()
        assert src.count('Click(text="the OK button", point=(') == 1, out + src
        assert os.listdir(os.path.join(ws, "images", "points")), out
        # the second test reaches the helper with the point learned in the
        # first one - the loaded code still has none
        with open(os.path.join(runs, "test_point_again", "run.json")) as f:
            again = json.load(f)["steps"]
        assert again[0].get("via") == "point", again
        out = pytest("--nollm", "-k", "test_point")
        assert "2 passed" in out, out
        print("pytest plugin: 3 passed, 2 failed as expected, run.json per "
              "test, a point written back after the first test, reused by "
              "the second and held under --nollm")
    finally:
        shutil.rmtree(ws, ignore_errors=True)
