"""One-shot execution guarded by a Linux advisory lock."""

import fcntl
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def scan_lock(path: str):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "Another scan or publisher holds the monitor lock"
            ) from error
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
