"""Open a terminal, start xeyes, close the terminal - xeyes must survive.

The former xeyes demo script and the built-in scenario.
"""

from aiguitest import *
from common import close_window, open_terminal


def test_xeyes_survives_the_terminal():
    open_terminal()
    TypeText("xeyes &", Enter)

    # wait for xeyes, at most five rounds
    rounds = 0
    while not Ask("Is a small window with two drawn eyes visible?"):
        rounds += 1
        assert rounds < 5, "xeyes did not show up"
        Wait(1)
    Log("xeyes visible after %d round(s)" % rounds)

    # close the terminal via its X; if that fails, type exit instead
    try:
        close_window("TERMINAL (not the xeyes one)")
    except AssertionError as e:
        LogWarning("closing by click failed (%s) - typing exit" % e)
        TypeText("exit", Enter)
    WaitWhile(text="a terminal window with a shell prompt", timeout=15)

    if Ask("Is the xeyes window with the two eyes still visible?"):
        Log("xeyes survived the terminal")
    else:
        LogError("xeyes was closed together with the terminal")
    CaptureScreen("at_the_end")
