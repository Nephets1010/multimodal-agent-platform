"""API 层：导出唯一 ``router`` 供 ``app/main.py`` 注册。"""

from __future__ import annotations

from app.api.routes import router

__all__ = ["router"]
