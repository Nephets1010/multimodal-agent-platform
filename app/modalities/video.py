"""视频模态：cv2 等间隔抽 ≤3 帧，**复用同一份 ImageProcessor 图像处理链路**。

不可解码（cap 未打开 / 0 帧 / cv2 缺失 / 无临时文件路径）时：
``seed = int.from_bytes(hashlib.sha256(raw_content).digest()[:8], "big")`` →
``numpy.random.default_rng(seed)`` 生成 3 张确定性合成帧 → **仍走 ImageProcessor**。

本模块自身不写日志、不写文件、不发请求；降级只体现在返回 chunk 的
``metadata.fallback`` 标记，由 ``api/routes.ingest`` 统一补 warning 日志。
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image

from app.modalities.base import BaseModalityProcessor, make_chunk_id, make_source_id
from app.modalities.image import ImageProcessor
from app.schemas import ModalityChunk, ModalityError, RawInput

if TYPE_CHECKING:
    from app.config import Settings

_MAX_FRAMES = 3
_SYNTH_HEIGHT = 48
_SYNTH_WIDTH = 64


def _frame_to_png(frame_rgb: np.ndarray) -> bytes:
    """把 RGB ndarray 编码为 PNG 字节，交给 ImageProcessor 走标准图像链路。"""
    arr = np.asarray(frame_rgb, dtype=np.uint8)
    image = Image.fromarray(arr, mode="RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class VideoProcessor(BaseModalityProcessor):
    """视频 → 每帧 1 个 ``ModalityChunk``（``modality="video"``，带 timestamp）。"""

    modality = "video"

    def __init__(self) -> None:
        # 唯一的图像处理逻辑来源：VideoProcessor 不另写颜色网格/指纹算法。
        self._image = ImageProcessor()

    def _load_cv2(self) -> Any:
        """局部探测并导入 cv2；缺失返回 ``None``（绝不顶层硬 import）。"""
        try:
            if importlib.util.find_spec("cv2") is None:
                return None
        except (ImportError, ValueError, ModuleNotFoundError):
            return None
        try:
            import cv2  # type: ignore[import-not-found]

            return cv2
        except ImportError:
            return None

    def _extract_frames(
        self, raw: RawInput, settings: "Settings"
    ) -> tuple[list[tuple[float, np.ndarray]], bool]:
        """返回 ``[(timestamp, RGB ndarray)]`` 与 ``fallback`` 标记。"""
        cv2 = self._load_cv2()
        candidate = raw.text
        path = Path(candidate) if candidate else None

        if cv2 is not None and path is not None and path.is_file():
            cap = None
            try:
                cap = cv2.VideoCapture(str(path))
                total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 1.0
                frames: list[tuple[float, np.ndarray]] = []
                if cap.isOpened() and total > 0:
                    count = min(_MAX_FRAMES, total)
                    for index in range(count):
                        position = int(total * index / max(1, count))
                        cap.set(cv2.CAP_PROP_POS_FRAMES, position)
                        ok, bgr = cap.read()
                        if not ok or bgr is None:
                            continue
                        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                        frames.append((position / fps, np.asarray(rgb, dtype=np.uint8)))
                if frames:
                    return frames, False
            except Exception:
                # 解码失败一律走确定性合成帧，不向上抛、不写日志。
                pass
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass

        seed = int.from_bytes(
            hashlib.sha256(raw.content or b"").digest()[:8], "big"
        )
        rng = np.random.default_rng(seed)
        synthetic: list[tuple[float, np.ndarray]] = []
        for index in range(_MAX_FRAMES):
            frame = rng.integers(
                0, 256, size=(_SYNTH_HEIGHT, _SYNTH_WIDTH, 3), dtype=np.uint8
            )
            synthetic.append((round(index / float(_MAX_FRAMES), 6), frame))
        return synthetic, True

    def process(self, raw: RawInput, settings: "Settings") -> list[ModalityChunk]:
        frames, fallback = self._extract_frames(raw, settings)
        source_id = make_source_id(raw)
        base_name = Path(raw.name).name or "video.bin"
        chunks: list[ModalityChunk] = []

        for index, (timestamp, frame_rgb) in enumerate(frames):
            try:
                png_bytes = _frame_to_png(frame_rgb)
            except Exception as exc:
                raise ModalityError(f"视频帧编码失败 {raw.name}：{type(exc).__name__}") from exc

            frame_raw = RawInput(
                name=f"{base_name}.frame{index}.png",
                content=png_bytes,
                mime="image/png",
                source_tag=raw.source_tag,
                text=None,
            )
            # 复用 ImageProcessor：颜色网格 / 感知指纹只在这一处实现。
            sub_chunks = self._image.process(frame_raw, settings)
            if not sub_chunks:
                continue
            primary = sub_chunks[0]
            content = (
                f"视频帧描述（第 {index + 1}/{len(frames)} 帧，t={timestamp:.2f}s）："
                f"{primary.content}"
            )
            metadata: dict[str, Any] = {
                "source_tag": raw.source_tag,
                "source_name": base_name,
                "chunk_index": index,
                "timestamp": timestamp,
                "frame_index": index,
                "fallback": fallback,
                "width": primary.metadata.get("width"),
                "height": primary.metadata.get("height"),
                "fingerprint": primary.metadata.get("fingerprint"),
            }
            chunks.append(
                ModalityChunk(
                    chunk_id=make_chunk_id(source_id, "video", index, content),
                    source_id=source_id,
                    modality="video",
                    content=content,
                    metadata=metadata,
                )
            )
        return chunks


__all__ = ["VideoProcessor"]
