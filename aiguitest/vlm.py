"""Access to the vision model via an OpenAI-compatible API."""

import base64
import json
import logging
import re
import time

import cv2
import numpy as np

from .config import (ASK_SCHEMA, LOCATE_NORM, LOCATE_SCHEMA, MAX_SIDE,
                     VLM_BASE, VLM_KEY, VLM_MODEL, VLM_VERIFY)
from .marks import candidate_boxes

# urllib3 raises this every time we POST with verify=False. The user already
# opted in by setting vlm.verify=false in config.json, so the warning is
# noise; quiet it at the source (filterwarnings) rather than per-call.
if VLM_VERIFY is False:
    import warnings
    try:
        from urllib3.exceptions import InsecureRequestWarning
        warnings.simplefilter("once", InsecureRequestWarning)
        logging.getLogger("urllib3").setLevel(logging.ERROR)
    except ImportError:
        pass


def _to_data_url(bgr):
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return "data:image/png;base64," + base64.b64encode(buf).decode()


def _shrink(bgr):
    """Scales to MAX_SIDE and returns (image, factor)."""
    h, w = bgr.shape[:2]
    scale = min(1.0, MAX_SIDE / float(max(h, w)))
    if scale >= 1.0:
        return bgr, 1.0
    small = cv2.resize(bgr, (int(w * scale), int(h * scale)),
                       interpolation=cv2.INTER_AREA)
    return small, scale


def _extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise AssertionError("no JSON answer from the model: %r" % text[:200])
        return json.loads(m.group(0))


class Vlm:
    """One model call per method; images are scaled by us beforehand."""

    def __init__(self, base=VLM_BASE, model=VLM_MODEL, key=VLM_KEY,
                 verify=VLM_VERIFY):
        import requests  # lazy, so that --selftest runs without requests
        self._requests = requests
        self.base, self.model, self.key = base, model, key
        self.verify = verify
        self.calls = 0
        self.seconds = 0.0

    def _post(self, bgr, prompt, max_tokens=4000):
        small, scale = _shrink(bgr)
        body = {
            "model": self.model,
            "temperature": 0,
            "seed": 1,
            # qwen3-vl thinks before answering (field 'reasoning') and needs
            # ~2000 tokens for that alone. Capped here, the answer comes back
            # with an empty 'content'. Ollama ignores both think=false and
            # reasoning_effort, so the only option is to leave room.
            "max_tokens": max_tokens,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url",
                     "image_url": {"url": _to_data_url(small)}},
                    {"type": "text", "text": prompt},
                ],
            }],
        }
        t0 = time.time()
        r = self._requests.post(
            self.base.rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + self.key},
            json=body, timeout=180, verify=self.verify,
        )
        r.raise_for_status()
        self.calls += 1
        self.seconds += time.time() - t0
        return r.json()["choices"][0]["message"]["content"].strip(), scale

    def _chat(self, bgr, prompt):
        text, scale = self._post(bgr, prompt)
        return _extract_json(text), scale

    def raw(self, bgr, question):
        """Free-text answer - for 'see' and set-of-marks follow-up questions."""
        return self._post(bgr, question)[0]

    def ask(self, bgr, question):
        """Have it describe first, then judge - don't ask yes/no directly."""
        prompt = (
            "You are checking a screenshot in an automated GUI test.\n"
            "First describe soberly what is visible, and only then judge.\n"
            "Be strict: when in doubt, ok=false.\n"
            "Question: %s\n"
            "Answer ONLY with this JSON, without Markdown:\n%s" % (question, ASK_SCHEMA)
        )
        out, _ = self._chat(bgr, prompt)
        return {"ok": bool(out.get("ok")),
                "seen": out.get("seen", ""),
                "reason": out.get("reason", "")}

    def locate(self, bgr, target):
        """Returns the box in FULL-IMAGE coordinates (back-transformation
        included).

        The model answers normalised to 0..LOCATE_NORM per axis (see config).
        The conversion therefore goes straight to the size of the original
        image; the _shrink factor plays no role in it.

        The prompt deliberately names NO coordinate format: ask for pixels
        and the model still returns 0..1000; ask for 0..1000 and it converts
        with a guessed image size in its 'reasoning' and runs into the
        context limit (empty content).
        """
        prompt = (
            "Find in this screenshot: %s\n"
            "Give the bounding box. If the element is not visible, "
            "found=false.\n"
            "Answer ONLY with this JSON, without Markdown:\n%s" % (target, LOCATE_SCHEMA)
        )
        out, _ = self._chat(bgr, prompt)
        if not out.get("found") or not out.get("box"):
            return None
        h, w = bgr.shape[:2]
        bx = [float(v) for v in out["box"]]
        x1, x2 = [int(round(v * w / LOCATE_NORM)) for v in (bx[0], bx[2])]
        y1, y2 = [int(round(v * h / LOCATE_NORM)) for v in (bx[1], bx[3])]
        x1, x2 = max(0, min(x1, w - 1)), max(0, min(x2, w - 1))
        y1, y2 = max(0, min(y1, h - 1)), max(0, min(y2, h - 1))
        if x2 <= x1 or y2 <= y1:
            return None
        return {"box": [x1, y1, x2, y2], "conf": float(out.get("conf", 0.0))}


class FakeVlm:
    """Answers deterministically from the candidate areas - for trying out
    the workbench without a model and without a network."""

    def __init__(self):
        self.calls = 0
        self.seconds = 0.0

    def _boxes(self, img):
        return candidate_boxes(img)

    def raw(self, img, question):
        self.calls += 1
        if "number" in question.lower():
            return '{"number": 1, "conf": 0.7}'
        return "Fake answer to %r: %d candidate areas visible." % (
            question, len(self._boxes(img)))

    def ask(self, img, question):
        self.calls += 1
        ok = len(self._boxes(img)) > 0
        return {"ok": ok, "seen": "%d elements" % len(self._boxes(img)),
                "reason": "fake"}

    def locate(self, img, target):
        self.calls += 1
        b = self._boxes(img)
        if not b:
            return None
        x, y, w, h = b[0]
        jitter = np.random.randint(-2, 3)   # simulates model noise
        return {"box": [x + jitter, y, x + w + jitter, y + h], "conf": 0.8}
