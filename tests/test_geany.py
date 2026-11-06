"""Start Geany from a terminal and close both windows again.

The former scripts/test1.yaml.
"""

from aiguitest import *


def test_geany_from_the_terminal():
    TypeText(ControlKey, AltKey, "t")           # Xfce: new terminal
    WaitFor(text="a terminal window with a shell prompt", timeout=20)
    TypeText("geany &", Enter)
    CaptureScreen("after_the_start")

    Assert("Is the window of the text editor Geany open?")
    Assert('Does the Geany window show the line "This is Geany 2.0"?')

    ClickMarks("the close button (X) in the title bar of the Geany window",
               needle="images/close.png")
    Assert("Is the window of the text editor Geany still visible?",
           expected=False)

    ClickMarks("the close button (X) in the title bar of the terminal window",
               needle="images/close.png")
    CaptureScreen("at_the_end")
