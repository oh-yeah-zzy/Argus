"""
指标采集器
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.services.storage import MetricsSample, SqliteMetricsStore
from app.services.temperature import read_cpu_temp_c

logger = get_logger("argus.sampler")


@dataclass
class GpuReading:
    usage: Optional[float]
    temp_c: Optional[float]
    name: Optional[str]
    source: Optional[str] = None  # "nvml" | "nvidia-smi" | None


class GpuReader:
    def __init__(self, enabled: bool, gpu_index: int):
        self.enabled = enabled
        self.gpu_index = gpu_index
        self._mode: Optional[str] = None  # "nvml" | "nvidia-smi" | None
        self._next_retry_at: float = 0.0
        self._fail_count: int = 0
        self._last_error: Optional[str] = None

        self._nvml_inited: Optional[bool] = None
        self._nvml_handle = None
        self._nvml_name: Optional[str] = None
        self._nvml_api = None

        self._smi_path: Optional[str] = None

    def read(self) -> GpuReading:
        if not self.enabled:
            return GpuReading(usage=None, temp_c=None, name=None, source=None)

        now = time.time()
        if now < self._next_retry_at:
            return GpuReading(usage=None, temp_c=None, name=None, source=None)

        # 尝试 NVML（优先）
        if self._mode in (None, "nvml"):
            reading = self._read_nvml()
            if reading is not None:
                self._mode = "nvml"
                self._fail_count = 0
                self._next_retry_at = 0.0
                self._last_error = None
                return reading

        # 尝试 nvidia-smi
        if self._mode in (None, "nvidia-smi"):
            reading = self._read_nvidia_smi()
            if reading is not None:
                self._mode = "nvidia-smi"
                self._fail_count = 0
                self._next_retry_at = 0.0
                self._last_error = None
                return reading

        self._fail_count += 1
        self._next_retry_at = now + min(60.0, 1.5 * (2 ** min(self._fail_count, 5)))
        self._mode = None
        return GpuReading(usage=None, temp_c=None, name=None, source=None)

    def get_status(self) -> dict:
        return {
            "enabled": bool(self.enabled),
            "gpu_index": int(self.gpu_index),
            "mode": self._mode,
            "next_retry_at": self._next_retry_at,
            "fail_count": self._fail_count,
            "last_error": self._last_error,
        }

    def _read_nvml(self) -> Optional[GpuReading]:
        try:
            if self._nvml_inited is False:
                return None
            if self._nvml_inited is None:
                try:
                    import pynvml  # type: ignore

                    pynvml.nvmlInit()
                    handle = pynvml.nvmlDeviceGetHandleByIndex(int(self.gpu_index))
                    name_raw = pynvml.nvmlDeviceGetName(handle)
                    name = (
                        name_raw.decode("utf-8")
                        if isinstance(name_raw, (bytes, bytearray))
                        else str(name_raw)
                    )
                    self._nvml_handle = handle
                    self._nvml_name = name
                    self._nvml_api = pynvml
                    self._nvml_inited = True
                except Exception as e:
                    self._nvml_inited = False
                    self._last_error = f"nvml init failed: {type(e).__name__}: {e}"
                    return None

            api = self._nvml_api
            handle = self._nvml_handle
            if api is None or handle is None:
                return None

            util = api.nvmlDeviceGetUtilizationRates(handle)
            temp_c = float(api.nvmlDeviceGetTemperature(handle, api.NVML_TEMPERATURE_GPU))
            return GpuReading(
                usage=float(util.gpu),
                temp_c=temp_c,
                name=self._nvml_name,
                source="nvml",
            )
        except Exception as e:
            self._last_error = f"nvml read failed: {type(e).__name__}: {e}"
            return None

    def _read_nvidia_smi(self) -> Optional[GpuReading]:
        import subprocess
        import shutil

        try:
            if self._smi_path is None:
                self._smi_path = shutil.which("nvidia-smi")
            if not self._smi_path:
                self._last_error = "nvidia-smi not found"
                return None

            cmd = [
                self._smi_path,
                f"--id={int(self.gpu_index)}",
                "--query-gpu=utilization.gpu,temperature.gpu,name",
                "--format=csv,noheader,nounits",
            ]
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=2).strip()
            if not out:
                return None
            parts = [p.strip() for p in out.split(",")]
            if len(parts) < 3:
                return None
            usage = float(parts[0])
            temp_c = float(parts[1])
            name = ",".join(parts[2:]).strip() or None
            return GpuReading(usage=usage, temp_c=temp_c, name=name, source="nvidia-smi")
        except Exception as e:
            self._last_error = f"nvidia-smi failed: {type(e).__name__}: {e}"
            return None


def _get_cpu_temp_c() -> Optional[float]:
    return read_cpu_temp_c()


class MetricsSampler:
    def __init__(self, store: SqliteMetricsStore):
        self._store = store
        self._stop_event = asyncio.Event()
        self._gpu_reader = GpuReader(settings.gpu_enabled, settings.gpu_index)
        self._last_retention_at: float = 0.0

        # prime psutil.cpu_percent()
        try:
            import psutil  # type: ignore

            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    async def run(self) -> None:
        logger.info(
            "metrics sampler started",
            extra={"extra_fields": {"interval": settings.sampling_interval_seconds}},
        )
        while not self._stop_event.is_set():
            start = time.time()
            try:
                sample = await asyncio.to_thread(self._collect_once)
                await asyncio.to_thread(self._store.insert_sample, sample)
                await self._apply_retention()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"metrics sampling failed: {type(e).__name__}: {e}")

            elapsed = time.time() - start
            sleep_s = max(0.1, float(settings.sampling_interval_seconds) - elapsed)
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=sleep_s)
            except asyncio.TimeoutError:
                continue

        logger.info("metrics sampler stopped")

    def stop(self) -> None:
        self._stop_event.set()

    def get_status(self) -> dict:
        return {
            "sampling_interval_seconds": int(settings.sampling_interval_seconds),
            "retention_days": int(settings.retention_days),
            "gpu": self._gpu_reader.get_status(),
        }

    def _collect_once(self) -> MetricsSample:
        import psutil  # type: ignore

        ts = int(time.time())
        cpu_usage = float(psutil.cpu_percent(interval=None))
        cpu_temp_c = _get_cpu_temp_c()

        vm = psutil.virtual_memory()
        mem_percent = float(vm.percent)
        mem_used = int(vm.used)
        mem_total = int(vm.total)

        gpu = self._gpu_reader.read()

        return MetricsSample(
            ts=ts,
            cpu_usage=cpu_usage,
            cpu_temp_c=cpu_temp_c,
            mem_percent=mem_percent,
            mem_used_bytes=mem_used,
            mem_total_bytes=mem_total,
            gpu_usage=gpu.usage,
            gpu_temp_c=gpu.temp_c,
            gpu_name=gpu.name,
        )

    async def _apply_retention(self) -> None:
        if settings.retention_days <= 0:
            return
        now = time.time()
        if now - self._last_retention_at < 60:
            return
        self._last_retention_at = now
        threshold = int(time.time() - settings.retention_days * 86400)
        deleted = await asyncio.to_thread(self._store.delete_older_than, threshold)
        if deleted:
            logger.info(f"retention cleanup deleted {deleted} rows")
