"""
配置管理模块
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        env_prefix="ARGUS_",
    )

    app_name: str = "Argus"
    app_version: str = "0.1.0"
    debug: bool = False

    host: str = "127.0.0.1"
    port: int = 8890

    api_prefix: str = "/api/v1"

    # ========== ServiceAtlas ==========
    registry_enabled: bool = True
    registry_url: str = "http://127.0.0.1:8888"
    service_id: str = "argus"
    service_name: str = "Argus Host Telemetry"
    service_host: str = "127.0.0.1"
    service_port: int = 8890
    heartbeat_interval: int = 30

    # ========== Auth (声明给 Hermes 的路由认证配置) ==========
    aegis_service_id: str = "aegis"
    require_auth: bool = True

    # ========== Metrics ==========
    db_path: str = "./argus.db"
    sampling_interval_seconds: int = 2
    retention_days: int = 7

    # CPU 温度选源（Linux hwmon）
    # - cpu_temp_sysfs_path: 直接指定 sysfs 路径（例如 /sys/class/hwmon/hwmon3/temp1_input）
    # - cpu_temp_preferred_chip/label: 在自动选源时偏好某个 chip 或 label（子串匹配）
    cpu_temp_sysfs_path: str = ""
    cpu_temp_preferred_chip: str = ""
    cpu_temp_preferred_label: str = ""
    cpu_temp_min_score: int = 80
    cpu_temp_cache_ttl_seconds: int = 300

    # GPU 采集（可选）
    gpu_enabled: bool = True
    gpu_index: int = 0


settings = Settings()
BASE_DIR = Path(__file__).resolve().parent.parent.parent
