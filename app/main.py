"""FastAPI 应用工厂、统一异常处理器与同源静态托管。

刻意把「装配逻辑」放在 ``app/runtime.py::build_context()``（U12 裁决），
本模块只负责：配置/日志初始化 → 注册异常处理器与静态路由 → lifespan 装配组合根。
``app/runtime`` 与 ``app/api/routes`` 在 T04 落地，此处的 import 是刻意的前向依赖。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from app import __version__
from app.api import router
from app.config import get_settings, resolve_paths
from app.observability.logging import configure_logging, get_logger
from app.runtime import build_context
from app.schemas import PlatformError


def create_app() -> FastAPI:
    """构建并返回 FastAPI 应用；``/docs`` 保持 FastAPI 默认开启（Q13）。"""
    settings = get_settings()
    paths = resolve_paths()
    configure_logging(settings)
    logger = get_logger("app.main")

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        # 三处（main / demo.py / conftest.py）复用同一个 build_context()；
        # 若调用方已预置 ctx（demo / tests 需要复用同一份装配），则不重复构造。
        if getattr(application.state, "ctx", None) is None:
            application.state.ctx = build_context()
        logger.warning(
            "未实现鉴权/多租户/会话持久化/并发写入锁，"
            "仅限本机或可信内网单机演示，勿暴露公网",
            extra={"event": "startup", "fallback": False},
        )
        try:
            yield
        finally:
            ctx = getattr(application.state, "ctx", None)
            if ctx is not None:
                try:
                    ctx.tools.shutdown()
                except Exception:
                    logger.warning("tools shutdown 失败", extra={"event": "shutdown"})
                try:
                    ctx.tracer.close()
                except Exception:
                    logger.warning("tracer close 失败", extra={"event": "shutdown"})

    application = FastAPI(
        title="多模态通用智能体开发平台",
        version=__version__,
        description="四模态统一接入 → 混合检索 RAG → Planner/Worker/Reflector → SSE 统一应答",
        lifespan=lifespan,
    )

    # ---- 三个异常处理器：一律 {"detail": 可读中文}，堆栈/密钥绝不直出 HTTP ----
    @application.exception_handler(PlatformError)
    async def _platform_error_handler(request: Request, exc: PlatformError) -> JSONResponse:
        logger.warning(
            "platform_error: %s",
            exc.detail,
            extra={"event": "platform_error", "trace_id": "-"},
        )
        return JSONResponse(status_code=exc.http_status, content={"detail": exc.detail})

    @application.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        parts: list[str] = []
        for error in (exc.errors() or [])[:3]:
            location = ".".join(str(item) for item in error.get("loc", []))
            parts.append(f"{location}: {error.get('msg', '参数不合法')}")
        detail = "请求参数不合法：" + "；".join(parts) if parts else "请求参数不合法"
        logger.warning(detail, extra={"event": "validation_error", "trace_id": "-"})
        return JSONResponse(status_code=422, content={"detail": detail})

    @application.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "内部错误，请查看服务端日志",
            exc_info=(type(exc), exc, exc.__traceback__),
            extra={"event": "unhandled_exception", "trace_id": "-"},
        )
        return JSONResponse(
            status_code=500, content={"detail": "内部错误，请查看服务端日志"}
        )

    # ---- 两个静态路由：从任意 cwd 启动都基于 PROJECT_ROOT，不 404 ----
    @application.get("/", include_in_schema=False)
    async def _index() -> FileResponse:
        return FileResponse(paths.web_index_path, media_type="text/html")

    @application.get("/ui/index.html", include_in_schema=False)
    async def _ui_index() -> FileResponse:
        return FileResponse(paths.web_index_path, media_type="text/html")

    application.include_router(router)
    return application


app: FastAPI = create_app()


if __name__ == "__main__":
    # HOST=127.0.0.1 python3 -m app.main 可收紧监听；
    # Makefile 的 run 目标仍保持规格 §2 的 --host 0.0.0.0 --port 8000。
    _settings: Any = get_settings()
    uvicorn.run(
        "app.main:app",
        host=_settings.server.host,
        port=_settings.server.port,
    )
