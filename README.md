<div align="center">

# Argus

**轻量级主机遥测服务**

[![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

实时监控主机指标，提供可视化 Dashboard

</div>

---

## 概述

Argus 是一个轻量级的主机遥测服务，用于实时监控和可视化主机性能指标。支持 CPU、内存、磁盘等核心指标的采集与展示，可选支持 NVIDIA GPU 监控。

### 核心特性

| 特性 | 说明 |
|------|------|
| **CPU 监控** | 占用率、温度（Linux hwmon 自动选源） |
| **内存监控** | 使用量、可用量、占用率 |
| **GPU 监控** | NVIDIA GPU 占用率、温度、显存（可选） |
| **历史记录** | SQLite 存储，支持 7 天数据保留 |
| **可视化** | 实时 Dashboard，图表展示 |
| **服务注册** | 可选集成 ServiceAtlas 服务发现 |

### 技术栈

- **后端**: Python 3.9+ / FastAPI / SQLAlchemy
- **数据库**: SQLite (异步)
- **前端**: Jinja2 模板 / Chart.js
- **GPU**: pynvml / nvidia-smi

---

## 快速开始

### 1. 安装依赖

```bash
cd Argus
pip install -r requirements.txt
```

### 2. 启动服务

```bash
# 基本启动
python run.py

# 开发模式（热重载）
python run.py --reload --debug

# 自定义端口
python run.py -p 8080
```

### 3. 访问

| 地址 | 说明 |
|------|------|
| http://127.0.0.1:8890 | Web Dashboard |
| http://127.0.0.1:8890/health | 健康检查 |

---

## 命令行参数

```bash
python run.py [选项]
```

| 参数 | 简写 | 说明 | 默认值 |
|------|------|------|--------|
| `--host` | `-H` | 监听地址 | 127.0.0.1 |
| `--port` | `-p` | 监听端口 | 8890 |
| `--debug` | | 启用调试模式 | false |
| `--reload` | | 启用热重载 | false |
| `--no-registry` | | 禁用服务注册 | false |
| `--registry-url` | | ServiceAtlas 地址 | http://127.0.0.1:8888 |

---

## 环境变量配置

创建 `.env` 文件或设置环境变量（前缀 `ARGUS_`）：

```bash
# === 服务配置 ===
ARGUS_HOST=127.0.0.1
ARGUS_PORT=8890

# === ServiceAtlas 集成 ===
ARGUS_REGISTRY_ENABLED=true
ARGUS_REGISTRY_URL=http://127.0.0.1:8888
ARGUS_SERVICE_HOST=127.0.0.1
ARGUS_HEARTBEAT_INTERVAL=30

# === 认证配置（由 Hermes 网关处理） ===
ARGUS_REQUIRE_AUTH=true
ARGUS_AEGIS_SERVICE_ID=aegis

# === 数据存储 ===
ARGUS_DB_PATH=./argus.db
ARGUS_SAMPLING_INTERVAL_SECONDS=2
ARGUS_RETENTION_DAYS=7

# === GPU 配置 ===
ARGUS_GPU_ENABLED=true
ARGUS_GPU_INDEX=0
```

---

## 与微服务生态集成

Argus 设计为微服务生态的一部分，可与 ServiceAtlas、Hermes、Aegis 协作：

```
用户 → Hermes (API网关) → 认证检查 → Argus
              ↓                ↓
       ServiceAtlas ←── 服务注册/发现
              ↓
           Aegis (认证服务)
```

### 通过网关访问

当注册到 ServiceAtlas 后，可通过 Hermes 网关访问：

```
http://<hermes_host>:<hermes_port>/argus/
```

Argus 在注册时会声明 `auth_config`，Hermes 的认证插件会自动对接 Aegis 进行登录验证。

---

## GPU 支持

### NVIDIA GPU

安装 `nvidia-ml-py` 或确保 `nvidia-smi` 可用：

```bash
pip install nvidia-ml-py
```

---

## CPU 温度选源（Linux）

Argus 默认从 `/sys/class/hwmon` 自动选择最像 CPU 的传感器。如需精确控制：

| 环境变量 | 说明 |
|---------|------|
| `ARGUS_CPU_TEMP_SYSFS_PATH` | 直接指定 sysfs 路径（如 `/sys/class/hwmon/hwmon3/temp1_input`） |
| `ARGUS_CPU_TEMP_PREFERRED_CHIP` | 偏好的芯片名称（子串匹配，如 `coretemp`） |
| `ARGUS_CPU_TEMP_PREFERRED_LABEL` | 偏好的标签名称（子串匹配，如 `package`） |
| `ARGUS_CPU_TEMP_MIN_SCORE` | 自动选源最低可信分（默认 80，越高越严格） |

---

## 项目结构

```
Argus/
├── app/
│   ├── api/v1/metrics.py       # API 路由
│   ├── core/
│   │   ├── config.py           # 配置管理
│   │   └── logging.py          # 日志配置
│   ├── integrations/
│   │   └── serviceatlas.py     # ServiceAtlas 集成
│   ├── services/
│   │   ├── sampler.py          # 指标采集
│   │   ├── storage.py          # 数据存储
│   │   └── temperature.py      # 温度传感器
│   ├── web/
│   │   ├── routes.py           # Web 路由
│   │   ├── templates/          # HTML 模板
│   │   └── static/             # CSS/JS
│   └── main.py                 # FastAPI 入口
├── run.py                      # 启动脚本
├── requirements.txt            # 依赖
└── .env.example                # 配置示例
```

---

## API 接口

| 接口 | 方法 | 说明 |
|------|:----:|------|
| `/api/v1/metrics/current` | GET | 获取当前指标 |
| `/api/v1/metrics/history` | GET | 获取历史数据 |
| `/health` | GET | 健康检查 |
| `/ready` | GET | 就绪检查 |

---

## 许可证

[MIT License](LICENSE)

---

<div align="center">

**Built with FastAPI**

</div>
