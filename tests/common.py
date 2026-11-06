"""Building blocks the tests share - plain functions instead of 'use'."""

from aiguitest import *


def open_terminal():
    """Xfce: Applications menu -> Terminal Emulator.

    The points were recorded on the lab desktop. Their reference images
    in images/points/ come from the first run with the model; after that
    the points are checked by template and corrected in this file when
    the menu moves.
    """
    Click(text="the Applications button at the top left", point=(60, 14))
    Click(text="the 'Terminal Emulator' entry of the menu", point=(77, 71))
    WaitFor(text="a terminal window with a shell prompt", timeout=20)


def close_window(which):
    """Click the X of a window - the template narrows, the model picks."""
    MoveTo((0, 0))       # no hover effect on the X we are looking for
    Click(image="close", text="the close button (X) in the title bar of "
                              "the %s window" % which)
