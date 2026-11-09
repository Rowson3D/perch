"""Deciding whether a GPU is FREE, IN USE or HELD from its recent samples."""

import time
from collections import deque

FREE, BUSY, HELD, UNKNOWN = "free", "busy", "held", "unknown"
HYSTERESIS = 5.0  # percentage points a busy GPU must drop below a threshold to flip back
IDLE_UTIL = 5.0  # utilization at or below this counts as "doing nothing"
KEEP_SECONDS = 4 * 3600

DETECTION_DEFAULTS = {
    "threshold": 50,  # VRAM % at or above which a GPU counts as IN USE
    "use_util": True,  # also IN USE when utilization averages >= util_threshold...
    "util_threshold": 40,
    "util_window": 60,  # ...over this many seconds
    "detect_held": True,  # VRAM held but GPU idle for held_minutes -> HELD
    "held_minutes": 10,
}


class Tracker:
    """Rolling history for one GPU plus its current state."""

    def __init__(self):
        self.samples = deque()  # (time, vram %, util % or None)
        self.state = UNKNOWN
        self.reason = ""

    def add(self, mem_pct, util, now=None):
        now = time.time() if now is None else now
        self.samples.append((now, mem_pct, util))
        while self.samples and self.samples[0][0] < now - KEEP_SECONDS:
            self.samples.popleft()

    def window(self, seconds, now=None):
        now = time.time() if now is None else now
        return [s for s in self.samples if s[0] >= now - seconds]

    def util_avg(self, seconds, now=None):
        vals = [u for _, _, u in self.window(seconds, now) if u is not None]
        return sum(vals) / len(vals) if vals else None

    def evaluate(self, cfg, now=None):
        now = time.time() if now is None else now
        if not self.samples:
            self.state, self.reason = UNKNOWN, ""
            return self.state
        _, mem, _ = self.samples[-1]
        was_busy = self.state in (BUSY, HELD)
        thr = float(cfg["threshold"])
        vram_busy = mem >= (thr - HYSTERESIS if was_busy else thr)

        util_busy, avg = False, None
        if cfg.get("use_util"):
            secs = float(cfg.get("util_window", 60))
            avg = self.util_avg(secs, now)
            uthr = float(cfg.get("util_threshold", 40))
            util_busy = avg is not None and avg >= (uthr - HYSTERESIS if was_busy else uthr)

        if not (vram_busy or util_busy):
            state = FREE
            self.reason = f"VRAM is at {mem:.0f}%, under the {thr:.0f}% threshold"
        elif vram_busy and not util_busy and cfg.get("detect_held") and self._idle_for(cfg, now):
            state = HELD
            self.reason = (
                f"VRAM is at {mem:.0f}% but the GPU has been idle for {int(cfg.get('held_minutes', 10))}+ minutes"
            )
        else:
            state = BUSY
            if vram_busy:
                self.reason = f"VRAM is at {mem:.0f}%, over the {thr:.0f}% threshold"
            else:
                self.reason = f"utilization averaged {avg:.0f}% over the last {int(cfg.get('util_window', 60))} s"
        self.state = state
        return state

    def _idle_for(self, cfg, now):
        span = float(cfg.get("held_minutes", 10)) * 60
        if not self.samples or self.samples[0][0] > now - span * 0.95:
            return False  # not enough history yet
        utils = [u for _, _, u in self.window(span, now)]
        return bool(utils) and all(u is not None and u <= IDLE_UTIL for u in utils)
