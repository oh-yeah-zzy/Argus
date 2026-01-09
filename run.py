#!/usr/bin/env python3
"""
Argus 启动脚本
"""

import argparse
import os
import sys

import uvicorn


def main() -> None:
    # 将项目目录添加到 Python 路径（便于直接运行）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    default_host = os.environ.get("ARGUS_HOST", "127.0.0.1")
    default_port = int(os.environ.get("ARGUS_PORT", "8890"))

    parser = argparse.ArgumentParser(description="Argus - Host Telemetry Dashboard")
    parser.add_argument(
        "-H",
        "--host",
        type=str,
        default=default_host,
        help=f"绑定地址 (默认: {default_host})",
    )
    parser.add_argument(
        "-p",
        "--port",
        type=int,
        default=default_port,
        help=f"监听端口 (默认: {default_port})",
    )
    parser.add_argument("--reload", action="store_true", help="启用热重载（开发模式）")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    args = parser.parse_args()

    # 同步环境变量，确保应用内配置与 CLI 一致（尤其是 ServiceAtlas 注册端口）
    os.environ["ARGUS_HOST"] = args.host
    os.environ["ARGUS_PORT"] = str(args.port)
    os.environ["ARGUS_SERVICE_HOST"] = os.environ.get("ARGUS_SERVICE_HOST", args.host)
    os.environ["ARGUS_SERVICE_PORT"] = os.environ.get("ARGUS_SERVICE_PORT", str(args.port))
    if args.debug:
        os.environ["ARGUS_DEBUG"] = "true"

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="debug" if args.debug else "info",
    )


if __name__ == "__main__":
    main()
