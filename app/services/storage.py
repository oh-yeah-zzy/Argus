"""
SQLite 指标存储
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class MetricsSample:
    ts: int
    cpu_usage: float
    cpu_temp_c: Optional[float]
    mem_percent: float
    mem_used_bytes: int
    mem_total_bytes: int
    gpu_usage: Optional[float]
    gpu_temp_c: Optional[float]
    gpu_name: Optional[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SqliteMetricsStore:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)

    def init_db(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS metrics_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    cpu_usage REAL NOT NULL,
                    cpu_temp_c REAL,
                    mem_percent REAL NOT NULL,
                    mem_used_bytes INTEGER NOT NULL,
                    mem_total_bytes INTEGER NOT NULL,
                    gpu_usage REAL,
                    gpu_temp_c REAL,
                    gpu_name TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_samples_ts ON metrics_samples(ts)")
            conn.commit()

    def insert_sample(self, sample: MetricsSample) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO metrics_samples (
                    ts, cpu_usage, cpu_temp_c,
                    mem_percent, mem_used_bytes, mem_total_bytes,
                    gpu_usage, gpu_temp_c, gpu_name
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sample.ts,
                    float(sample.cpu_usage),
                    sample.cpu_temp_c,
                    float(sample.mem_percent),
                    int(sample.mem_used_bytes),
                    int(sample.mem_total_bytes),
                    sample.gpu_usage,
                    sample.gpu_temp_c,
                    sample.gpu_name,
                ),
            )
            conn.commit()

    def get_latest(self) -> Optional[MetricsSample]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    ts, cpu_usage, cpu_temp_c,
                    mem_percent, mem_used_bytes, mem_total_bytes,
                    gpu_usage, gpu_temp_c, gpu_name
                FROM metrics_samples
                ORDER BY ts DESC
                LIMIT 1
                """
            ).fetchone()
        if not row:
            return None
        return MetricsSample(
            ts=int(row[0]),
            cpu_usage=float(row[1]),
            cpu_temp_c=row[2] if row[2] is None else float(row[2]),
            mem_percent=float(row[3]),
            mem_used_bytes=int(row[4]),
            mem_total_bytes=int(row[5]),
            gpu_usage=row[6] if row[6] is None else float(row[6]),
            gpu_temp_c=row[7] if row[7] is None else float(row[7]),
            gpu_name=row[8],
        )

    def get_history(self, start_ts: int, end_ts: int, limit: int) -> list[MetricsSample]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    ts, cpu_usage, cpu_temp_c,
                    mem_percent, mem_used_bytes, mem_total_bytes,
                    gpu_usage, gpu_temp_c, gpu_name
                FROM metrics_samples
                WHERE ts >= ? AND ts <= ?
                ORDER BY ts ASC
                LIMIT ?
                """,
                (int(start_ts), int(end_ts), int(limit)),
            ).fetchall()

        return [
            MetricsSample(
                ts=int(r[0]),
                cpu_usage=float(r[1]),
                cpu_temp_c=r[2] if r[2] is None else float(r[2]),
                mem_percent=float(r[3]),
                mem_used_bytes=int(r[4]),
                mem_total_bytes=int(r[5]),
                gpu_usage=r[6] if r[6] is None else float(r[6]),
                gpu_temp_c=r[7] if r[7] is None else float(r[7]),
                gpu_name=r[8],
            )
            for r in rows
        ]

    def get_history_resampled(
        self,
        start_ts: int,
        end_ts: int,
        max_points: int,
    ) -> tuple[list[MetricsSample], int, str]:
        """
        获取历史数据并按时间桶降采样，确保返回点数不超过 max_points。

        说明：
        - bucket_seconds=1 时近似等同于原始数据（每秒 1 桶）
        - bucket_seconds>1 时为聚合数据（按桶平均，ts 取桶内最大值）
        """
        start_ts = int(start_ts)
        end_ts = int(end_ts)
        max_points = max(1, int(max_points))

        span_seconds = max(1, end_ts - start_ts + 1)
        bucket_seconds = max(1, int(math.ceil(span_seconds / max_points)))
        mode = "raw" if bucket_seconds <= 1 else "avg_bucket"

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT
                    MAX(ts) as ts,
                    AVG(cpu_usage) as cpu_usage,
                    AVG(cpu_temp_c) as cpu_temp_c,
                    AVG(mem_percent) as mem_percent,
                    AVG(mem_used_bytes) as mem_used_bytes,
                    MAX(mem_total_bytes) as mem_total_bytes,
                    AVG(gpu_usage) as gpu_usage,
                    AVG(gpu_temp_c) as gpu_temp_c,
                    MAX(gpu_name) as gpu_name
                FROM metrics_samples
                WHERE ts >= ? AND ts <= ?
                GROUP BY CAST((ts - ?) / ? AS INTEGER)
                ORDER BY ts ASC
                """,
                (start_ts, end_ts, start_ts, bucket_seconds),
            ).fetchall()

        samples: list[MetricsSample] = []
        for r in rows:
            ts_v = r[0]
            if ts_v is None:
                continue
            samples.append(
                MetricsSample(
                    ts=int(ts_v),
                    cpu_usage=float(r[1] or 0.0),
                    cpu_temp_c=None if r[2] is None else float(r[2]),
                    mem_percent=float(r[3] or 0.0),
                    mem_used_bytes=int(r[4] or 0),
                    mem_total_bytes=int(r[5] or 0),
                    gpu_usage=None if r[6] is None else float(r[6]),
                    gpu_temp_c=None if r[7] is None else float(r[7]),
                    gpu_name=r[8],
                )
            )

        return samples, bucket_seconds, mode

    def delete_older_than(self, ts_threshold: int) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM metrics_samples WHERE ts < ?", (int(ts_threshold),))
            conn.commit()
            return int(cur.rowcount or 0)
