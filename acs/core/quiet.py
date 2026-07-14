"""Silence MediaPipe's native C++ log spam (clearcut telemetry, XNNPACK, glog).

Those messages are written directly to OS file descriptor 2 (stderr) by the C++
library and ignore every Python/glog/absl logging env var. The only way to hide
them is to redirect fd 2 — but we must keep Python's own logging (uvicorn, our
app) visible. So we point Python's ``sys.stderr`` at a saved copy of the real
terminal first, then send the raw fd 2 to the null device. Native noise → null;
Python logs → terminal.

Call this BEFORE importing/running anything that initializes MediaPipe.
Set ACS_QUIET_NATIVE=0 to keep the native logs (for debugging).
"""
from __future__ import annotations

import os
import sys


def silence_native_stderr() -> None:
    if os.environ.get("ACS_QUIET_NATIVE", "1") == "0":
        return
    try:
        saved = os.dup(2)                       # a handle to the real terminal
        sys.stderr = os.fdopen(saved, "w", buffering=1)   # Python keeps the terminal
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)                     # native fd 2 -> null
        os.close(devnull)
    except Exception:                            # noqa: BLE001 - never block startup
        pass
