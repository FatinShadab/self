"""Bounded subprocess output and process-group timeouts, without shell policies."""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


def run_process(argv: list[str], *, cwd: Path, timeout: float, cap: int,
                env: dict[str, str] | None = None, stdin: str | None = None,
                on_output: Callable[[str], None] | None = None,
                on_complete: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Execute a bounded child process and capture its output."""
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
    captured = bytearray()
    total = 0
    timed_out = False
    deadline = time.monotonic() + max(0.1, timeout)

    if os.name == "nt":
        # Windows pipes do not support select.select; use communicate
        try:
            out_bytes, _ = process.communicate(input=(stdin or "").encode() if stdin else None, timeout=max(0.1, timeout))
            total = len(out_bytes or b"")
            captured.extend((out_bytes or b"")[:max(0, cap)])
            if on_output is not None and out_bytes:
                try:
                    on_output(out_bytes.decode("utf-8", errors="replace"))
                except Exception:
                    pass
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            out_bytes, _ = process.communicate()
            total = len(out_bytes or b"")
            captured.extend((out_bytes or b"")[:max(0, cap)])
    else:
        selector = selectors.DefaultSelector()
        os.set_blocking(process.stdout.fileno(), False)
        selector.register(process.stdout, selectors.EVENT_READ)

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
                    if on_output is not None:
                        try:
                            on_output(chunk.decode("utf-8", errors="replace"))
                        except Exception:
                            # Activity observers are diagnostic only and must never
                            # change subprocess behavior.
                            pass
        finally:
            kill_group()  # Also clean up descendants after their parent exits.
            selector.close()
            process.stdout.close()
            process.wait(timeout=5)
    result = {"exit_code": process.returncode, "output": captured.decode("utf-8", errors="replace"),
              "output_bytes": total, "truncated": total > cap, "timed_out": timed_out}
    if on_complete is not None:
        try:
            on_complete(result)
        except Exception:
            pass
    return result
