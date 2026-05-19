"""Wolfpack 后端入口.

最常用:
    python main.py             # 起服务, 默认 DEBUG=False, 跑在 settings.port (8080)

热重载开发:
    WOLFPACK_DEBUG=true python main.py

也可以直接:
    uvicorn app.server:app --reload --port 8080

完整环境变量见 backend/.env.example.
"""

import uvicorn

from app.infra.settings import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.server:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        reload_dirs=["app"] if settings.debug else None,
        reload_excludes=["wolfpack-data/**"] if settings.debug else None,
        access_log=settings.access_log,
    )
