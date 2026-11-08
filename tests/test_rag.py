"""T03 表征检索回归：Stub 确定性、混合检索命中、全零回退、JSON 持久化与损坏恢复、软上限。"""

from __future__ import annotations

import json
import logging
import math

import pytest

from app.rag.encoder import StubEncoder
from app.rag.retriever import HybridRetriever
from app.rag.store import InMemoryVectorStore, VectorIndex
from app.schemas import ModalityChunk, RawInput


def test_stub_encoder_is_bitwise_deterministic():
    first = StubEncoder(256)
    second = StubEncoder(256)
    text = "混合检索结合稠密余弦与简化 BM25 加权融合"
    assert first.encode(text) == second.encode(text)
    assert len(first.encode(text)) == 256


def test_stub_encoder_zero_vector_has_no_nan():
    vector = StubEncoder(256).encode("")
    assert len(vector) == 256
    assert all(value == 0.0 for value in vector)
    assert not any(math.isnan(value) for value in vector)


def test_hybrid_retrieval_hits_builtin_knowledge(ctx):
    """P0-2：正常问题必须走稠密+BM25 的 hybrid，而非退化成纯关键词回退。

    QA-T05：原断言 ``in ("hybrid", "keyword_fallback")`` 被 NEG-5 证明是假绿
    （把 ``strategy = "hybrid"`` 改成 ``"keyword_fallback"`` 后 139 条仍全绿）。
    本机实测 DEMO 下 ``strategy="hybrid"``、``dense_candidates=4``。
    回退语义由 ``test_keyword_fallback_when_dense_has_no_result`` 等既有用例守护。
    """
    evidences, debug = ctx.retriever.retrieve("请说明混合检索策略", [], 5)
    assert debug["strategy"] == "hybrid"
    assert debug["dense_candidates"] > 0
    assert evidences
    assert all(len(item.model_dump()) >= 4 for item in evidences)
    assert all(item.snippet for item in evidences)


def test_keyword_fallback_when_dense_has_no_result(ctx, monkeypatch):
    """构造稠密无结果场景 → last_debug.strategy == 'keyword_fallback'。"""
    monkeypatch.setattr(ctx.store, "search", lambda *args, **kwargs: [])
    evidences, debug = ctx.retriever.retrieve("混合检索", [], 5)
    assert debug["strategy"] == "keyword_fallback"
    assert evidences  # 纯关键词回退仍产出证据


def test_keyword_fallback_when_all_dense_scores_are_zero(ctx, monkeypatch):
    chunks = ctx.index.all_chunks()

    def _zero_scores(vector, top_k, modalities):
        return [(chunk, 0.0) for chunk in chunks[:3]]

    monkeypatch.setattr(ctx.store, "search", _zero_scores)
    _, debug = ctx.retriever.retrieve("混合检索", [], 5)
    assert debug["strategy"] == "keyword_fallback"


def test_empty_index_returns_empty_strategy(ctx):
    store = InMemoryVectorStore(ctx.settings, ctx.paths)
    index = VectorIndex(ctx.encoder, store, ctx.settings, ctx.paths)
    retriever = HybridRetriever(index, ctx.settings)
    evidences, debug = retriever.retrieve("任意问题", [], 5)
    assert evidences == []
    assert debug["strategy"] == "empty"


def test_modalities_filter_applies(ctx):
    evidences, _ = ctx.retriever.retrieve("平台", ["text"], 5)
    assert all(item.modality == "text" for item in evidences)


def test_persist_and_corrupted_recovery(ctx):
    """损坏 vector_index.json 后 load() 不崩溃，清空重建（不抛到 HTTP 层）。"""
    from app.modalities import PROCESSORS

    raw = RawInput(
        name="persist.txt",
        content=b"persist me",
        mime="text/plain",
        source_tag="pytest",
        text="持久化与损坏恢复验证文本",
    )
    chunks = PROCESSORS["text"]().process(raw, ctx.settings)
    ctx.index.ingest_chunks(chunks)
    assert ctx.paths.index_path.exists()

    ctx.paths.index_path.write_text('{"chunks": [', encoding="utf-8")
    recovered = InMemoryVectorStore(ctx.settings, ctx.paths)
    recovered.load()  # 必须不抛
    assert recovered.count() == 0


def test_soft_limit_warning_does_not_change_results(ctx, monkeypatch):
    """Q11：接近软上限只告警 + 标注，检索结果集合不变。"""
    before, _ = ctx.retriever.retrieve("混合检索", [], 5)
    monkeypatch.setattr(ctx.settings.vector_store, "soft_limit", 1)
    ctx.index._check_soft_limit()
    after, debug = ctx.retriever.retrieve("混合检索", [], 5)
    assert [item.chunk_id for item in before] == [item.chunk_id for item in after]
    assert debug["soft_limit_warning"] is True


def test_ensure_bootstrap_is_idempotent(ctx):
    from app.modalities.text import TextProcessor

    count_before = ctx.index.count()
    ctx.index.ensure_bootstrap(TextProcessor())
    assert ctx.index.count() == count_before


# --------------------------------------------------------------------------- #
# QA-T11：索引持久化损坏恢复（4 类 payload）+ 原子写后目标文件内容
# --------------------------------------------------------------------------- #


_VALID_CHUNK = {
    "chunk_id": "chk_ok",
    "source_id": "qa:persist",
    "modality": "text",
    "content": "x",
    "metadata": {},
}

_CORRUPT_PAYLOADS = [
    ('{"chunks": [', "JSON 截断"),
    (
        json.dumps({"chunks": [_VALID_CHUNK], "vectors": []}),
        "chunks/vectors 数量不一致",
    ),
    (
        json.dumps({"chunks": ["not-an-object"], "vectors": [[0.0]]}),
        "非法 chunk 模型",
    ),
    (
        json.dumps({"chunks": [_VALID_CHUNK], "vectors": [["not-a-float"]]}),
        "float 转换失败",
    ),
    (
        json.dumps({"chunks": "not-a-list", "vectors": []}),
        "结构不是数组",
    ),
]


@pytest.mark.parametrize(("payload", "_reason"), _CORRUPT_PAYLOADS)
def test_corrupted_index_payload_clears_store_without_raising(
    ctx, caplog, payload, _reason
):
    ctx.paths.index_path.write_text(payload, encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="multimodal_agent_platform"):
        store = InMemoryVectorStore(ctx.settings, ctx.paths)
        store.load()  # 必须不抛
    assert store.count() == 0, _reason
    assert any(
        getattr(record, "event", None) == "index_corrupted"
        for record in caplog.records
    ), _reason


def test_persist_writes_compact_equal_length_payload(ctx):
    """只针对最终目标文件断言（A-02 原子写会先写 tmp 再 replace）。"""
    store = InMemoryVectorStore(ctx.settings, ctx.paths)
    chunk = ModalityChunk.model_validate(_VALID_CHUNK)
    store.add([chunk], [[1.0, 2.0]])
    store.persist()

    text = ctx.paths.index_path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["version"] == 1
    assert len(data["chunks"]) == len(data["vectors"]) == 1
    assert data["chunks"][0]["chunk_id"] == "chk_ok"
    assert "\n" not in text
    assert '": ' not in text and '", "' not in text  # separators=(",", ":") 紧凑写法
