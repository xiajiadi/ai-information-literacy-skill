"""A stand-in for a browser CLI, used to prove the hard timeout really kills.

Modes (via FAKE_BROWSER_MODE):
  sleep   - spawn a grandchild, then hang
  detach  - spawn a grandchild and exit at once, modelling agent-browser's
            daemon: the launcher is gone while the browser keeps running, so a
            tree-kill on the launcher pid reaches nothing
  fail    - exit non-zero immediately (drives the max_browser_failures path)

The grandchild pid is written to FAKE_BROWSER_PIDFILE so the test can assert on
what actually survived, and FAKE_BROWSER_MARKER puts a searchable string in its
command line for the residue sweep to match.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time


def main() -> int:
    mode = os.environ.get("FAKE_BROWSER_MODE", "sleep")

    if mode == "fail":
        print("fake browser: intentional failure", file=sys.stderr)
        return 1

    # A grandchild that would survive if only the direct child were killed.
    # FAKE_BROWSER_MARKER puts a searchable string in its command line so the
    # residue sweep can find it the same way it finds agent-browser's Chromium.
    grandchild_argv = [sys.executable, "-c", "import time; time.sleep(600)"]
    marker = os.environ.get("FAKE_BROWSER_MARKER")
    if marker:
        grandchild_argv.append(marker)
    child = subprocess.Popen(grandchild_argv)
    pidfile = os.environ.get("FAKE_BROWSER_PIDFILE")
    if pidfile:
        with open(pidfile, "w", encoding="utf-8") as handle:
            handle.write(str(child.pid))

    if mode == "detach":
        # Exit immediately, leaving the browser running with no live parent --
        # this is what makes a launcher-only kill insufficient.
        return 0

    time.sleep(600)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
