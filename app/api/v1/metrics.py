"""
指标 API
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Query, Request

from app.core.config import settings
from app.services.storage import MetricsSample, SqliteMetricsStore
from app.services.temperature import get_cpu_temp_status, list_hwmon_temperatures


router = APIRouter()


def _store(request: Request) -> SqliteMetricsStore:
    return request.app.state.metrics_store  # type: ignore[attr-defined]


def _format_sample(sample: MetricsSample) -> dict:
    return {
        "ts": sample.ts,
        "cpu": {"usage": sample.cpu_usage, "temp_c": sample.cpu_temp_c},
        "memory": {
            "percent": sample.mem_percent,
            "used_bytes": sample.mem_used_bytes,
            "total_bytes": sample.mem_total_bytes,
        },
        "gpu": {
            "usage": sample.gpu_usage,
            "temp_c": sample.gpu_temp_c,
            "name": sample.gpu_name,
        },
    }


@router.get("/metrics/latest", summary="获取最新指标")
async def latest_metrics(request: Request) -> dict:
    store = _store(request)
    sample = await _to_thread(store.get_latest)
    return {"sample": _format_sample(sample) if sample else None}


@router.get("/metrics/history", summary="获取历史指标")
async def metrics_history(
    request: Request,
    seconds: int = Query(3600, ge=10, le=86400 * 30, description="查询最近 N 秒"),
    end_ts: Optional[int] = Query(None, description="结束时间戳（秒），默认当前时间）"),
    limit: int = Query(2000, ge=10, le=20000, description="最大返回点数（将自动降采样）"),
) -> dict:
    store = _store(request)
    end = int(end_ts or time.time())
    start = int(end - seconds)
    samples, bucket_seconds, mode = await _to_thread(store.get_history_resampled, start, end, int(limit))
    return {
        "start_ts": start,
        "end_ts": end,
        "seconds": int(seconds),
        "max_points": int(limit),
        "mode": mode,
        "bucket_seconds": int(bucket_seconds),
        "count": len(samples),
        "samples": [_format_sample(s) for s in samples],
    }


@router.get("/metrics/sensors", summary="列出温度传感器（调试）")
async def sensors_debug() -> dict:
    hwmon = await _to_thread(list_hwmon_temperatures)
    hwmon_sorted = sorted(hwmon, key=lambda x: (x.score, x.temp_c), reverse=True)
    recommended = None
    if hwmon_sorted and hwmon_sorted[0].score >= int(settings.cpu_temp_min_score):
        s = hwmon_sorted[0]
        recommended = {
            "chip": s.chip,
            "label": s.label,
            "temp_c": s.temp_c,
            "score": s.score,
            "input_path": s.input_path,
        }

    cpu_status = await _to_thread(get_cpu_temp_status)

    return {
        "config": {
            "cpu_temp_sysfs_path": settings.cpu_temp_sysfs_path or None,
            "cpu_temp_preferred_chip": settings.cpu_temp_preferred_chip or None,
            "cpu_temp_preferred_label": settings.cpu_temp_preferred_label or None,
            "cpu_temp_min_score": int(settings.cpu_temp_min_score),
        },
        "cpu_temp": cpu_status,
        "hwmon_count": len(hwmon_sorted),
        "hwmon": [
            {
                "chip": s.chip,
                "label": s.label,
                "temp_c": s.temp_c,
                "score": s.score,
                "input_path": s.input_path,
            }
            for s in hwmon_sorted
        ],
        "recommended": recommended,
    }


@router.get("/metrics/status", summary="获取采集状态与选源信息")
async def metrics_status(request: Request) -> dict:
    sampler = getattr(request.app.state, "sampler", None)
    sampler_status = sampler.get_status() if sampler else None
    cpu_status = await _to_thread(get_cpu_temp_status)
    return {
        "sampling": sampler_status,
        "cpu_temp": cpu_status,
    }


async def _to_thread(func, *args, **kwargs):
    import asyncio

    return await asyncio.to_thread(func, *args, **kwargs)
