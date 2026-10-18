"""aiguitest - semantic GUI tests over VNC with a vision LLM.

Layers (bottom to top):

    config   constants and paths, imports nothing from the package
    marks    image analysis: candidate_boxes, needle_filter, draw_marks, match
    vnc      image sources: VncSession (real desktop), ImageSource (PNG)
    vlm      model access: Vlm.ask/locate/raw, FakeVlm as test double
    runner   Run, run_steps, scenario, replay, selftest

The CLIs sit next to it: 'aiguitest-workbench' (interactive prompt
workbench) and 'aiguitest-run' (test run). They import this package, never
the other way round.
"""

from .config import (ASK_SCHEMA, IMAGE_DIRS, IMAGE_EXT, IMAGES, LOCATE_NORM,
                     LOCATE_SCHEMA, LOGDIR, MAX_SIDE, PASSWORD, PROJECT,
                     SCRIPT_DIRS, SCRIPT_EXT, SCRIPTS, SERVER, TMPDIR,
                     VLM_BASE, VLM_KEY, VLM_MODEL, WORKSPACE, image_path,
                     log_path, script_path, tmp_path)
from .marks import candidate_boxes, draw_marks, match, needle_filter
from .runner import (Run, RunLog, load_steps, log_marker, replay, run_log,
                     run_steps, save_steps, scenario, selftest)
from .vlm import FakeVlm, Vlm, _extract_json, _shrink, _to_data_url
from .vnc import ImageSource, VncSession

__all__ = [
    "ASK_SCHEMA", "LOCATE_NORM", "LOCATE_SCHEMA", "MAX_SIDE", "PASSWORD",
    "PROJECT", "SERVER", "TMPDIR", "VLM_BASE", "VLM_KEY", "VLM_MODEL",
    "WORKSPACE",
    "IMAGE_DIRS", "IMAGE_EXT", "IMAGES",
    "LOGDIR", "SCRIPT_DIRS", "SCRIPT_EXT", "SCRIPTS",
    "image_path", "log_path", "script_path", "tmp_path",
    "candidate_boxes", "draw_marks", "match", "needle_filter",
    "Run", "RunLog", "load_steps", "log_marker", "replay", "run_log",
    "run_steps", "save_steps",
    "scenario", "selftest",
    "FakeVlm", "Vlm", "_extract_json", "_shrink", "_to_data_url",
    "ImageSource", "VncSession",
]
