"""
温度读取工具（CPU）

优先使用 Linux hwmon（/sys/class/hwmon）进行精确选源，
必要时回退到 psutil.sensors_temperatures / thermal_zone。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.core.config import settings


@dataclass(frozen=True)
class HwmonTempReading:
    chip: str
    label: str
    temp_c: float
    input_path: str
    score: int


def _is_plausible_temp_c(value: float) -> bool:
    return 0.0 <= value <= 125.0


def _parse_temp_to_c(raw: str) -> Optional[float]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except Exception:
        return None

    # sysfs 通常是毫摄氏度（例如 42000）
    if value > 1000:
        value = value / 1000.0

    if not _is_plausible_temp_c(value):
        return None
    return value


def _score_cpu_temp_candidate(chip: str, label: str) -> int:
    chip_l = (chip or "").lower()
    label_l = (label or "").lower()

    score = 0

    # 强 CPU 传感器驱动名
    if any(k in chip_l for k in ("coretemp", "k10temp", "cpu_thermal", "zenpower", "x86_pkg_temp")):
        score += 100
    elif "cpu" in chip_l:
        score += 60

    # 常见 CPU 温度标签
    if any(k in label_l for k in ("package", "tctl", "tdie", "cpu")):
        score += 60
    elif "core" in label_l:
        score += 40

    # 明确的非 CPU（强排除）
    if any(k in chip_l for k in ("nvme", "amdgpu", "gpu")) or any(k in label_l for k in ("nvme", "amdgpu", "gpu")):
        score -= 200

    # 常见非 CPU（降权）
    if any(k in chip_l for k in ("pch", "battery", "iwlwifi")) or any(k in label_l for k in ("pch", "battery", "iwlwifi")):
        score -= 80

    # 用户偏好（可选）
    preferred_chip = (settings.cpu_temp_preferred_chip or "").strip().lower()
    preferred_label = (settings.cpu_temp_preferred_label or "").strip().lower()
    if preferred_chip and preferred_chip in chip_l:
        score += 500
    if preferred_label and preferred_label in label_l:
        score += 300

    return score


def _min_score() -> int:
    try:
        return int(settings.cpu_temp_min_score)
    except Exception:
        return 80


def list_hwmon_temperatures() -> list[HwmonTempReading]:
    """
    枚举 /sys/class/hwmon 下所有温度输入（temp*_input）。

    Returns:
        读取到的温度列表（已过滤掉明显异常值）
    """
    base = Path("/sys/class/hwmon")
    if not base.exists():
        return []

    readings: list[HwmonTempReading] = []
    for hwmon_dir in sorted(base.glob("hwmon*")):
        try:
            name = (hwmon_dir / "name").read_text(encoding="utf-8").strip()
        except Exception:
            name = ""

        for input_file in sorted(hwmon_dir.glob("temp*_input")):
            stem = input_file.name.replace("_input", "")
            label_file = hwmon_dir / f"{stem}_label"
            label = ""
            if label_file.exists():
                try:
                    label = label_file.read_text(encoding="utf-8").strip()
                except Exception:
                    label = ""

            try:
                temp_c = _parse_temp_to_c(input_file.read_text(encoding="utf-8"))
            except Exception:
                temp_c = None
            if temp_c is None:
                continue

            score = _score_cpu_temp_candidate(name, label)
            readings.append(
                HwmonTempReading(
                    chip=name or hwmon_dir.name,
                    label=label,
                    temp_c=temp_c,
                    input_path=str(input_file),
                    score=score,
                )
            )

    return readings


_CPU_TEMP_CACHE: dict[str, object] = {
    "path": None,  # Optional[str]
    "expires_at": 0.0,  # float
    "source": None,  # Optional[HwmonTempReading]
}


def _read_temp_from_sysfs(path: str) -> Optional[float]:
    try:
        return _parse_temp_to_c(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def get_cpu_temp_status() -> dict:
    """
    返回 CPU 温度与选源信息（用于排错/确认指标来源）
    """
    sysfs_path = (settings.cpu_temp_sysfs_path or "").strip()
    if sysfs_path:
        return {
            "temp_c": _read_temp_from_sysfs(sysfs_path),
            "method": "sysfs",
            "sysfs_path": sysfs_path,
            "min_score": _min_score(),
        }

    now = time.time()
    cached_path = _CPU_TEMP_CACHE.get("path")
    expires_at = float(_CPU_TEMP_CACHE.get("expires_at") or 0.0)
    cached_source = _CPU_TEMP_CACHE.get("source")

    if isinstance(cached_path, str) and cached_path and now < expires_at:
        temp_c = _read_temp_from_sysfs(cached_path)
        if temp_c is not None:
            source = None
            if isinstance(cached_source, HwmonTempReading):
                source = {
                    "chip": cached_source.chip,
                    "label": cached_source.label,
                    "input_path": cached_source.input_path,
                    "score": cached_source.score,
                }
            return {
                "temp_c": temp_c,
                "method": "hwmon",
                "source": source,
                "cache": {"path": cached_path, "expires_at": expires_at},
                "min_score": _min_score(),
            }

    picked = _pick_cpu_temp_hwmon()
    if picked is not None:
        return {
            "temp_c": picked.temp_c,
            "method": "hwmon",
            "source": {
                "chip": picked.chip,
                "label": picked.label,
                "input_path": picked.input_path,
                "score": picked.score,
            },
            "cache": {
                "path": picked.input_path,
                "expires_at": now + float(settings.cpu_temp_cache_ttl_seconds),
            },
            "min_score": _min_score(),
        }

    ps = _pick_cpu_temp_psutil()
    if ps is not None:
        value, group, label, score = ps
        return {
            "temp_c": value,
            "method": "psutil",
            "source": {"group": group, "label": label, "score": score},
            "min_score": _min_score(),
        }

    tz = _pick_cpu_temp_thermal_zone()
    if tz is not None:
        value, zone_type, score = tz
        return {
            "temp_c": value,
            "method": "thermal_zone",
            "source": {"type": zone_type, "score": score},
            "min_score": _min_score(),
        }

    return {"temp_c": None, "method": None, "min_score": _min_score()}


def read_cpu_temp_c() -> Optional[float]:
    """
    获取 CPU 温度（摄氏度）

    优先读取 hwmon。若用户指定了 `ARGUS_CPU_TEMP_SYSFS_PATH`，则直接读取该路径。
    """
    sysfs_path = (settings.cpu_temp_sysfs_path or "").strip()
    if sysfs_path:
        return _read_temp_from_sysfs(sysfs_path)

    now = time.time()
    cached_path = _CPU_TEMP_CACHE.get("path")
    expires_at = float(_CPU_TEMP_CACHE.get("expires_at") or 0.0)
    if isinstance(cached_path, str) and cached_path and now < expires_at:
        temp_c = _read_temp_from_sysfs(cached_path)
        if temp_c is not None:
            return temp_c
        _CPU_TEMP_CACHE["path"] = None

    picked = _pick_cpu_temp_hwmon()
    if picked is not None:
        _CPU_TEMP_CACHE["path"] = picked.input_path
        _CPU_TEMP_CACHE["expires_at"] = now + float(settings.cpu_temp_cache_ttl_seconds)
        _CPU_TEMP_CACHE["source"] = picked
        return picked.temp_c

    # fallback: psutil.sensors_temperatures()
    ps = _pick_cpu_temp_psutil()
    if ps is not None:
        return ps[0]

    # fallback: /sys/class/thermal/thermal_zone*
    tz = _pick_cpu_temp_thermal_zone()
    return tz[0] if tz is not None else None


def _pick_cpu_temp_hwmon() -> Optional[HwmonTempReading]:
    candidates = list_hwmon_temperatures()
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x.score, x.temp_c), reverse=True)
    best = candidates[0]
    return best if best.score >= _min_score() else None


def _pick_cpu_temp_psutil() -> Optional[tuple[float, str, str, int]]:
    try:
        import psutil  # type: ignore

        temps = psutil.sensors_temperatures(fahrenheit=False) or {}
        candidates: list[tuple[int, float, str, str]] = []

        for group, entries in temps.items():
            for e in entries or []:
                current = getattr(e, "current", None)
                if current is None:
                    continue
                try:
                    value = float(current)
                except Exception:
                    continue
                if not _is_plausible_temp_c(value):
                    continue

                label = getattr(e, "label", "") or ""
                score = _score_cpu_temp_candidate(str(group), str(label))
                candidates.append((score, value, str(group), str(label)))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best_score, best_value, best_group, best_label = candidates[0]
        return (best_value, best_group, best_label, best_score) if best_score >= _min_score() else None
    except Exception:
        return None


def _pick_cpu_temp_thermal_zone() -> Optional[tuple[float, str, int]]:
    try:
        base = Path("/sys/class/thermal")
        candidates: list[tuple[int, float, str]] = []

        for zone in base.glob("thermal_zone*"):
            temp_path = zone / "temp"
            if not temp_path.exists():
                continue

            type_s = ""
            type_path = zone / "type"
            if type_path.exists():
                try:
                    type_s = type_path.read_text(encoding="utf-8").strip()
                except Exception:
                    type_s = ""

            try:
                temp_c = _parse_temp_to_c(temp_path.read_text(encoding="utf-8"))
            except Exception:
                temp_c = None
            if temp_c is None:
                continue

            score = _score_cpu_temp_candidate(type_s, type_s)
            candidates.append((score, temp_c, type_s))

        if not candidates:
            return None

        candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
        best_score, best_value, best_type = candidates[0]
        return (best_value, best_type, best_score) if best_score >= _min_score() else None
    except Exception:
        return None
