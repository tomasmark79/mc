#!/usr/bin/env python3
"""Copy the current MC item, path, or name to the Wayland clipboard."""

import os
from pathlib import Path
import subprocess
import sys
import traceback


def fail(message, status=1):
    if os.environ.get("MC_CLIPBOARD_DEBUG") == "1":
        traceback.print_exc()
    print(message, file=sys.stderr)
    sys.exit(status)


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("path", "directory", "name", "file"):
        sys.exit("Usage: mc-clipboard path|directory|name|file FILE")

    # abspath normalizes . and .. but preserves the symbolic link path.
    path = Path(os.path.abspath(sys.argv[2]))
    value = {
        "path": str(path),
        "directory": str(path.parent),
        "name": path.name,
        "file": path.as_uri() + "\r\n",
    }[sys.argv[1]]
    try:
        command = [
            "wl-copy", "--type",
            "text/uri-list" if sys.argv[1] == "file" else "text/plain;charset=utf-8",
        ]
        with subprocess.Popen(command, stdin=subprocess.PIPE) as process:
            try:
                process.communicate(os.fsencode(value), timeout=5)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                process.kill()
                process.wait()
                raise
            if process.returncode:
                raise subprocess.CalledProcessError(process.returncode, command)
    except subprocess.TimeoutExpired:
        fail("Copy failed: clipboard did not respond within 5 seconds. Please try again.")
    except subprocess.CalledProcessError:
        fail("Copy failed: wl-copy could not access the clipboard.")
    except OSError as error:
        fail(f"Copy failed: {error}")
    except KeyboardInterrupt:
        fail("Copy cancelled.", 130)


if __name__ == "__main__":
    main()
