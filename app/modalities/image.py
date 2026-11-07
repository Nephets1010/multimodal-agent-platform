"""图像模态：Pillow 归一 + numpy 4×4 颜色网格 / 感知指纹 → 描述性文本。

不加载任何模型权重；图像字节**绝不**写入 ``content``，只产出可检索的描述性文本。
视频抽帧链路复用本模块唯一的图像处理逻辑（见 ``video.py``）。
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from app.modalities.base import BaseModalityProcessor, build_chunk
from app.schemas import ModalityError, RawInput

if TYPE_CHECKING:
    from app.config import Settings
    from app.schemas import ModalityChunk

_GRID = 4
_RESIZE = 32


def _color_grid(arr: np.ndarray) -> list[list[int]]:
    """把 32×32 RGB 均分成 4×4 网格，返回每块平均 RGB（取整）。"""
    block = _RESIZE // _GRID
    grid: list[list[int]] = []
    for row in range(_GRID):
        for col in range(_GRID):
            patch = arr[
                row * block : (row + 1) * block,
                col * block : (col + 1) * block,
                :,
            ]
            mean = patch.mean(axis=(0, 1))
            grid.append([int(round(float(v))) for v in mean])
    return grid


def _perceptual_fingerprint(arr: np.ndarray) -> str:
    """灰度相邻像素比较位串（结果完全由像素决定，确定性）。"""
    gray = arr.mean(axis=2)
    bits: list[str] = []
    for row in range(min(8, gray.shape[0])):
        for col in range(1, min(9, gray.shape[1])):
            bits.append("1" if gray[row, col] > gray[row, col - 1] else "0")
    value = int("".join(bits), 2) if bits else 0
    return f"fp_{value:016x}"


class ImageProcessor(BaseModalityProcessor):
    """图像 → 1 个描述性 ``ModalityChunk``；非法字节抛 ``ModalityError``。"""

    modality = "image"

    def process(self, raw: RawInput, settings: "Settings") -> "list[ModalityChunk]":
        try:
            with Image.open(io.BytesIO(raw.content or b"")) as opened:
                fmt = opened.format or "UNKNOWN"
                width, height = opened.size
                rgb = opened.convert("RGB").resize((_RESIZE, _RESIZE))
                arr = np.asarray(rgb, dtype=np.float64)
        except Exception as exc:  # PIL.UnidentifiedImageError / OSError / ValueError
            raise ModalityError(f"无法解析图像文件 {raw.name}：{type(exc).__name__}") from exc

        grid = _color_grid(arr)
        fingerprint = _perceptual_fingerprint(arr)
        grid_text = " ".join(f"({r},{g},{b})" for r, g, b in grid)
        content = (
            f"图像 描述性证据：格式 {fmt}，原始尺寸 {width}x{height}，"
            f"归一化为 {_RESIZE}x{_RESIZE}。颜色网格 {_GRID}x{_GRID} 平均 RGB：{grid_text}。"
            f"感知指纹 {fingerprint}。"
            "该图像被统一抽象为描述性文本证据，含图像、颜色、指纹等可检索关键词。"
        )

        metadata: dict[str, Any] = {
            "width": width,
            "height": height,
            "format": fmt,
            "fingerprint": fingerprint,
            "color_grid": grid,
        }
        return [build_chunk(raw, self.modality, 0, content, metadata)]


__all__ = ["ImageProcessor"]
