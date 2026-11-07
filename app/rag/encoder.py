"""表征层：Stub / API / Transformers 三种编码器与唯一工厂入口。

DEMO 或 ``backend=stub`` → :class:`StubEncoder`（``hashlib`` 词频 + 字符分布
分桶 + L2 归一化，固定 256 维，零向量返回全零不产生 NaN）。
生产 ``api`` → ``httpx`` 直连 OpenAI 兼容 ``/embeddings``（**DEMO 下 0 请求**）。
生产 ``transformers`` → 从 ``encoder.local_model_path`` 以 ``local_files_only=True`` 加载。
任一失败 → 回退 ``StubEncoder`` 并记 ``fallback``。
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import numpy as np

from app.observability.logging import get_logger

if TYPE_CHECKING:
    from app.config import Settings

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


class BaseEncoder(ABC):
    """编码器统一接口。"""

    dim: int = 256

    @abstractmethod
    def encode(self, text: str) -> list[float]:
        """把一段文本编码为 ``dim`` 维向量。"""
        raise NotImplementedError

    def encode_batch(self, texts: list[str]) -> list[list[float]]:
        """默认逐条编码；子类可覆写以批量优化。"""
        return [self.encode(text) for text in texts]


class StubEncoder(BaseEncoder):
    """确定性哈希词频编码器，**禁用 Python 内置 ``hash()``**。"""

    def __init__(self, dim: int = 256) -> None:
        self.dim = int(dim) if int(dim) > 0 else 256

    def encode(self, text: str) -> list[float]:
        vec = np.zeros(self.dim, dtype=np.float64)
        source = text or ""

        for token in _TOKEN_RE.findall(source.lower()):
            digest = int(hashlib.sha256(token.encode("utf-8")).hexdigest()[:8], 16)
            vec[digest % self.dim] += 1.0
            vec[(digest >> 8) % self.dim] += 0.25

        # 字符分布分桶：与词频桶用不同前缀，保证不同文本有稳定区分度。
        for char in source:
            digest = int(
                hashlib.sha256(("char:" + char).encode("utf-8")).hexdigest()[:8], 16
            )
            vec[digest % self.dim] += 0.3

        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec = vec / norm
        return [float(value) for value in vec]


class APIEncoder(BaseEncoder):
    """生产模式：``httpx`` POST ``{base_url}/embeddings``（不依赖 openai SDK）。"""

    def __init__(self, settings: "Settings") -> None:
        self.dim = int(settings.encoder.dim)
        self._settings = settings
        if not settings.llm.api_key or not settings.llm.base_url:
            raise RuntimeError("APIEncoder 需要 LLM_API_KEY 与 LLM_BASE_URL")

    def encode(self, text: str) -> list[float]:
        if self._settings.demo.enabled:
            raise RuntimeError("DEMO_MODE=1 禁止发起外部请求")
        import httpx  # 核心依赖；仅在真正需要时导入

        url = self._settings.llm.base_url.rstrip("/") + "/embeddings"
        response = httpx.post(
            url,
            headers={"Authorization": f"Bearer {self._settings.llm.api_key}"},
            json={"model": self._settings.llm.model or "text-embedding-3-small", "input": text},
            timeout=float(self._settings.encoder.timeout_seconds),
        )
        response.raise_for_status()
        data = response.json()["data"][0]["embedding"]
        vector = [float(value) for value in data]
        self.dim = len(vector)
        return vector


class TransformersEncoder(BaseEncoder):
    """生产模式：本地权重目录 ``local_files_only=True``，绝不联网下载。"""

    def __init__(self, settings: "Settings") -> None:
        path = settings.encoder.local_model_path
        if not path:
            raise RuntimeError("encoder.local_model_path 未配置")
        try:
            from transformers import AutoModel, AutoTokenizer  # type: ignore[import-not-found]
        except ImportError as exc:
            raise ImportError("transformers 不可用") from exc

        self._tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        self._model = AutoModel.from_pretrained(path, local_files_only=True)
        self.dim = int(settings.encoder.dim)

    def encode(self, text: str) -> list[float]:
        import numpy as _np  # 局部使用，保持与 StubEncoder 相同的返回类型

        encoded = self._tokenizer(
            text or "", return_tensors="pt", truncation=True, max_length=512
        )
        output = self._model(**encoded)
        hidden = output.last_hidden_state.mean(dim=1).detach().numpy()[0]
        vector = _np.asarray(hidden, dtype=float)
        norm = float(_np.linalg.norm(vector))
        if norm > 0.0:
            vector = vector / norm
        return [float(value) for value in vector]


def _record_fallback(ctx_partial: Any, name: str, reason: str) -> None:
    flags = getattr(ctx_partial, "fallback_flags", None)
    if isinstance(flags, list) and name not in flags:
        flags.append(name)
    get_logger("rag.encoder").warning(
        "encoder fallback: %s -> stub (%s)",
        name,
        reason,
        extra={"event": "fallback", "fallback": True},
    )


def build_encoder(settings: "Settings", ctx_partial: Any = None) -> BaseEncoder:
    """编码器唯一工厂；任何失败均回退 :class:`StubEncoder` 且绝不崩溃。"""
    dim = int(settings.encoder.dim)
    if settings.demo.enabled or settings.encoder.backend == "stub":
        return StubEncoder(dim)

    if settings.encoder.backend == "api":
        try:
            return APIEncoder(settings)
        except Exception as exc:
            _record_fallback(ctx_partial, "api_encoder", type(exc).__name__)
            return StubEncoder(dim)

    if settings.encoder.backend == "transformers":
        try:
            if importlib.util.find_spec("transformers") is None:
                raise ImportError("transformers 未安装")
            return TransformersEncoder(settings)
        except Exception as exc:
            _record_fallback(ctx_partial, "transformers_encoder", type(exc).__name__)
            return StubEncoder(dim)

    _record_fallback(ctx_partial, "encoder", f"未知后端 {settings.encoder.backend}")
    return StubEncoder(dim)


__all__ = [
    "BaseEncoder",
    "StubEncoder",
    "APIEncoder",
    "TransformersEncoder",
    "build_encoder",
]
