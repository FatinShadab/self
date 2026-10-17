"""Independent stop and pause watcher for SELF.

Does not depend on the coordinator being idle. Runs in a dedicated background
thread and calls Body.emergency_stop() on stop and on broker panic.
"""
from __future__ import annotations

import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from agent.infra.event_log import EventLogger


class StopWatcher:
    """Monitors STOP file, pause flag, OS signals, and broker panic independently."""

    def __init__(
        self,
        workspace: Path | str,
        body: Any | None = None,
        broker: Any | None = None,
        logger: EventLogger | None = None,
        check_interval: float = 0.05,
        install_signals: bool = True,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.body = body
        self.broker = broker
        self.logger = logger
        self.check_interval = max(0.01, float(check_interval))

        self.stop_file = self.workspace / "STOP"
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None
        self._original_sigint = None
        self._original_sigterm = None
        self._emergency_stop_called = False

        if install_signals:
            self._install_signals()

        # Connect broker panic callback if broker provided
        if self.broker is not None and hasattr(self.broker, "on_panic"):
            prev_panic = self.broker.on_panic

            def _panic_handler(reason: str) -> None:
                if prev_panic:
                    try:
                        prev_panic(reason)
                    except Exception:
                        pass
                self.trigger_panic(reason)

            self.broker.on_panic = _panic_handler

    def _install_signals(self) -> None:
        """Register signal handlers for SIGINT and SIGTERM where supported."""
        try:
            if threading.current_thread() is threading.main_thread():
                self._original_sigint = signal.getsignal(signal.SIGINT)
                signal.signal(signal.SIGINT, self._signal_handler)
                if hasattr(signal, "SIGTERM"):
                    self._original_sigterm = signal.getsignal(signal.SIGTERM)
                    signal.signal(signal.SIGTERM, self._signal_handler)
        except (ValueError, OSError):
            pass

    def _signal_handler(self, signum: int, frame: Any) -> None:
        sig_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM" if signum == getattr(signal, "SIGTERM", -1) else str(signum)
        if self.logger:
            self.logger.log("stop_watcher_signal_received", signal=sig_name)
        self.request_stop(reason=f"signal:{sig_name}")

    def start(self) -> None:
        """Start the background watcher thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, name="stop-watcher", daemon=True)
        self._thread.start()
        if self.logger:
            self.logger.log("stop_watcher_started")

    def shutdown(self) -> None:
        """Stop and join the watcher thread."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._restore_signals()
        if self.logger:
            self.logger.log("stop_watcher_stopped")

    def _restore_signals(self) -> None:
        try:
            if threading.current_thread() is threading.main_thread():
                if self._original_sigint is not None:
                    signal.signal(signal.SIGINT, self._original_sigint)
                if self._original_sigterm is not None and hasattr(signal, "SIGTERM"):
                    signal.signal(signal.SIGTERM, self._original_sigterm)
        except (ValueError, OSError):
            pass

    def request_stop(self, reason: str = "requested") -> None:
        """Trigger an immediate hard stop and call Body.emergency_stop()."""
        self._stop_event.set()
        try:
            self.stop_file.touch()
        except OSError:
            pass
        self._call_emergency_stop(reason=reason)
        if self.logger:
            self.logger.log("stop_watcher_stop_triggered", reason=reason)

    def trigger_panic(self, reason: str) -> None:
        """Broker panic triggered — immediately call Body.emergency_stop() and stop."""
        self._stop_event.set()
        try:
            self.stop_file.touch()
        except OSError:
            pass
        self._call_emergency_stop(reason=f"broker_panic:{reason}")
        if self.logger:
            self.logger.log("stop_watcher_panic_triggered", reason=reason)

    def pause(self) -> None:
        """Pause execution."""
        self._pause_event.set()
        if self.logger:
            self.logger.log("stop_watcher_paused")

    def resume(self) -> None:
        """Resume execution from pause."""
        self._pause_event.clear()
        if self.logger:
            self.logger.log("stop_watcher_resumed")

    def is_stopped(self) -> bool:
        """Return True if stop has been triggered or STOP file exists."""
        return self._stop_event.is_set() or self.stop_file.exists()

    def is_paused(self) -> bool:
        """Return True if paused."""
        return self._pause_event.is_set()

    def _call_emergency_stop(self, reason: str) -> None:
        """Invoke Body.emergency_stop() if not already called."""
        if not self._emergency_stop_called and self.body is not None:
            self._emergency_stop_called = True
            if hasattr(self.body, "emergency_stop"):
                try:
                    self.body.emergency_stop()
                except Exception as exc:
                    if self.logger:
                        self.logger.log("emergency_stop_error", error=str(exc))

    def _watch_loop(self) -> None:
        """Continuous watch loop running independently in the background thread."""
        while self._running:
            # 1. Check STOP file
            if self.stop_file.exists() and not self._stop_event.is_set():
                self._stop_event.set()
                self._call_emergency_stop(reason="stop_file_detected")

            # 2. Check broker panic
            if self.broker is not None and getattr(self.broker, "in_panic", False):
                if not self._stop_event.is_set():
                    self.trigger_panic("broker_in_panic_detected")

            time.sleep(self.check_interval)
