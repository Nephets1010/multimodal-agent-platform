"""文本模态：清洗 + 段落边界优先的定长重叠切片。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.modalities.base import BaseModalityProcessor, build_chunk
from app.schemas import RawInput

if TYPE_CHECKING:
    from app.config import Settings
    from app.schemas import ModalityChunk

_THREE_BLANK_LINES = re.compile(r"\n{3,}")


def _clean(text: str) -> str:
    """去 BOM、统一换行、合并 3+ 空行为 2 个、去首尾空白。"""
    cleaned = text.lstrip("\ufeff")
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _THREE_BLANK_LINES.sub("\n\n", cleaned)
    return cleaned.strip()


def _split_segments(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """段落优先 + 超长段落定长重叠切片 + 相邻短段合并。

    步进 ``chunk_size - chunk_overlap``（T01 校验保证 > 0）。
    """
    step = max(1, chunk_size - chunk_overlap)
    pieces: list[str] = []
    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= chunk_size:
            pieces.append(paragraph)
            continue
        start = 0
        while start < len(paragraph):
            segment = paragraph[start : start + chunk_size]
            if segment.strip():
                pieces.append(segment)
            if start + chunk_size >= len(paragraph):
                break
            start += step

    merged: list[str] = []
    buffer = ""
    for piece in pieces:
        if not buffer:
            buffer = piece
        elif len(buffer) + 2 + len(piece) <= chunk_size:
            buffer = buffer + "\n\n" + piece
        else:
            merged.append(buffer)
            buffer = piece
    if buffer:
        merged.append(buffer)
    return merged


class TextProcessor(BaseModalityProcessor):
    """把纯文本切成若干 ``ModalityChunk``；空文本返回 ``[]`` 而非报错。"""

    modality = "text"

    def process(self, raw: RawInput, settings: "Settings") -> "list[ModalityChunk]":
        if raw.text is not None and raw.text.strip():
            source_text = raw.text
        else:
            source_text = (raw.content or b"").decode("utf-8", errors="replace")

        cleaned = _clean(source_text)
        if not cleaned:
            return []

        chunk_size = int(settings.ingest.chunk_size)
        chunk_overlap = int(settings.ingest.chunk_overlap)
        segments = _split_segments(cleaned, chunk_size, chunk_overlap)

        return [
            build_chunk(
                raw,
                self.modality,
                index,
                segment,
                {"char_count": len(segment), "total_segments": len(segments)},
            )
            for index, segment in enumerate(segments)
        ]


__all__ = ["TextProcessor"]
