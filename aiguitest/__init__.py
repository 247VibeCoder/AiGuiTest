"""aiguitest - semantic GUI tests over VNC with a vision LLM.

Layers (bottom to top):

    config     constants and paths, imports nothing from the package
    keys       key names (ControlKey, Enter) -> vncdotool, TypeText sequences
    marks      image analysis: candidate_boxes, needle_filter, draw_marks, match
    vnc        image sources: VncSession (real desktop), ImageSource (PNG)
    vlm        model access: Vlm.ask/locate/raw, FakeVlm as test double
    runner     Run (the actions and their log), replay, selftest
    commands   the commands tests are written in: Click, TypeText, ...
    pytest_plugin  one Run per test, bound for the commands

Tests are pytest files under tests/: 'from aiguitest import *' brings the
commands and the key constants - only those; everything else is imported
by name (from aiguitest import Run). 'aiguitest-run' runs the tests,
'aiguitest-bridge' serves the VS Code extension. Both import this
package, never the other way round.
"""

from .config import (ASK_SCHEMA, IMAGE_DIRS, IMAGE_EXT, IMAGES, LOCATE_NORM,
                     LOCATE_SCHEMA, LOGDIR, MAX_SIDE, PASSWORD, PROJECT,
                     SERVER, TESTS, TMPDIR, VLM_BASE, VLM_KEY, VLM_MODEL,
                     WORKSPACE, image_path, log_path, test_path, tmp_path)
from .keys import key_name, key_sequence, resolve_key, send_sequence
from .marks import candidate_boxes, draw_marks, match, needle_filter
from .runner import (Run, RunLog, describe_target, log_marker, parse_target,
                     replay, run_log, selftest)
from .vlm import FakeVlm, Vlm, VlmError, _extract_json, _shrink, _to_data_url
from .vnc import ImageSource, VncSession

# last: commands sits on top of runner
from . import commands as _commands
from .commands import *  # noqa: F401,F403
from .commands import bind, current, unbind  # noqa: F401

# 'from aiguitest import *' is for tests: the commands and key constants.
# Written this way so editors (Pylance/pyright) can follow it statically
# and offer the commands as completions after 'from aiguitest import *'.
__all__ = []
__all__ += _commands.__all__
