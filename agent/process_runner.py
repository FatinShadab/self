"""Bounded subprocess output and process-group timeouts, without shell policies."""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from pathlib import Path
from typing import Any


def run_process(argv: list[str], *, cwd: Path, timeout: float, cap: int,
                env: dict[str, str] | None = None, stdin: str | None = None) -> dict[str, Any]:
    process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               start_new_session=True)
    assert process.stdout is not None and process.stdin is not None
    # Payloads are small; use a temporary in-memory stdin reader in a thread so
    # the timeout also covers a child which does not read its input.
    import threading

    def send_input() -> None:
        try:
            process.stdin.write((stdin or "").encode())
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass

    threading.Thread(target=send_input, daemon=True).start()
    selector = selectors.DefaultSelector()
    os.set_blocking(process.stdout.fileno(), False)
    selector.register(process.stdout, selectors.EVENT_READ)
    captured = bytearray()
    total = 0
    timed_out = False
    deadline = time.monotonic() + max(0.1, timeout)

    def kill_group() -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    try:
        while selector.get_map() or process.poll() is None:
            if time.monotonic() >= deadline:
                timed_out = True
                kill_group()
                break
            for key, _ in selector.select(min(0.1, max(0, deadline - time.monotonic()))):
                try:
                    chunk = os.read(key.fd, 8192)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                captured.extend(chunk[:max(0, cap - len(captured))])
    finally:
        kill_group()  # Also clean up descendants after their parent exits.
        selector.close()
        process.stdout.close()
        process.wait(timeout=5)
    return {"exit_code": process.returncode, "output": captured.decode("utf-8", errors="replace"),
            "output_bytes": total, "truncated": total > cap, "timed_out": timed_out}
