"""GET /healthz — 服务存活探针.

返回基本的服务状态. 后续 Electron Main 在 spawn 后会循环 ping 这个端点,
直到 200 才打开窗口加载页面 (避免页面 fetch 时后端还没起来).
"""

from fastapi import APIRouter


router = APIRouter()


@router.get("/healthz")
def healthz() -> dict:
    """服务存活检查. 始终返回 ok."""
    return {"status": "ok", "service": "wolfpack"}
