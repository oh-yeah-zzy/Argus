# Argus

Argus 是一个主机指标监视与可视化服务，提供：
- CPU 占用 / 温度
- 内存占用
- GPU 占用 / 温度（可选：NVIDIA）
- 历史指标记录与可视化 Dashboard

## 运行

```bash
cd Argus
pip install -r requirements.txt
python run.py --reload --debug
```

默认监听：`http://127.0.0.1:8890/`

## 接入整体系统（ServiceAtlas + Hermes + Aegis）

Argus 会在启动时尝试注册到 ServiceAtlas（可通过环境变量关闭），并在 ServiceAtlas 中声明 `auth_config`，由 Hermes 网关的认证插件统一对接 Aegis 登录。

典型访问方式（通过 Hermes 网关）：
- `http://<hermes_host>:<hermes_port>/argus/`

常用环境变量：
- `ARGUS_HOST` / `ARGUS_PORT`
- `ARGUS_REGISTRY_ENABLED=true|false`
- `ARGUS_REGISTRY_URL=http://127.0.0.1:8888`
- `ARGUS_SERVICE_HOST=127.0.0.1`（注册到 ServiceAtlas 的对外地址）
- `ARGUS_AEGIS_SERVICE_ID=aegis`（用于声明路由认证服务）

## GPU 支持

- NVIDIA：安装 `nvidia-ml-py`（提供 `pynvml`）或确保 `nvidia-smi` 可用。

## CPU 温度选源（Linux）

默认优先从 `/sys/class/hwmon` 自动选择更像 CPU 的传感器；如需更精确可指定：
- `ARGUS_CPU_TEMP_SYSFS_PATH=/sys/class/hwmon/hwmonX/tempY_input`
- 或用 `ARGUS_CPU_TEMP_PREFERRED_CHIP` / `ARGUS_CPU_TEMP_PREFERRED_LABEL` 引导自动选源
- `ARGUS_CPU_TEMP_MIN_SCORE` 可调整自动选源的严格程度（越高越严格，可能返回空温度）
