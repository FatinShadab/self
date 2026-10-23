"""Best-effort live metrics for the current container namespace and cgroup."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any


def format_bytes(value: int | None) -> str:
    """Format an integer byte count into a readable binary string."""
    if value is None or value < 0:
        return "—"
    amount = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if amount < 1024 or unit == "TB":
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return "—"


def read_int_file(path: str | Path) -> int | None:
    """Read a single integer from a file if present."""
    try:
        return int(Path(path).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def read_cgroup_value(filename: str, *groups: str) -> int | None:
    """Read an integer from cgroup v1 or v2 controller directories."""
    for group in groups:
        value = read_int_file(Path("/sys/fs/cgroup") / group / filename)
        if value is not None:
            return value
    return None


class ContainerMetrics:
    """Best-effort live metrics for the current container namespace/cgroup."""

    def __init__(self) -> None:
        self._last_cpu_usage: int | None = None
        self._last_sample = time.monotonic()

    @staticmethod
    def _cpu_usage() -> tuple[int | None, float]:
        stat_path = Path("/sys/fs/cgroup/cpu.stat")
        usage = None
        try:
            values: dict[str, int] = {}
            for line in stat_path.read_text(encoding="utf-8").splitlines():
                key, _, raw = line.partition(" ")
                if key and raw:
                    values[key] = int(raw)
            usage = values.get("usage_usec")
        except (OSError, ValueError):
            usage_ns = read_cgroup_value("cpuacct.usage", "cpuacct")
            usage = usage_ns // 1_000 if usage_ns is not None else None

        quota_cpus = float(os.cpu_count() or 1)
        try:
            quota, period = Path("/sys/fs/cgroup/cpu.max").read_text(encoding="utf-8").split()
            if quota != "max" and int(period) > 0:
                quota_cpus = max(0.01, int(quota) / int(period))
        except (OSError, ValueError):
            quota = read_cgroup_value("cpu.cfs_quota_us", "cpu")
            period = read_cgroup_value("cpu.cfs_period_us", "cpu")
            if quota is not None and quota > 0 and period:
                quota_cpus = max(0.01, quota / period)
        return usage, quota_cpus

    def snapshot(self) -> dict[str, Any]:
        """Return a read-only snapshot of current container resource metrics."""
        now = time.monotonic()
        elapsed = max(0.001, now - self._last_sample)
        cpu_usage, quota_cpus = self._cpu_usage()
        cpu_percent: float | None = None
        if cpu_usage is not None and self._last_cpu_usage is not None:
            cpu_percent = max(0.0, (cpu_usage - self._last_cpu_usage) / 1_000_000 / elapsed / quota_cpus * 100)
        self._last_cpu_usage = cpu_usage
        self._last_sample = now

        ram_used = read_int_file("/sys/fs/cgroup/memory.current")
        ram_limit: int | None = None
        try:
            raw_limit = Path("/sys/fs/cgroup/memory.max").read_text(encoding="utf-8").strip()
            if raw_limit != "max":
                ram_limit = int(raw_limit)
        except (OSError, ValueError):
            ram_used = ram_used or read_cgroup_value("memory.usage_in_bytes", "memory")
            ram_limit = read_cgroup_value("memory.limit_in_bytes", "memory")
            if ram_limit and ram_limit >= 2**60:
                ram_limit = None

        rx_bytes = 0
        tx_bytes = 0
        try:
            for line in Path("/proc/net/dev").read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                interface, raw_stats = line.split(":", 1)
                if interface.strip() == "lo":
                    continue
                stats = raw_stats.split()
                if len(stats) >= 9:
                    rx_bytes += int(stats[0])
                    tx_bytes += int(stats[8])
        except (OSError, ValueError):
            rx_bytes = tx_bytes = 0

        disk_read: int | None = None
        try:
            total = 0
            found = False
            for line in Path("/sys/fs/cgroup/io.stat").read_text(encoding="utf-8").splitlines():
                for item in line.split()[1:]:
                    if item.startswith("rbytes="):
                        total += int(item.split("=", 1)[1])
                        found = True
            if found:
                disk_read = total
        except (OSError, ValueError):
            disk_read = None

        return {
            "cpu": f"{cpu_percent:.1f}% / {quota_cpus:g} CPU" if cpu_percent is not None else "—",
            "ram": f"{format_bytes(ram_used)} / {format_bytes(ram_limit)}" if ram_limit else format_bytes(ram_used),
            "network": f"RX {format_bytes(rx_bytes)} · TX {format_bytes(tx_bytes)}",
            "disk_read": format_bytes(disk_read),
            "ram_used_bytes": ram_used,
            "ram_limit_bytes": ram_limit,
            "cpu_percent": cpu_percent,
            "quota_cpus": quota_cpus,
            "rx_bytes": rx_bytes,
            "tx_bytes": tx_bytes,
            "net": f"↓ {format_bytes(rx_bytes)}  ↑ {format_bytes(tx_bytes)}",
            "disk": f"{format_bytes(disk_read)} read" if disk_read is not None else "—",
            "disk_read_bytes": disk_read,
        }
