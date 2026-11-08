"""四模态接入层：统一导出 ``PROCESSORS`` 映射。

``api/routes.ingest`` 只依赖本映射 + ``BaseModalityProcessor.process`` 契约，
不感知具体模态实现。
"""

from __future__ import annotations

from app.modalities.audio import AudioProcessor
from app.modalities.base import (
    MODALITY_BY_EXT,
    BaseModalityProcessor,
    RawInput,
    build_chunk,
    build_modality_map,
    detect_modality,
    make_chunk_id,
    make_source_id,
)
from app.modalities.image import ImageProcessor
from app.modalities.text import TextProcessor
from app.modalities.video import VideoProcessor

#: 模态名 → 处理器类（由组合根 / routes 按需实例化）。
PROCESSORS: dict[str, type[BaseModalityProcessor]] = {
    "text": TextProcessor,
    "image": ImageProcessor,
    "audio": AudioProcessor,
    "video": VideoProcessor,
}

__all__ = [
    "PROCESSORS",
    "MODALITY_BY_EXT",
    "BaseModalityProcessor",
    "RawInput",
    "TextProcessor",
    "ImageProcessor",
    "AudioProcessor",
    "VideoProcessor",
    "detect_modality",
    "build_modality_map",
    "make_source_id",
    "make_chunk_id",
    "build_chunk",
]
