"""多模态接入层公共基类与工具函数。

只依赖 ``app.schemas`` / ``app.config``；**不得 import ``app.rag.*`` / ``app.agent.*`` /
``app.runtime``**（ARCH §1.3 铁律 2）。所有 ``chunk_id`` 由 ``hashlib`` 生成，
DEMO 分支禁用 Python 内置 ``hash()``。
"""

from __future__ import annotations

import hashlib
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, TYPE_CHECKING

from app.schemas import IngestError, ModalityChunk, RawInput

if TYPE_CHECKING:  # 仅类型标注，运行时不产生额外依赖
    from app.config import Settings

#: Q3 扩展名白名单（逐字一致，大小写不敏感）。
#: **只读参考常量，运行时禁止读取**：白名单真实来源是 ``settings.ingest.allowed_extensions``
#: （经 :func:`build_modality_map` 构建该映射）。保留本常量仅供测试做零漂移断言。
MODALITY_BY_EXT: dict[str, str] = {
    ".txt": "text",
    ".md": "text",
    ".json": "text",
    ".csv": "text",
    ".text": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".bmp": "image",
    ".wav": "audio",
    ".mp4": "video",
    ".avi": "video",
    ".mov": "video",
    ".mkv": "video",
    ".webm": "video",
}

#: MIME 兜底（仅当扩展名未知且 MIME 明确属于白名单模态时使用）。
_MIME_TO_MODALITY: dict[str, str] = {
    "text/plain": "text",
    "text/markdown": "text",
    "text/csv": "text",
    "application/json": "text",
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
    "image/bmp": "image",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "audio/wave": "audio",
    "video/mp4": "video",
    "video/x-msvideo": "video",
    "video/quicktime": "video",
    "video/x-matroska": "video",
    "video/webm": "video",
}

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]")


def make_source_id(raw: RawInput) -> str:
    """同一来源的多个切片共享 ``source_id``，供检索重排「同源去重」使用。"""
    safe_name = _SAFE_NAME_RE.sub("_", Path(raw.name).name) or "inline"
    return f"{raw.source_tag}:{safe_name}"


def make_chunk_id(source_id: str, modality: str, index: int, content: str) -> str:
    """确定性内容哈希 ID（``hashlib.sha256``，禁用内置 ``hash()``）。"""
    digest = hashlib.sha256(
        f"{source_id}|{modality}|{index}|{content}".encode("utf-8")
    ).hexdigest()[:16]
    return f"chk_{digest}"


def build_chunk(
    raw: RawInput,
    modality: str,
    index: int,
    content: str,
    extra_metadata: dict[str, Any] | None = None,
) -> ModalityChunk:
    """构造**恰好 5 字段**的 ``ModalityChunk``。

    ``metadata`` 至少含 ``source_tag``、净化后的原始文件名、``chunk_index``。
    """
    source_id = make_source_id(raw)
    safe_name = _SAFE_NAME_RE.sub("_", Path(raw.name).name) or "inline"
    metadata: dict[str, Any] = {
        "source_tag": raw.source_tag,
        "source_name": safe_name,
        "chunk_index": index,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return ModalityChunk(
        chunk_id=make_chunk_id(source_id, modality, index, content),
        source_id=source_id,
        modality=modality,
        content=content,
        metadata=metadata,
    )


def build_modality_map(settings: "Settings") -> dict[str, str]:
    """把 ``settings.ingest.allowed_extensions`` 扁平化为 ``{扩展名: 模态}`` 运行期映射。

    扩展名统一小写；这是白名单的**唯一运行时来源**，``detect_modality`` 与
    ``api.guards.validate_uploads`` 都读它，保证判定与提示同源。
    """
    return {
        ext.lower(): modality
        for modality, exts in settings.ingest.allowed_extensions.items()
        for ext in exts
    }


def detect_modality(name: str, mime: str, settings: "Settings") -> str:
    """扩展名优先、MIME 兜底；未知扩展名抛 ``IngestError``（400 + 可读 detail）。"""
    ext = Path(name).suffix.lower()
    ext_map = build_modality_map(settings)
    if ext in ext_map:
        return ext_map[ext]

    normalized_mime = (mime or "").split(";")[0].strip().lower()
    if normalized_mime in _MIME_TO_MODALITY:
        return _MIME_TO_MODALITY[normalized_mime]

    # 错误提示与实际判定同源：统一用 build_modality_map(settings)，
    # 避免配置漂移时提示撒谎。
    allowed = ", ".join(sorted(ext_map))
    raise IngestError(
        f"不支持的扩展名 {ext or '(无扩展名)'}，仅允许 {allowed}",
        code="unsupported_extension",
    )


class BaseModalityProcessor(ABC):
    """四模态处理器统一接口：``process(raw, settings) -> list[ModalityChunk]``。

    实现必须是同步纯函数：不写日志、不写文件、不发网络请求；
    单文件解析失败抛 ``ModalityError``，由 ``api/routes.ingest`` 统一降级。
    """

    modality: str = ""

    @abstractmethod
    def process(self, raw: RawInput, settings: "Settings") -> list[ModalityChunk]:
        """把原始输入转成描述性文本切片。"""
        raise NotImplementedError


__all__ = [
    "MODALITY_BY_EXT",
    "RawInput",
    "BaseModalityProcessor",
    "build_modality_map",
    "detect_modality",
    "make_source_id",
    "make_chunk_id",
    "build_chunk",
]
