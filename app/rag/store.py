"""向量库：内存暴力余弦 + JSON 持久化 + 损坏恢复 + ``VectorIndex`` 门面。

``store.py`` **不得 import ``app.modalities.*``**：空索引灌库所需的
``TextProcessor`` 由组合根通过 ``ensure_bootstrap(text_processor)`` 运行时注入
（ARCH §1.3 铁律 2）。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from app.observability.logging import get_logger
from app.rag.encoder import BaseEncoder
from app.schemas import ModalityChunk, RawInput

if TYPE_CHECKING:
    from app.config import Paths, Settings


class VectorStore(ABC):
    """向量库统一接口。"""

    @abstractmethod
    def add(self, chunks: list[ModalityChunk], vectors: list[list[float]]) -> int:
        raise NotImplementedError

    @abstractmethod
    def search(
        self, vector: list[float], top_k: int, modalities: list[str]
    ) -> list[tuple[ModalityChunk, float]]:
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def persist(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError


class InMemoryVectorStore(VectorStore):
    """numpy 暴力余弦；``modalities`` 空列表 = 不过滤；得分相同以 ``chunk_id`` 稳定排序。"""

    def __init__(self, settings: "Settings", paths: "Paths") -> None:
        self._settings = settings
        self._index_path: Path = paths.index_path
        self._chunks: dict[str, ModalityChunk] = {}
        self._vectors: dict[str, list[float]] = {}

    def add(self, chunks: list[ModalityChunk], vectors: list[list[float]]) -> int:
        added = 0
        for chunk, vector in zip(chunks, vectors):
            if chunk.chunk_id in self._chunks:
                continue  # 同一内容重复入库时幂等去重
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = [float(value) for value in vector]
            added += 1
        return added

    def search(
        self, vector: list[float], top_k: int, modalities: list[str]
    ) -> list[tuple[ModalityChunk, float]]:
        query = np.asarray(vector, dtype=np.float64)
        query_norm = float(np.linalg.norm(query))
        allowed = set(modalities or [])
        scored: list[tuple[ModalityChunk, float]] = []
        for chunk_id, chunk in self._chunks.items():
            if allowed and chunk.modality not in allowed:
                continue
            doc = np.asarray(self._vectors.get(chunk_id, []), dtype=np.float64)
            if doc.shape[0] != query.shape[0]:
                continue
            denominator = query_norm * float(np.linalg.norm(doc))
            score = float(np.dot(query, doc) / denominator) if denominator > 0 else 0.0
            scored.append((chunk, score))
        # 稳定次级键：chunk_id 字典序
        scored.sort(key=lambda item: (-item[1], item[0].chunk_id))
        return scored[: max(0, int(top_k))]

    def count(self) -> int:
        return len(self._chunks)

    def all_chunks(self) -> list[ModalityChunk]:
        """按 ``chunk_id`` 排序返回全部切片，供 BM25 / 关键词回退使用（确定性）。"""
        return [self._chunks[key] for key in sorted(self._chunks)]

    def persist(self) -> None:
        items = list(self._chunks.items())
        payload = {
            "version": 1,
            "chunks": [chunk.model_dump(mode="json") for _, chunk in items],
            "vectors": [self._vectors[chunk_id] for chunk_id, _ in items],
        }
        self._index_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )

    def load(self) -> None:
        """读取持久化索引；损坏 → 清空重建 + warning，**不抛到 HTTP 层**（P0-11）。"""
        if not self._index_path.exists():
            return
        try:
            payload = json.loads(self._index_path.read_text(encoding="utf-8"))
            chunks = payload["chunks"]
            vectors = payload["vectors"]
            if not isinstance(chunks, list) or not isinstance(vectors, list):
                raise ValueError("索引文件结构非法")
            if len(chunks) != len(vectors):
                raise ValueError("索引 chunks/vectors 数量不一致")
            rebuilt: dict[str, ModalityChunk] = {}
            rebuilt_vectors: dict[str, list[float]] = {}
            for raw_chunk, raw_vector in zip(chunks, vectors):
                chunk = ModalityChunk.model_validate(raw_chunk)
                rebuilt[chunk.chunk_id] = chunk
                rebuilt_vectors[chunk.chunk_id] = [float(v) for v in raw_vector]
            self._chunks = rebuilt
            self._vectors = rebuilt_vectors
        except (json.JSONDecodeError, KeyError, ValueError, TypeError, OSError) as exc:
            self._chunks.clear()
            self._vectors.clear()
            get_logger("rag.store").warning(
                "向量索引损坏，已清空重建：%s",
                type(exc).__name__,
                extra={"event": "index_corrupted", "fallback": True},
            )


class ChromaVectorStore(InMemoryVectorStore):
    """Chroma 适配器：构造时验证 chromadb 可用（局部 import），
    随后复用内存镜像保证单机演示下检索口径与持久化行为完全一致。

    chromadb 缺失时构造抛 ``ImportError``，由 :func:`build_store` 捕获回退。
    """

    def __init__(self, settings: "Settings", paths: "Paths") -> None:
        try:
            import chromadb  # noqa: F401  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError("chromadb 不可用") from exc
        super().__init__(settings, paths)
        self._chroma_dir = paths.data_dir / "chroma"


class VectorIndex:
    """encode + store 的门面：灌库、持久化、软上限告警、空索引 bootstrap。"""

    def __init__(
        self,
        encoder: BaseEncoder,
        store: VectorStore,
        settings: "Settings",
        paths: "Paths",
    ) -> None:
        self.encoder = encoder
        self.store = store
        self.settings = settings
        self.paths = paths
        self.last_soft_limit_warning = False

    def load(self) -> None:
        self.store.load()

    def ingest_chunks(self, chunks: list[ModalityChunk]) -> int:
        if not chunks:
            return 0
        vectors = self.encoder.encode_batch([chunk.content for chunk in chunks])
        added = self.store.add(chunks, vectors)
        self.store.persist()
        self._check_soft_limit()
        return added

    def _check_soft_limit(self) -> None:
        """Q11：接近软上限只写 warning + 标注，**绝不截断候选集／不改检索口径**。"""
        threshold = 0.9 * float(self.settings.vector_store.soft_limit)
        count = self.store.count()
        self.last_soft_limit_warning = count >= threshold
        if self.last_soft_limit_warning:
            get_logger("rag.store").warning(
                "索引切片数 %d 接近软上限 %.0f，仅告警不改检索口径",
                count,
                float(self.settings.vector_store.soft_limit),
                extra={"event": "soft_limit_approaching", "fallback": True},
            )

    def ensure_bootstrap(self, text_processor: Any) -> None:
        """空索引时灌入 ``samples/knowledge.txt``；processor 由组合根注入，不 import modalities。"""
        if self.store.count() > 0:
            return
        try:
            text = self.paths.knowledge_path.read_text(encoding="utf-8")
        except OSError as exc:
            get_logger("rag.store").warning(
                "内置知识文件缺失，跳过 bootstrap：%s",
                type(exc).__name__,
                extra={"event": "bootstrap_missing", "fallback": True},
            )
            return
        raw = RawInput(
            name="knowledge.txt",
            content=text.encode("utf-8"),
            mime="text/plain",
            source_tag="bootstrap",
            text=text,
        )
        chunks = text_processor.process(raw, self.settings)
        if chunks:
            self.ingest_chunks(chunks)

    def count(self) -> int:
        return self.store.count()

    def all_chunks(self) -> list[ModalityChunk]:
        store = self.store
        if hasattr(store, "all_chunks"):
            return list(store.all_chunks())
        return []


def build_store(
    settings: "Settings", paths: "Paths", ctx_partial: Any = None
) -> VectorStore:
    """向量库唯一工厂；chroma 不可用 → 回退内存实现 + fallback 标记。"""
    if settings.demo.enabled or settings.vector_store.backend != "chroma":
        return InMemoryVectorStore(settings, paths)
    try:
        return ChromaVectorStore(settings, paths)
    except Exception as exc:
        flags = getattr(ctx_partial, "fallback_flags", None)
        if isinstance(flags, list) and "chroma" not in flags:
            flags.append("chroma")
        get_logger("rag.store").warning(
            "vector store fallback: chroma -> memory (%s)",
            type(exc).__name__,
            extra={"event": "fallback", "fallback": True},
        )
        return InMemoryVectorStore(settings, paths)


__all__ = [
    "VectorStore",
    "InMemoryVectorStore",
    "ChromaVectorStore",
    "VectorIndex",
    "build_store",
]
