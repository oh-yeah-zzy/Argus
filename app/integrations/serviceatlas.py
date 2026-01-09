"""
ServiceAtlas 注册集成

优先使用 serviceatlas_client（如果已安装），否则使用内置的轻量实现。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.logging import get_logger

logger = get_logger("argus.integrations.serviceatlas")


@dataclass(frozen=True)
class ServiceAtlasRegistration:
    registry_url: str
    service_id: str
    service_name: str
    host: str
    port: int
    protocol: str = "http"
    health_check_path: str = "/health"
    is_gateway: bool = False
    base_path: str = ""
    metadata: Optional[dict[str, Any]] = None
    heartbeat_interval: int = 30


class ServiceAtlasRegistrar:
    def __init__(self, config: ServiceAtlasRegistration):
        self._cfg = config
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        await self._register()
        self._task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._unregister()

    async def _register(self) -> None:
        url = self._cfg.registry_url.rstrip("/") + "/api/v1/services"
        payload: dict[str, Any] = {
            "id": self._cfg.service_id,
            "name": self._cfg.service_name,
            "host": self._cfg.host,
            "port": self._cfg.port,
            "protocol": self._cfg.protocol,
            "health_check_path": self._cfg.health_check_path,
            "is_gateway": self._cfg.is_gateway,
            "service_meta": self._cfg.metadata or {},
        }
        if self._cfg.base_path:
            payload["base_path"] = self._cfg.base_path

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()

    async def _unregister(self) -> None:
        url = self._cfg.registry_url.rstrip("/") + f"/api/v1/services/{self._cfg.service_id}"
        async with httpx.AsyncClient(timeout=5) as client:
            try:
                await client.delete(url)
            except Exception:
                return

    async def _heartbeat_loop(self) -> None:
        url = self._cfg.registry_url.rstrip("/") + f"/api/v1/services/{self._cfg.service_id}/heartbeat"

        while not self._stop_event.is_set():
            try:
                async with httpx.AsyncClient(timeout=5) as client:
                    await client.post(url)
            except Exception as e:
                logger.warning(f"heartbeat failed: {type(e).__name__}: {e}")

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._cfg.heartbeat_interval)
            except asyncio.TimeoutError:
                continue


async def create_registrar(config: ServiceAtlasRegistration):
    """
    创建注册器：优先使用 serviceatlas_client（如果可用），否则使用内置实现。
    """
    try:
        from serviceatlas_client.client import AsyncServiceAtlasClient  # type: ignore

        client = AsyncServiceAtlasClient(
            registry_url=config.registry_url,
            service_id=config.service_id,
            service_name=config.service_name,
            host=config.host,
            port=config.port,
            protocol=config.protocol,
            health_check_path=config.health_check_path,
            is_gateway=config.is_gateway,
            base_path=config.base_path,
            metadata=config.metadata,
            heartbeat_interval=config.heartbeat_interval,
        )
        return client
    except Exception:
        return ServiceAtlasRegistrar(config)

