"""
Argus FastAPI 应用入口
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.v1.metrics import router as metrics_router
from app.core.config import BASE_DIR, settings
from app.core.logging import get_logger
from app.integrations.serviceatlas import ServiceAtlasRegistration, create_registrar
from app.services.sampler import MetricsSampler
from app.services.storage import SqliteMetricsStore
from app.web.routes import router as web_router

logger = get_logger("argus.app")


def _build_service_meta() -> dict:
    # API 文档不再公开，需要认证后才能访问
    # 仅保留健康检查和静态资源为公开路径
    public_paths = [
        f"/{settings.service_id}/health",
        f"/{settings.service_id}/ready",
        f"/{settings.service_id}/static/**",
    ]
    return {
        "version": settings.app_version,
        "service_type": "monitoring",
        "description": "主机指标监视与历史可视化",
        "icon": "cloud",
        "auth_config": {
            "require_auth": bool(settings.require_auth),
            "auth_service_id": settings.aegis_service_id,
            "public_paths": public_paths,
        },
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 初始化存储
    store = SqliteMetricsStore(settings.db_path)
    store.init_db()
    app.state.metrics_store = store

    # 模板与静态
    templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "web" / "templates"))
    app.state.templates = templates

    # 指标采集后台任务
    sampler = MetricsSampler(store)
    app.state.sampler = sampler
    sampler_task = asyncio.create_task(sampler.run())

    # ServiceAtlas 注册（可选）
    registry_client = None
    if settings.registry_enabled:
        try:
            reg = ServiceAtlasRegistration(
                registry_url=settings.registry_url,
                service_id=settings.service_id,
                service_name=settings.service_name,
                host=settings.service_host,
                port=settings.service_port or settings.port,
                health_check_path="/health",
                metadata=_build_service_meta(),
                heartbeat_interval=settings.heartbeat_interval,
            )
            registry_client = await create_registrar(reg)
            await registry_client.start()
            logger.info("registered to ServiceAtlas")
        except Exception as e:
            logger.warning(f"ServiceAtlas registration failed: {type(e).__name__}: {e}")

    try:
        yield
    finally:
        sampler.stop()
        sampler_task.cancel()
        try:
            await sampler_task
        except asyncio.CancelledError:
            pass

        if registry_client is not None:
            try:
                await registry_client.stop()
            except Exception:
                pass


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(directory=str(BASE_DIR / "app" / "web" / "static")),
    name="static",
)

# Web
app.include_router(web_router)

# API
app.include_router(metrics_router, prefix=settings.api_prefix, tags=["metrics"])


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/ready")
async def ready():
    return {"status": "ready"}
