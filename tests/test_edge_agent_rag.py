"""QA 独立第二层验证 · Agent 编排 / RAG 边界与降级（NF-1 / NF-5 / P0-2 / P0-14）。

覆盖：最大步数保护与 Reflector 收敛、``resume()`` 图层恢复、``HUMAN_IN_LOOP=1``
的 human_required 位置、稠密全零回退与 ``last_debug.strategy`` 可观测、空索引、
损坏 ``vector_index.json`` 自动重建、软上限只告警不改口径、生产模式「配置声明值
vs 实际生效后端」两条独立数据流、轨迹快照脱敏。

运行期目录由 ``conftest._demo_env`` 隔离到 ``tmp_path``，不污染仓库 ``data/``。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.config as config
from app.agent.state import AgentState, make_trace_id
from app.generation.router import build_unified_response
from app.modalities.text import TextProcessor
from app.rag.store import InMemoryVectorStore, VectorIndex
from app.runtime import build_context


def _state(query: str, max_steps: int = 8) -> AgentState:
    return AgentState(
        trace_id=make_trace_id(query, "qa-edge"),
        session_id="qa-edge",
        query=query,
        max_steps=max_steps,
        last_debug={"modalities": []},
    )


@pytest.fixture
def edge_ctx():
    config.reset_settings_cache()
    context = build_context()
    try:
        yield context
    finally:
        context.tools.shutdown()
        context.tracer.close()
        config.reset_settings_cache()


@pytest.fixture
def ctx_factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """在装配组合根之前注入自定义环境变量，支持 DEMO / 生产切换。"""
    created: list[Any] = []

    def _factory(**env: str):
        monkeypatch.setenv("DEMO_MODE", env.pop("DEMO_MODE", "1"))
        for key, value in env.items():
            monkeypatch.setenv(key, str(value))
        monkeypatch.setitem(config._PATH_OVERRIDES, "data_dir", tmp_path / "data")
        monkeypatch.setitem(config._PATH_OVERRIDES, "tmp_dir", tmp_path / "data" / "tmp")
        config.reset_settings_cache()
        context = build_context()
        created.append(context)
        return context

    try:
        yield _factory
    finally:
        for context in created:
            context.tools.shutdown()
            context.tracer.close()
        config.reset_settings_cache()


def _client(context) -> TestClient:
    from app.main import app

    app.state.ctx = context
    return TestClient(app)


# --------------------------------------------------------------------------- #
# 编排层边界
# --------------------------------------------------------------------------- #


class TestGraphBoundary:
    def test_max_steps_forces_reflector_convergence(self, edge_ctx):
        """工具失败触发重规划时，``max_steps=2`` 必须强制收敛，不得无限循环。"""
        state = _state("计算 1/0 的结果 并统计字数", max_steps=2)
        final = edge_ctx.graph.run(state)
        assert final.answer
        assert final.next_node == "done"
        assert final.steps <= max(3, 2 * 3)
        assert final.last_debug.get("need_replan") is False

    def test_resume_clears_breakpoint_and_converges(self, edge_ctx):
        state = _state("你好")
        state.human_required = True
        state.pending_step = "reflector"
        state.answer = "旧的未确认答案"
        resumed = edge_ctx.graph.resume(state, "approved")
        assert resumed.human_required is False
        assert resumed.pending_step is None
        assert resumed.next_node == "done"
        assert resumed.answer
        assert resumed.last_debug.get("resumed") is True

    def test_resume_with_non_approved_decision_keeps_state(self, edge_ctx):
        state = _state("你好")
        state.human_required = True
        assert edge_ctx.graph.resume(state, "rejected") is state

    def test_human_in_loop_emits_human_required_after_tokens_before_done(self, ctx_factory):
        context = ctx_factory(HUMAN_IN_LOOP="1")
        assert context.settings.agent.human_in_loop is True
        frames = list(context.graph.stream_events(_state("你好")))
        names = [name for name, _ in frames]
        assert names[0] == "meta"
        assert names[-1] == "done"
        assert names.count("done") == 1
        assert "human_required" in names
        assert names.index("human_required") < names.index("done")
        assert names.index("human_required") > max(i for i, n in enumerate(names) if n == "step")
        assert names.index("human_required") > max(i for i, n in enumerate(names) if n == "token")
        human = dict(frames[names.index("human_required")][1])
        assert "prompt" in human and human["prompt"]
        assert set(dict(frames[-1][1])) == {
            "answer",
            "evidences",
            "tool_calls",
            "tool_results",
            "trace_id",
            "steps",
            "elapsed_ms",
            "status",
            "output_modality",
            "demo_mode",
            "graph_backend",
        }

    def test_non_stream_and_sse_done_share_same_builder(self, edge_ctx, monkeypatch):
        """ARCH §7-A13：非流式与 SSE done 必须由同一个 build_unified_response 产出。"""
        import importlib

        graph_module = importlib.import_module("app.agent.graph")
        routes_module = importlib.import_module("app.api.routes")
        router_module = importlib.import_module("app.generation.router")

        assert graph_module.build_unified_response is router_module.build_unified_response
        assert routes_module.build_unified_response is router_module.build_unified_response

        calls: list[int] = []
        original = router_module.build_unified_response

        def _spy(*args: Any, **kwargs: Any):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(graph_module, "build_unified_response", _spy)

        final = edge_ctx.graph.run(_state("计算 12*8 的结果"))
        unified = original(final, edge_ctx.settings, final.trace_id, final.elapsed_ms)
        frames = list(edge_ctx.graph.stream_events(_state("计算 12*8 的结果")))
        done = frames[-1][1]

        assert calls == [1]
        assert set(unified.model_dump(mode="json")) == set(done)
        # 答案里含单工具耗时（观测元数据），两次独立运行数值必然不同：
        # 只断言结构一致与业务结果 96，不做逐字相等。
        assert unified.answer.startswith("【结论】")
        assert done["answer"].startswith("【结论】")
        assert "96" in unified.answer and "96" in done["answer"]


# --------------------------------------------------------------------------- #
# 检索边界与可观测性
# --------------------------------------------------------------------------- #


class TestRetrievalBoundary:
    def test_dense_all_zero_falls_back_to_keyword_and_strategy_is_observable(
        self, edge_ctx, monkeypatch
    ):
        chunks = edge_ctx.index.all_chunks()

        def _zero_scores(_vector, _top_k, _modalities):
            return [(chunk, 0.0) for chunk in chunks[:3]]

        monkeypatch.setattr(edge_ctx.index.store, "search", _zero_scores)
        evidences, debug = edge_ctx.retriever.retrieve("混合检索说明", [], 5)
        assert debug["strategy"] == "keyword_fallback"
        assert evidences
        final = edge_ctx.graph.run(_state("混合检索说明"))
        assert final.last_debug["strategy"] == "keyword_fallback"
        assert final.evidences
        assert "关键词" in final.answer or "回退" in final.answer or final.answer

    def test_empty_index_returns_empty_strategy(self, edge_ctx):
        paths = config.resolve_paths()
        store = InMemoryVectorStore(edge_ctx.settings, paths)
        index = VectorIndex(edge_ctx.encoder, store, edge_ctx.settings, paths)
        from app.rag.retriever import HybridRetriever

        evidences, debug = HybridRetriever(index, edge_ctx.settings).retrieve(
            "混合检索说明", [], 5
        )
        assert evidences == []
        assert debug["strategy"] == "empty"

    def test_modalities_filter_restricts_evidences(self, edge_ctx):
        evidences, _ = edge_ctx.retriever.retrieve("平台", ["image"], 5)
        assert all(item.modality == "image" for item in evidences)

    def test_corrupted_vector_index_is_rebuilt_from_knowledge(self, edge_ctx):
        paths = config.resolve_paths()
        paths.index_path.write_text("{BROKEN JSON", encoding="utf-8")
        store = InMemoryVectorStore(edge_ctx.settings, paths)
        index = VectorIndex(edge_ctx.encoder, store, edge_ctx.settings, paths)
        index.load()
        assert store.count() == 0
        index.ensure_bootstrap(TextProcessor())
        assert store.count() > 0
        written = json.loads(paths.index_path.read_text(encoding="utf-8"))
        assert written["version"] == 1
        assert len(written["chunks"]) == len(written["vectors"]) == store.count()

    def test_soft_limit_only_warns_and_never_changes_results(self, edge_ctx):
        paths = config.resolve_paths()
        store = InMemoryVectorStore(edge_ctx.settings, paths)
        index = VectorIndex(edge_ctx.encoder, store, edge_ctx.settings, paths)
        index.ensure_bootstrap(TextProcessor())
        from app.rag.retriever import HybridRetriever
        from app.schemas import ModalityChunk

        retriever = HybridRetriever(index, edge_ctx.settings)
        original = edge_ctx.settings.vector_store.soft_limit
        try:
            edge_ctx.settings.vector_store.soft_limit = 10
            extra = [
                ModalityChunk(
                    chunk_id=f"qa_soft_{i}",
                    source_id="qa:soft",
                    modality="text",
                    content=f"软上限验证切片 {i} 混合检索",
                    metadata={},
                )
                for i in range(6)
            ]
            index.ingest_chunks(extra)
            assert index.last_soft_limit_warning is True
            warned, debug = retriever.retrieve("混合检索说明", [], 5)
            assert debug["soft_limit_warning"] is True
            edge_ctx.settings.vector_store.soft_limit = 10000
            index._check_soft_limit()
            assert index.last_soft_limit_warning is False
            quiet, quiet_debug = retriever.retrieve("混合检索说明", [], 5)
            assert quiet_debug["soft_limit_warning"] is False
            assert [item.chunk_id for item in warned] == [item.chunk_id for item in quiet]
            assert [item.score for item in warned] == [item.score for item in quiet]
        finally:
            edge_ctx.settings.vector_store.soft_limit = original


# --------------------------------------------------------------------------- #
# 健康：配置声明值 vs 实际生效后端（两条独立数据流）
# --------------------------------------------------------------------------- #


class TestHealthBackendStreams:
    def test_production_reports_effective_backends_and_configured_values(
        self, ctx_factory
    ):
        context = ctx_factory(DEMO_MODE="0", VECTOR_BACKEND="chroma")
        test_client = _client(context)
        try:
            body = test_client.get("/health").json()
            assert body["demo_mode"] is False
            assert "configured_backends" in body
            assert body["configured_backends"]["vector"] == "chroma"
            # chromadb 缺失 → 实际生效降级为 memory，且如实反映到 components
            assert body["components"]["vector"] == "memory"
            assert body["components"]["graph"] == "pure"
            assert "chroma" in context.fallback_flags
            assert body["status"] == "degraded"
            chat = test_client.post(
                "/v1/chat", json={"query": "计算 12*8 的结果", "stream": False}
            )
            assert chat.status_code == 200
            assert "96" in chat.json()["answer"]
        finally:
            test_client.close()
            from app.main import app

            if getattr(app.state, "ctx", None) is context:
                del app.state.ctx

    def test_demo_never_exposes_configured_backends(self, edge_ctx):
        test_client = _client(edge_ctx)
        try:
            body = test_client.get("/health").json()
            assert "configured_backends" not in body
            assert body["components"]["graph"] == "pure"
        finally:
            test_client.close()
            from app.main import app

            if getattr(app.state, "ctx", None) is edge_ctx:
                del app.state.ctx


# --------------------------------------------------------------------------- #
# 轨迹内容（NF-2）
# --------------------------------------------------------------------------- #


class TestTraceContent:
    def test_state_snapshots_are_redacted_and_ordered(self, edge_ctx):
        edge_ctx.graph.run(_state("计算 12*8 的结果"))
        lines = edge_ctx.paths.trace_path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(line) for line in lines if line.strip()]
        assert records
        for record in records:
            snapshot = record.get("state_snapshot", {})
            for key in ("query", "answer"):
                if key in snapshot:
                    assert isinstance(snapshot[key], dict)
                    assert {"length", "preview"} <= set(snapshot[key])
            assert "api_key" not in json.dumps(snapshot, ensure_ascii=False) or (
                "***REDACTED***" in json.dumps(snapshot, ensure_ascii=False)
            )
        steps = [item["steps"] for item in records if item["event"] == "step"]
        assert steps == sorted(steps)
        assert records[-1]["event"] == "done"
