"""Read-only system, process, GPU and temperature metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import platform
import socket
from typing import Iterable


GIB = 1024**3
HWMON_ROOT = Path("/sys/class/hwmon")


def _meminfo(path: Path = Path("/proc/meminfo")) -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, separator, rest = line.partition(":")
            if separator:
                number = rest.strip().split()[0]
                if number.isdigit():
                    values[key] = int(number) * 1024
    except OSError:
        pass
    return values


def _process_rss_bytes() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def gpu_memory() -> dict[str, int | None]:
    """Return separate AMD VRAM and GTT counters from sysfs."""
    vram_totals: list[int] = []
    vram_used: list[int] = []
    gtt_totals: list[int] = []
    gtt_used: list[int] = []
    for device in sorted(Path("/sys/class/drm").glob("card*/device")):
        vram_total = _read_int(device / "mem_info_vram_total")
        vram_current = _read_int(device / "mem_info_vram_used")
        gtt_total = _read_int(device / "mem_info_gtt_total")
        gtt_current = _read_int(device / "mem_info_gtt_used")
        if vram_total is not None:
            vram_totals.append(vram_total)
        if vram_current is not None:
            vram_used.append(vram_current)
        if gtt_total is not None:
            gtt_totals.append(gtt_total)
        if gtt_current is not None:
            gtt_used.append(gtt_current)
    total = sum(vram_totals) + sum(gtt_totals) if vram_totals or gtt_totals else None
    current = sum(vram_used) + sum(gtt_used) if vram_used or gtt_used else None
    return {
        "addressable_total_bytes": total,
        "addressable_used_bytes": current,
        "addressable_available_bytes": total - current if total is not None and current is not None else None,
        "vram_total_bytes": sum(vram_totals) if vram_totals else None,
        "vram_used_bytes": sum(vram_used) if vram_used else None,
        "gtt_total_bytes": sum(gtt_totals) if gtt_totals else None,
        "gtt_used_bytes": sum(gtt_used) if gtt_used else None,
    }


@dataclass(frozen=True)
class MemorySample:
    system_total_bytes: int | None
    system_available_bytes: int | None
    swap_total_bytes: int | None
    swap_free_bytes: int | None
    process_rss_bytes: int | None
    gpu_addressable_total_bytes: int | None
    gpu_addressable_available_bytes: int | None
    gpu_addressable_used_bytes: int | None
    gpu_vram_total_bytes: int | None
    gpu_vram_used_bytes: int | None
    gpu_gtt_total_bytes: int | None
    gpu_gtt_used_bytes: int | None

    def to_dict(self) -> dict[str, int | None]:
        return asdict(self)


def memory_sample() -> MemorySample:
    memory = _meminfo()
    gpu = gpu_memory()
    return MemorySample(
        system_total_bytes=memory.get("MemTotal"),
        system_available_bytes=memory.get("MemAvailable"),
        swap_total_bytes=memory.get("SwapTotal"),
        swap_free_bytes=memory.get("SwapFree"),
        process_rss_bytes=_process_rss_bytes(),
        gpu_addressable_total_bytes=gpu["addressable_total_bytes"],
        gpu_addressable_available_bytes=gpu["addressable_available_bytes"],
        gpu_addressable_used_bytes=gpu["addressable_used_bytes"],
        gpu_vram_total_bytes=gpu["vram_total_bytes"],
        gpu_vram_used_bytes=gpu["vram_used_bytes"],
        gpu_gtt_total_bytes=gpu["gtt_total_bytes"],
        gpu_gtt_used_bytes=gpu["gtt_used_bytes"],
    )


def _labelled_temperature_files(root: Path = HWMON_ROOT) -> Iterable[tuple[str, Path]]:
    for directory in sorted(root.glob("hwmon*")):
        try:
            chip = (directory / "name").read_text(encoding="utf-8").strip()
        except OSError:
            chip = directory.name
        for input_path in sorted(directory.glob("temp*_input")):
            label_path = input_path.with_name(input_path.name.replace("_input", "_label"))
            try:
                label = label_path.read_text(encoding="utf-8").strip()
            except OSError:
                label = input_path.stem
            yield f"{chip}/{label}", input_path


def temperatures(sensor_labels: tuple[str, ...], root: Path = HWMON_ROOT) -> dict[str, float]:
    readings: dict[str, float] = {}
    lowered = tuple(label.casefold() for label in sensor_labels)
    for label, path in _labelled_temperature_files(root):
        if not any(expected in label.casefold() for expected in lowered):
            continue
        raw = _read_int(path)
        if raw is not None and -40_000 <= raw <= 200_000:
            readings[label] = raw / 1000.0
    return readings


def peak_temperature(sensor_labels: tuple[str, ...]) -> tuple[float | None, dict[str, float]]:
    readings = temperatures(sensor_labels)
    return (max(readings.values()) if readings else None, readings)


def host_identity() -> dict[str, str | None]:
    fedora = None
    try:
        fedora = Path("/etc/fedora-release").read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return {
        "machine_id": socket.gethostname(),
        "fedora_version": fedora,
        "kernel_version": platform.release(),
        "python_version": platform.python_version(),
        "rocm_version": installed_rocm_version(),
    }


def installed_rocm_version() -> str | None:
    candidates = [Path("/opt/rocm/.info/version"), Path("/opt/rocm/.info/version-dev")]
    for path in candidates:
        try:
            value = path.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            continue
    return None


def package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None
