"""Key names: readable names -> vncdotool, and key sequences.

Tests write keys as identifiers (ControlKey, Enter, WindowsKey), vncdotool
as short names from its KEYMAP (ctrl, enter, super). This module
translates the one into the other and turns a TypeText list such as
[ControlKey, "c"] into the key presses vncdotool expects.

Imports nothing from the package - like config and marks, a bottom layer.
"""

import re
import time

# Lower-cased key name, with a trailing "key" removed -> vncdotool name.
# vncdotool's own names (ctrl, bsp, pgdn ...) also resolve, they are simply
# passed through by resolve_key.
_NAMES = {
    "enter": "enter", "return": "return", "tab": "tab",
    "escape": "esc", "esc": "esc",
    "backspace": "bsp", "delete": "delete", "del": "delete",
    "forwarddelete": "delete", "insert": "ins",
    "home": "home", "end": "end",
    "pageup": "pgup", "pagedown": "pgdn",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "uparrow": "up", "downarrow": "down",
    "leftarrow": "left", "rightarrow": "right",
    "space": "space", "spacebar": "space",
    "capslock": "caplk", "numlock": "numlk", "scrolllock": "scrlk",
    "pause": "pause", "printscreen": "sysrq",
    "numpadenter": "kpenter",
    # modifiers
    "control": "ctrl", "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt", "option": "alt",
    "windows": "super", "win": "super", "command": "super", "cmd": "super",
    "super": "super", "meta": "meta",
}
for _i in range(1, 21):
    _NAMES["f%d" % _i] = "f%d" % _i

# Modifiers combine with the next item of a key sequence instead of being
# pressed on their own: [ControlKey, "c"] is ctrl-c, not ctrl then c.
MODIFIERS = ("ctrl", "shift", "alt", "super", "meta",
             "lctrl", "rctrl", "lshift", "rshift", "lalt", "ralt",
             "lsuper", "rsuper", "lmeta", "rmeta")


def _norm(name):
    n = re.sub(r"[\s_]", "", str(name)).lower()
    if n.endswith("key") and len(n) > 3:
        n = n[:-3]
    return n


def key_name(name):
    """vncdotool name for a key name like ControlKey, or None if it isn't one.

    'ControlKey' -> 'ctrl', 'Enter' -> 'enter', 'PageDown' -> 'pgdn'.
    Single characters are never key names here - "c" is text.
    """
    if not isinstance(name, str) or len(name) <= 1:
        return None
    return _NAMES.get(_norm(name))


def resolve_key(k):
    """Translate a key for session.key(): key names and chords.

    'Enter' -> 'enter', 'ControlKey-c' -> 'ctrl-c', a list such as
    ['ControlKey', 'ShiftKey', 't'] -> 'ctrl-shift-t'. Names vncdotool
    already knows ('ctrl-alt-t', 'f4', 'a') stay as they are, so old
    run.json files replay unchanged.
    """
    if isinstance(k, (list, tuple)):
        parts = [str(p) for p in k]
    elif len(k) > 1 and "-" in k.strip("-"):
        parts = k.split("-")
    else:
        name = key_name(k)
        return name or k            # single char or unknown: unchanged
    out = []
    for p in parts:
        name = key_name(p)
        if name:
            out.append(name)
        elif p == "-":
            out.append("minus")
        elif len(p) == 1 and p.isupper():
            out += ["shift", p.lower()]
        else:
            out.append(p)
    return "-".join(out)


def key_sequence(items):
    """TypeText list -> [("text", str) | ("key", name), ...].

    A list item that is a key name is a key, every other item is text.
    Modifiers combine with the item that follows them: the first character
    of a text, or a key. ["Hallo", Enter] types "Hallo" and presses enter;
    [WindowsKey, "r"] presses super-r; [ControlKey, ShiftKey, Escape]
    presses ctrl-shift-esc. A modifier at the very end is pressed alone.
    """
    if isinstance(items, str):
        return [("text", items)] if items else []
    out, held = [], []
    for item in items:
        item = "" if item is None else str(item)
        name = key_name(item)
        if name in MODIFIERS:
            held.append(name)
            continue
        if name:
            out.append(("key", "-".join(held + [name])))
        elif held and item:
            first, rest = item[0], item[1:]
            mods = list(held)
            if first.isupper():
                if "shift" not in mods:
                    mods.append("shift")
                first = first.lower()
            out.append(("key", "-".join(mods + ["minus" if first == "-" else first])))
            if rest:
                out.append(("text", rest))
        elif item:
            out.append(("text", item))
        held = []
    if held:
        out.append(("key", "-".join(held)))
    return out


def send_sequence(session, items, delay=0.1):
    """Press/type a key_sequence() on a session (VncSession, ImageSource)."""
    for kind, value in key_sequence(items):
        if kind == "key":
            session.key(value)
        else:
            session.type_text(value)
        time.sleep(delay)
