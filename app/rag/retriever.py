"""混合检索：稠密余弦 + 简化 BM25 + 加权融合 + 重排 + 纯关键词回退。

``retrieve()`` 返回 ``(list[Evidence], last_debug)``；
``last_debug.strategy ∈ {hybrid, keyword_fallback, empty}``，并携带
``soft_limit_warning``（接近软上限时 True，**不改检索结果口径**，Q11）。
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import TYPE_CHECKING, Any

from app.schemas import Evidence, ModalityChunk

if TYPE_CHECKING:
    from app.config import Settings
    from app.rag.store import VectorIndex

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")
_BM25_K1 = 1.5
_BM25_B = 0.75


def _tokenize(text: str) -> list[str]:
    """中文按字 + 英文数字按词，全部小写。"""
    return _TOKEN_RE.findall((text or "").lower())


class HybridRetriever:
    """稠密 + BM25 加权融合，稠密无结果／全零时切纯关键词回退。"""

    def __init__(self, index: "VectorIndex", settings: "Settings") -> None:
        self.index = index
        self.settings = settings

    def _bm25_scores(
        self, query: str, chunks: list[ModalityChunk], modalities: list[str]
    ) -> dict[str, float]:
        """简化 BM25：词频 + 文档长度归一 + IDF；结果归一化到 [0, 1]。"""
        allowed = set(modalities or [])
        docs: list[tuple[ModalityChunk, list[str]]] = [
            (chunk, _tokenize(chunk.content))
            for chunk in chunks
            if not allowed or chunk.modality in allowed
        ]
        if not docs:
            return {}

        total = len(docs)
        avg_length = (sum(len(tokens) for _, tokens in docs) / total) or 1.0
        document_freq: Counter[str] = Counter()
        for _, tokens in docs:
            for term in set(tokens):
                document_freq[term] += 1

        query_terms = set(_tokenize(query))
        idf: dict[str, float] = {
            term: math.log(1.0 + (total - document_freq.get(term, 0) + 0.5) / (document_freq.get(term, 0) + 0.5))
            for term in query_terms
        }

        scores: dict[str, float] = {}
        for chunk, tokens in docs:
            term_freq: Counter[str] = Counter(tokens)
            length = len(tokens) or 1
            score = 0.0
            for term in query_terms:
                freq = term_freq.get(term, 0)
                if freq == 0:
                    continue
                denominator = freq + _BM25_K1 * (
                    1.0 - _BM25_B + _BM25_B * length / avg_length
                )
                score += idf.get(term, 0.0) * (freq * (_BM25_K1 + 1.0)) / denominator
            scores[chunk.chunk_id] = max(0.0, score)

        maximum = max(scores.values(), default=0.0)
        if maximum > 0.0:
            scores = {key: value / maximum for key, value in scores.items()}
        return scores

    def _rerank(
        self,
        query: str,
        scores: dict[str, float],
        by_id: dict[str, ModalityChunk],
        top_k: int,
    ) -> list[tuple[ModalityChunk, float]]:
        """子串命中 ``+substring_boost`` + 同一 ``source_id`` 去重限流 + 稳定次级键。"""
        lowered_query = (query or "").lower()
        terms = [term for term in _tokenize(lowered_query) if len(term) >= 2][:8]
        boost = float(self.settings.retrieval.substring_boost)

        ranked: list[tuple[ModalityChunk, float]] = []
        for chunk_id, score in scores.items():
            chunk = by_id.get(chunk_id)
            if chunk is None:
                continue
            content_lower = chunk.content.lower()
            if (lowered_query and lowered_query in content_lower) or any(
                term in content_lower for term in terms
            ):
                score += boost
            ranked.append((chunk, float(score)))
        ranked.sort(key=lambda item: (-item[1], item[0].chunk_id))

        # 同源去重：同一 source_id 最多保留 cap 条，避免单一来源垄断证据列表。
        cap = max(1, (int(top_k) + 1) // 2)
        seen: dict[str, int] = {}
        result: list[tuple[ModalityChunk, float]] = []
        for chunk, score in ranked:
            source_id = chunk.source_id
            if seen.get(source_id, 0) >= cap:
                continue
            seen[source_id] = seen.get(source_id, 0) + 1
            result.append((chunk, round(score, 6)))
        return result

    def retrieve(
        self, query: str, modalities: list[str], top_k: int = 5
    ) -> tuple[list[Evidence], dict[str, Any]]:
        """返回 ``(evidences, last_debug)``。``modalities=[]`` ⇒ 不过滤（Q4）。"""
        mods = list(modalities or [])
        debug: dict[str, Any] = {
            "strategy": "empty",
            "soft_limit_warning": bool(self.index.last_soft_limit_warning),
            "dense_candidates": 0,
            "bm25_candidates": 0,
            "query_terms": len(_tokenize(query)),
            "dense_weight": float(self.settings.retrieval.dense_weight),
            "bm25_weight": float(self.settings.retrieval.bm25_weight),
        }

        chunks = self.index.all_chunks()
        if not chunks:
            return [], debug
        by_id = {chunk.chunk_id: chunk for chunk in chunks}

        query_vector = self.index.encoder.encode(query or "")
        dense = self.index.store.search(query_vector, max(int(top_k) * 4, 12), mods)
        debug["dense_candidates"] = len(dense)
        bm25 = self._bm25_scores(query or "", chunks, mods)
        debug["bm25_candidates"] = len(bm25)

        floor = float(self.settings.retrieval.dense_floor)
        dense_useless = (not dense) or all(score <= floor for _, score in dense)
        w_dense = float(self.settings.retrieval.dense_weight)
        w_bm25 = float(self.settings.retrieval.bm25_weight)

        if dense_useless:
            # 稠密无结果或全部得分 ≤ dense_floor → 纯关键词文本回退
            strategy = "keyword_fallback"
            scores: dict[str, float] = dict(bm25)
        else:
            strategy = "hybrid"
            dense_scores = {chunk.chunk_id: max(0.0, score) for chunk, score in dense}
            max_dense = max(dense_scores.values(), default=0.0) or 1.0
            max_bm25 = max(bm25.values(), default=0.0) or 1.0
            all_ids = set(dense_scores) | set(bm25)
            scores = {
                chunk_id: w_dense * (dense_scores.get(chunk_id, 0.0) / max_dense)
                + w_bm25 * (bm25.get(chunk_id, 0.0) / max_bm25)
                for chunk_id in all_ids
            }

        ranked = self._rerank(query or "", scores, by_id, int(top_k))
        snippet_chars = int(self.settings.retrieval.snippet_chars)
        evidences = [
            Evidence(
                chunk_id=chunk.chunk_id,
                modality=chunk.modality,
                snippet=chunk.content[:snippet_chars],
                score=score,
                source_id=chunk.source_id,
            )
            for chunk, score in ranked[: max(0, int(top_k))]
        ]
        debug["strategy"] = strategy if evidences else "empty"
        debug["dense_max_score"] = max((score for _, score in dense), default=0.0)
        return evidences, debug


__all__ = ["HybridRetriever"]
