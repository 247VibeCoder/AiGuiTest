"""Remembered points: the point of a text= target, checked, written back.

    Click(text="the OK button", point=(412, 87))

The point stays in the test. Next to it, images/points/<text>.png holds
what the element looked like there (the reference image). A run checks
the reference image around the point by template - a hit is a click
without the model; if the element moved, the new place is clicked; if it
changed, the model searches again. Every point that was found anew is
written back into the source after each test (write_points), so the next
run is fast again.

Imports nothing from the package but config - runner and the pytest
plugin use it.
"""

import ast
import hashlib
import os
import re

from .config import IMAGES, WORKSPACE

POINTS_DIR = os.path.join(IMAGES, "points")

# Template score from which the reference image counts as 'the same
# element'; the same threshold as image targets.
THRESHOLD = 0.9

# A point found within this distance of the one in the source is not
# written back - noise in the template match, not a move.
TOLERANCE = 3

# Points learned in this process, by call site. The source on disk is
# rewritten, but the code already loaded still holds the old point - so a
# second test calling the same helper, or a line run again in the
# debugger, starts from what was learned instead of asking the model.
LEARNED = {}


def site_key(site):
    return (site["file"], site["lineno"], site.get("col")) if site else None


def reference_path(text, base=None):
    """images/points/<slug>_<hash>.png for a description.

    The slug keeps it readable, the hash tells two long descriptions
    with the same beginning apart. A changed description has no
    reference image yet - so the model searches it once.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48] or "point"
    tag = hashlib.sha1(text.encode("utf-8")).hexdigest()[:6]
    return os.path.join(base or POINTS_DIR, "%s_%s.png" % (slug, tag))


def call_site(skip_dir):
    """Where the test called the command: {file, lineno, col, ...} or None.

    The first frame outside 'skip_dir' (the package) - a call inside a
    helper like open_terminal() is that helper's line, so the point lands
    where the call is written. Only files in the workspace count; a test
    library elsewhere is never rewritten.
    """
    import inspect
    skip_dir = os.path.abspath(skip_dir)
    f = inspect.currentframe()
    while f is not None:
        path = os.path.abspath(f.f_code.co_filename)
        if os.path.dirname(path) != skip_dir:
            break
        f = f.f_back
    if f is None or not path.endswith(".py"):
        return None
    if not path.startswith(os.path.abspath(WORKSPACE) + os.sep):
        return None
    site = {"file": path, "lineno": f.f_lineno}
    pos = getattr(inspect.getframeinfo(f), "positions", None)   # 3.11+
    if pos is not None and pos.lineno:
        site.update(lineno=pos.lineno, col=pos.col_offset,
                    end_lineno=pos.end_lineno, end_col=pos.end_col_offset)
    return site


# ----------------------------------------------------- source rewrite --

def _call_at(tree, site):
    """The Call node the site points at, or None."""
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    if site.get("col") is not None:
        for n in calls:
            if (n.lineno, n.col_offset, n.end_lineno, n.end_col_offset) == (
                    site["lineno"], site["col"], site["end_lineno"],
                    site["end_col"]):
                return n
    # older Pythons: the innermost call with keywords on that line
    near = [n for n in calls if n.lineno <= site["lineno"] <= n.end_lineno
            and n.keywords]
    return min(near, key=lambda n: n.end_lineno - n.lineno) if near else None


def _edit(node, point):
    """(start, end, bytes) for 'point=(x, y)' in this call - ast columns
    are UTF-8 byte offsets, so the edit works on bytes."""
    text = b"(%d, %d)" % (point[0], point[1])
    for kw in node.keywords:
        if kw.arg == "point":
            v = kw.value
            return ((v.lineno, v.col_offset), (v.end_lineno, v.end_col_offset),
                    text)
    last = max(list(node.args) + [k.value for k in node.keywords],
               key=lambda n: (n.end_lineno, n.end_col_offset))
    at = (last.end_lineno, last.end_col_offset)
    return at, at, b", point=" + text


def write_points(updates, since=None, state=None):
    """Write the points of 'updates' into the sources -> report lines.

    updates: [{"site": call_site(), "point": [x, y], "old": [x, y] or None,
    "text": str}]. A site that got two different points in one run (a
    loop over different elements) is left alone. A file changed after
    'since' (a time stamp - edited during the run) is not touched either:
    its line numbers may no longer be the ones that ran.

    state: a dict kept across calls, for writing after every test. The
    sites refer to the source as it was loaded, so every call edits that
    original again with all updates so far; a file whose content is no
    longer what the last call wrote was edited by someone else and stays
    as it is.
    """
    state = {} if state is None else state
    by_site, clash = {}, set()
    for u in updates:
        site = u.get("site")
        if not site:
            continue
        key = site_key(site)
        if key in by_site and by_site[key]["point"] != list(u["point"]):
            clash.add(key)
        by_site.setdefault(key, dict(u, point=list(u["point"])))
    report = []
    files = {}
    for key, u in sorted(by_site.items()):
        files.setdefault(key[0], []).append((key, u))
    for path, items in sorted(files.items()):
        rel = os.path.relpath(path, WORKSPACE)
        with open(path, "rb") as f:
            current = f.read()
        mine = state.get(path)
        if mine is not None:
            changed = current != mine["written"]
        else:
            changed = since is not None and os.path.getmtime(path) > since
        if changed:
            for key, u in items:
                report.append("%s:%d: not written (file changed during the "
                              "run) - point=(%d, %d)" % (rel, key[1], *u["point"]))
            continue
        src = mine["orig"] if mine is not None else current
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.splitlines(keepends=True)
        edits = []
        for key, u in items:
            if key in clash:
                report.append("%s:%d: not written - different points in one "
                              "run (a loop?)" % (rel, key[1]))
                continue
            node = _call_at(tree, u["site"])
            if node is None:
                report.append("%s:%d: call not found, point=(%d, %d)"
                              % (rel, key[1], *u["point"]))
                continue
            edits.append(_edit(node, u["point"]))
            old = u.get("old")
            report.append("%s:%d: '%s' %s (%d, %d)" % (
                rel, key[1], u.get("text", ""),
                "moved from (%d, %d) to" % tuple(old) if old else "new point",
                *u["point"]))
        if not edits:
            continue
        out = _apply(lines, edits)
        try:
            ast.parse(out)
        except SyntaxError:          # never leave a broken test behind
            report.append("%s: edit would break the file, not written" % rel)
            continue
        if out != current:
            with open(path, "wb") as f:
                f.write(out)
        state[path] = {"orig": src, "written": out}
    return report


def _apply(lines, edits):
    """Apply (start, end, text) edits, last first, to a list of byte lines."""
    lines = list(lines)
    for (sl, sc), (el, ec), text in sorted(edits, reverse=True):
        head = lines[sl - 1][:sc]
        tail = lines[el - 1][ec:]
        lines[sl - 1:el] = [head + text + tail]
    return b"".join(lines)


def selftest():
    """write_points on a file of its own: insert, replace, multi-line,
    a non-ASCII character before the call, a clash."""
    import time
    from .config import tmp_path

    path = tmp_path("_points_test.py")
    src = ('# Grüße\n'
           'def test_a():\n'
           '    Click(text="the ä button")\n'
           '    DoubleClick(text="the X",\n'
           '                point=(1, 2))\n'
           '    Click(text="t", timeout=5,\n'
           '    )\n'
           '    Click(text="loop")\n')
    with open(path, "w", encoding="utf-8") as f:
        f.write(src)
    tree = ast.parse(src)
    calls = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call)),
                   key=lambda n: n.lineno)

    def site(n):
        return {"file": path, "lineno": n.lineno, "col": n.col_offset,
                "end_lineno": n.end_lineno, "end_col": n.end_col_offset}
    ups = [{"site": site(calls[0]), "point": [10, 20], "old": None},
           {"site": site(calls[1]), "point": [30, 40], "old": [1, 2]},
           {"site": site(calls[2]), "point": [5, 6], "old": None},
           {"site": site(calls[3]), "point": [1, 1], "old": None},
           {"site": site(calls[3]), "point": [2, 2], "old": None}]
    try:
        report = write_points(ups, since=time.time() + 60)
        with open(path, encoding="utf-8") as f:
            out = f.read()
        assert 'Click(text="the ä button", point=(10, 20))' in out, out
        assert "point=(30, 40))" in out and "(1, 2)" not in out, out
        assert 'Click(text="t", timeout=5, point=(5, 6),\n    )' in out, out
        assert 'Click(text="loop")\n' in out, out
        assert any("different points" in r for r in report), report
        n = len(report) - 1

        # after every test: the sites stay those of the loaded source
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)
        state = {}
        write_points(ups[:1], since=time.time() + 60, state=state)
        write_points(ups[:1] + [dict(ups[0], point=[10, 20]), ups[2]],
                     since=time.time() + 60, state=state)
        with open(path, encoding="utf-8") as f:
            out = f.read()
        assert out.count("point=(10, 20)") == 1, out
        assert "timeout=5, point=(5, 6)" in out, out
        with open(path, "a", encoding="utf-8") as f:
            f.write("# edited by hand\n")
        report = write_points(ups[:3], since=time.time() + 60, state=state)
        assert all("not written" in r for r in report), report
        print("points: %d written, the loop left alone, after every test "
              "too" % n)
    finally:
        os.remove(path)
