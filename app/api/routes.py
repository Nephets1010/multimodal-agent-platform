"""7 组 REST 端点 + ``/health`` 组件报告 + SSE ``StreamingResponse``。

所有端点通过 ``request.app.state.ctx`` 拿组合根，**不得 import ``app.main``**（避免循环）。
成功响应直接返回业务 JSON（S1）；错误统一 ``{"detail": "可读中文"}``。
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from app import __version__
from app.agent.state import AgentState, make_trace_id
from app.api.guards import cleanup_temporary, save_temporary, validate_uploads
from app.generation.router import build_unified_response, format_sse
from app.modalities import PROCESSORS, detect_modality
from app.observability.logging import get_logger
from app.schemas import (
    ChatRequest,
    EvalError,
    EvalRequest,
    HealthComponents,
    HealthResponse,
    IngestChunkItem,
    IngestError,
    IngestResponse,
    ModalityError,
    PlatformError,
    RawInput,
    Status,
    ToolsResponse,
    TraceEvent,
    TraceResponse,
)

if TYPE_CHECKING:
    from app.runtime import AppContext

#: 组合根 once 保护：仅保证并发下 ``build_context()`` 只调用一次，不是索引写入锁。
_CTX_LOCK = threading.Lock()

router = APIRouter()
logger = get_logger("api.routes")

_PROBE_KEYS: tuple[str, ...] = (
    "langgraph",
    "chromadb",
    "whisper",
    "cv2",
    "transformers",
    "openai",
)


def _ctx(request: Request) -> "AppContext":
    """取组合根；若调用方未进入 lifespan（如 ``TestClient(app)`` 不带 ``with``），
    则懒装配一次并缓存，仍复用**同一个** ``build_context()``，不改变唯一装配入口。
    """
    ctx = getattr(request.app.state, "ctx", None)
    if ctx is None:
        # 双重检查 + once 锁：并发下保证 build_context() 只调用一次（非索引写入锁）。
        with _CTX_LOCK:
            ctx = getattr(request.app.state, "ctx", None)
            if ctx is None:
                from app.runtime import build_context  # 局部导入，避免循环

                ctx = build_context()
                request.app.state.ctx = ctx
    return ctx


# --------------------------------------------------------------------------- #
# EP-1 GET /health
# --------------------------------------------------------------------------- #


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    ctx = _ctx(request)
    # ``components`` 的 graph/encoder/vector/llm 一律报告**实际生效**后端，
    # 不报配置声明值：生产模式发生降级时配置值仍为 api/chroma 会误导运维。
    effective = ctx.effective_backends
    components = HealthComponents(
        graph=effective.get("graph", ctx.graph_backend),
        encoder=effective.get("encoder", ctx.settings.encoder.backend),
        vector=effective.get("vector", ctx.settings.vector_store.backend),
        llm=effective.get("llm", ctx.settings.llm.backend),
        index_chunks=ctx.index.count(),
        langgraph=ctx.probes.get("langgraph", "fallback"),
        chromadb=ctx.probes.get("chromadb", "fallback"),
        whisper=ctx.probes.get("whisper", "fallback"),
        cv2=ctx.probes.get("cv2", "fallback"),
        transformers=ctx.probes.get("transformers", "fallback"),
        openai=ctx.probes.get("openai", "fallback"),
    )
    # 运行时降级强制反映到对应探测项
    for key in _PROBE_KEYS:
        if key in ctx.fallback_flags:
            setattr(components, key, "fallback")

    has_fallback = any(
        getattr(components, key) == "fallback" for key in _PROBE_KEYS
    ) or bool(ctx.fallback_flags)
    status = Status.DEGRADED if has_fallback else Status.OK

    # 配置声明值只在生产模式附加（DEMO 下配置值==生效值，响应保持与既有契约完全一致）。
    configured = dict(ctx.configured_backends) if not ctx.settings.demo.enabled else None
    return HealthResponse(
        demo_mode=bool(ctx.settings.demo.enabled),
        components=components,
        status=status,
        version=__version__,
        index_chunks=components.index_chunks,
        configured_backends=configured,
    ).model_dump(mode="json", exclude_none=True)


# --------------------------------------------------------------------------- #
# EP-2 POST /v1/ingest
# --------------------------------------------------------------------------- #


@router.post("/v1/ingest")
async def ingest(
    request: Request,
    files: list[UploadFile] = File(default=[]),
    text: str = Form(""),
    source_tag: str = Form("webui"),
) -> dict[str, Any]:
    """三个参数都要默认值（前端 ``text`` 仅在非空时 append，Q3 不得破坏 FormData 流程）。"""
    ctx = _ctx(request)
    uploads = await validate_uploads(list(files or []), ctx.settings)
    temporary_paths: list[Any] = []
    chunks: list[Any] = []

    try:
        for safe_name, data, mime in uploads:
            try:
                temporary_path = save_temporary(data, safe_name, ctx.paths.tmp_dir)
            except OSError as exc:
                # 复用既有 IngestError(400) 映射，不新增全局 handler。
                raise IngestError(
                    "临时文件写入失败：文件名过长或磁盘不可用，请缩短文件名后重试"
                ) from exc
            temporary_paths.append(temporary_path)
            try:
                modality = detect_modality(safe_name, mime, ctx.settings)
                raw = RawInput(
                    name=safe_name,
                    content=data,
                    mime=mime,
                    source_tag=source_tag,
                    # 视频需要已落盘的临时文件路径；processor 本身不写文件。
                    text=str(temporary_path) if modality == "video" else None,
                )
                produced = PROCESSORS[modality]().process(raw, ctx.settings)
                for chunk in produced:
                    if chunk.metadata.get("fallback"):
                        logger.warning(
                            "模态降级：%s 使用确定性降级链路",
                            safe_name,
                            extra={"event": "modality_fallback", "fallback": True},
                        )
                chunks.extend(produced)
            except ModalityError as exc:
                # 单模态失败隔离：跳过该文件 + warning，其余继续（NF-1）
                logger.warning(
                    "单模态解析失败，跳过文件 %s：%s",
                    safe_name,
                    exc.detail,
                    extra={"event": "modality_failed", "fallback": True},
                )
                continue

        if text and text.strip():
            raw_text = RawInput(
                name="pasted.txt",
                content=text.encode("utf-8"),
                mime="text/plain",
                source_tag=source_tag,
                text=text,
            )
            try:
                chunks.extend(PROCESSORS["text"]().process(raw_text, ctx.settings))
            except ModalityError as exc:
                logger.warning(
                    "粘贴文本解析失败：%s",
                    exc.detail,
                    extra={"event": "modality_failed", "fallback": True},
                )

        if chunks:
            ctx.index.ingest_chunks(chunks)

        snippet_chars = int(ctx.settings.retrieval.snippet_chars)
        items = [
            IngestChunkItem(
                chunk_id=chunk.chunk_id,
                source_id=chunk.source_id,
                modality=chunk.modality,
                snippet=chunk.content[:snippet_chars],
            )
            for chunk in chunks
        ]
        ctx.tracer.emit(
            TraceEvent(
                ts=datetime.now(timezone.utc).isoformat(),
                trace_id=make_trace_id("ingest", source_tag),
                session_id="default",
                event="ingest",
                node="ingest",
                steps=len(items),
                status="ok",
                elapsed_ms=0.0,
                state_snapshot={
                    "ingested_chunks": len(items),
                    "source_tag": source_tag,
                },
            )
        )
        return IngestResponse(chunks=items, total=len(items)).model_dump(mode="json")
    finally:
        cleanup_temporary(temporary_paths)


# --------------------------------------------------------------------------- #
# EP-3 POST /v1/chat（非流式 / SSE）
# --------------------------------------------------------------------------- #


@router.post("/v1/chat")
async def chat(request: Request, payload: ChatRequest) -> Any:
    ctx = _ctx(request)
    query = (payload.query or "").strip()
    if not query:
        raise PlatformError("query 不能为空", http_status=400)
    if len(query) > int(ctx.settings.agent.max_query_chars):
        raise PlatformError(
            f"query 长度超过上限 {ctx.settings.agent.max_query_chars} 字符",
            http_status=400,
        )

    trace_id = make_trace_id(query, payload.session_id)
    state = AgentState(
        trace_id=trace_id,
        session_id=payload.session_id,
        query=query,
        max_steps=int(ctx.settings.agent.max_steps),
        last_debug={"modalities": list(payload.modalities or [])},
    )

    if not payload.stream:
        final = ctx.graph.run(state)
        response = build_unified_response(
            final, ctx.settings, trace_id, final.elapsed_ms
        )
        return JSONResponse(response.model_dump(mode="json"))

    def _frames() -> Iterator[tuple[str, dict[str, Any]]]:
        """产出 ``(event, data)`` 元组；异常时兜底补一帧 ``done``（恒为最后一帧）。"""
        try:
            yield from ctx.graph.stream_events(state)
        except (GeneratorExit, asyncio.CancelledError):
            raise
        except Exception as exc:
            logger.error(
                "SSE 生成异常：%s",
                type(exc).__name__,
                exc_info=True,
                extra={"event": "sse_error", "trace_id": trace_id},
            )
            emergency = build_unified_response(state, ctx.settings, trace_id, 0.0)
            yield ("done", emergency.model_dump(mode="json"))

    def _generate() -> Iterator[str]:
        """帧字节串的**唯一**产出点：所有 data 都经同一个 ``format_sse``。"""
        try:
            for event_name, data in _frames():
                yield format_sse(event_name, data)
        except (GeneratorExit, asyncio.CancelledError):
            # 断连：停止迭代、不写半帧、记 warning
            logger.warning(
                "SSE 客户端断连，停止迭代",
                extra={"event": "sse_client_disconnected", "trace_id": trace_id},
            )
            raise
        finally:
            logger.info(
                "SSE 流结束",
                extra={"event": "sse_completed", "trace_id": trace_id},
            )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# EP-4 GET /v1/trace/{trace_id}
# --------------------------------------------------------------------------- #


@router.get("/v1/trace/{trace_id}")
async def trace(request: Request, trace_id: str) -> dict[str, Any]:
    ctx = _ctx(request)
    events = ctx.tracer.replay(trace_id)
    if not events:
        # Q7：不存在返回 HTTP 200 空集 + warning，绝不 404
        logger.warning(
            "trace_not_found: %s",
            trace_id,
            extra={"event": "trace_not_found", "trace_id": trace_id},
        )
        return TraceResponse(events=[], count=0).model_dump(mode="json")
    return TraceResponse(events=events, count=len(events)).model_dump(mode="json")


# --------------------------------------------------------------------------- #
# EP-5 GET /v1/tools
# --------------------------------------------------------------------------- #


@router.get("/v1/tools")
async def tools(request: Request) -> dict[str, Any]:
    ctx = _ctx(request)
    return ToolsResponse(
        tools=ctx.tools.describe(),
        whitelist=ctx.tools.whitelist(),
        max_steps=int(ctx.settings.agent.max_steps),
        tool_timeout_seconds=float(ctx.settings.agent.tool_timeout_seconds),
    ).model_dump(mode="json")


# --------------------------------------------------------------------------- #
# EP-6 POST /v1/eval
# --------------------------------------------------------------------------- #


@router.post("/v1/eval")
async def evaluate(request: Request, payload: EvalRequest | None = None) -> dict[str, Any]:
    ctx = _ctx(request)
    override = payload.samples if payload is not None else None
    # TD-16：显式样本数超过 eval.max_samples 时 400；{} / None 走内置 default_samples 路径。
    if override is not None and len(override) > ctx.settings.eval.max_samples:
        raise EvalError(
            f"评测样本数 {len(override)} 超过上限 {ctx.settings.eval.max_samples}，"
            "请减少 samples 或分批评测"
        )
    return ctx.evaluator.evaluate(override).model_dump(mode="json")


__all__ = ["router"]
