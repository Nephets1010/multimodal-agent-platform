"""唯一组合根（U12 裁决）：``AppContext`` + ``build_context()``。

``app/main.py``、``scripts/demo.py``、``tests/conftest.py`` 三处复用同一个
``build_context()``，不得各自 new 依赖。本模块**无 FastAPI 构造副作用**，
因此 demo / tests 导入它不会连带创建应用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING

from app.agent.graph import build_graph
from app.agent.state import make_trace_id  # noqa: F401 - 供组合根使用方统一复用
from app.agent.tools import ToolRegistry
from app.config import (
    Paths,
    Settings,
    get_settings,
    probe_optional_dependencies,
    resolve_paths,
)
from app.generation.router import AnswerGenerator
from app.modalities.text import TextProcessor
from app.observability.evaluator import Evaluator
from app.observability.logging import configure_logging, get_logger, is_configured
from app.observability.tracer import AgentTracer
from app.rag.encoder import BaseEncoder, build_encoder
from app.rag.retriever import HybridRetriever
from app.rag.store import VectorIndex, VectorStore, build_store

if TYPE_CHECKING:
    from app.agent.graph import CompiledGraph


@dataclass
class AppContext:
    """全进程唯一的依赖容器；``graph`` / ``evaluator`` 在装配最后两步注入。"""

    settings: Settings
    paths: Paths
    probes: dict[str, str]
    encoder: BaseEncoder
    store: VectorStore
    index: VectorIndex
    retriever: HybridRetriever
    tools: ToolRegistry
    graph: "CompiledGraph"
    tracer: AgentTracer
    evaluator: "Evaluator"
    generator: AnswerGenerator
    graph_backend: str
    fallback_flags: list[str]
    started_at: float
    #: 配置层声明的后端值（``/health.configured_backends``）。
    configured_backends: dict[str, str] = field(default_factory=dict)
    #: 实际生效的后端值（``/health.components`` 的 graph/encoder/vector/llm 一律取这里）。
    #: 与 configured_backends 是两条独立数据流：降级时二者不同。
    effective_backends: dict[str, str] = field(default_factory=dict)


def build_context(settings: Settings | None = None) -> AppContext:
    """按固定顺序装配全部依赖；所有降级写入 ``fallback_flags`` + warning 日志。"""
    active_settings: Settings = settings if settings is not None else get_settings()
    paths = resolve_paths()
    if not is_configured():
        configure_logging(active_settings)
    logger = get_logger("runtime")

    probes = probe_optional_dependencies()
    fallback_flags: list[str] = []
    flags = SimpleNamespace(fallback_flags=fallback_flags)

    encoder = build_encoder(active_settings, flags)
    store = build_store(active_settings, paths, flags)
    index = VectorIndex(encoder, store, active_settings, paths)
    index.load()
    # 注入 T02 的 TextProcessor，store.py 不 import modalities（ARCH §1.3 铁律 2）。
    index.ensure_bootstrap(TextProcessor())

    retriever = HybridRetriever(index, active_settings)
    tools = ToolRegistry(retriever, active_settings)  # 注册 4 个白名单工具
    generator = AnswerGenerator(active_settings)
    tracer = AgentTracer(paths, active_settings)

    ctx = AppContext(
        settings=active_settings,
        paths=paths,
        probes=probes,
        encoder=encoder,
        store=store,
        index=index,
        retriever=retriever,
        tools=tools,
        graph=None,  # type: ignore[arg-type] - 下一步由 build_graph 注入
        tracer=tracer,
        evaluator=None,  # type: ignore[arg-type] - 需要 ctx 自身，最后注入
        generator=generator,
        graph_backend="pure",
        fallback_flags=fallback_flags,
        started_at=time.time(),
    )
    ctx.graph = build_graph(active_settings, ctx)
    ctx.evaluator = Evaluator(ctx)

    # ---- 配置声明值 vs 实际生效后端（两条独立数据流，供 /health 如实报告）----
    # 声明值只反映 settings；生效值在降级后与声明值分离，避免运维误判。
    ctx.configured_backends.update(
        {
            "llm": active_settings.llm.backend,
            "encoder": active_settings.encoder.backend,
            "vector": active_settings.vector_store.backend,
            "graph": (
                "pure"
                if active_settings.demo.enabled or probes.get("langgraph") != "native"
                else "langgraph"
            ),
        }
    )

    effective_encoder = active_settings.encoder.backend
    if any(
        flag in ctx.fallback_flags
        for flag in ("api_encoder", "transformers_encoder", "encoder")
    ):
        effective_encoder = "stub"
    effective_vector = active_settings.vector_store.backend
    if "chroma" in ctx.fallback_flags:
        effective_vector = "memory"
    effective_llm = active_settings.llm.backend
    if active_settings.demo.enabled or not (
        active_settings.llm.api_key and active_settings.llm.base_url
    ):
        effective_llm = "template"
    ctx.effective_backends.update(
        {
            "llm": effective_llm,
            "encoder": effective_encoder,
            "vector": effective_vector,
            "graph": ctx.graph_backend,  # build_graph 写回的实际生效值
        }
    )

    logger.info(
        "组合根装配完成：graph_backend=%s index_chunks=%d fallbacks=%s",
        ctx.graph_backend,
        ctx.index.count(),
        ",".join(ctx.fallback_flags) or "none",
        extra={"event": "context_built", "fallback": bool(ctx.fallback_flags)},
    )
    return ctx


__all__ = ["AppContext", "build_context"]
