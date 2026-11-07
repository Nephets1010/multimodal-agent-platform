"""音频模态：标准库 ``wave`` 解析 PCM WAV 元信息 + ``hashlib`` 确定性占位 ASR。

DEMO 下零模型、零联网；whisper 只在生产模式用 ``find_spec`` + 局部
``try/except ImportError`` 探测降级，绝不顶层硬 import。
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import wave
from typing import TYPE_CHECKING, Any

from app.modalities.base import BaseModalityProcessor, build_chunk
from app.schemas import ModalityError, RawInput

if TYPE_CHECKING:
    from app.config import Settings
    from app.schemas import ModalityChunk

#: 固定中文词表：占位 ASR 由内容哈希字节索引取词，保证确定性。
_ASR_WORDS: tuple[str, ...] = (
    "多模态",
    "平台",
    "混合检索",
    "音频",
    "证据",
    "统一表征",
    "向量",
    "智能体",
    "演示",
    "知识",
    "描述性文本",
    "颜色",
    "指纹",
    "轨迹",
    "工具",
    "编码器",
)


def _placeholder_asr(content: bytes) -> str:
    """按 ``sha256(content).digest()`` 字节索引取词，拼成确定性描述。"""
    digest = hashlib.sha256(content or b"").digest()
    picked = [_ASR_WORDS[digest[i] % len(_ASR_WORDS)] for i in range(6)]
    return "、".join(picked)


class AudioProcessor(BaseModalityProcessor):
    """WAV → 1 个描述性 ``ModalityChunk``；非 WAV / 损坏抛 ``ModalityError``。"""

    modality = "audio"

    def process(self, raw: RawInput, settings: "Settings") -> "list[ModalityChunk]":
        try:
            with wave.open(io.BytesIO(raw.content or b""), "rb") as wav:
                channels = int(wav.getnchannels())
                sample_width = int(wav.getsampwidth())
                frame_rate = int(wav.getframerate())
                n_frames = int(wav.getnframes())
        except (wave.Error, EOFError, OSError, ValueError) as exc:
            raise ModalityError(f"无法解析 WAV 音频文件 {raw.name}：{type(exc).__name__}") from exc

        duration = (n_frames / frame_rate) if frame_rate > 0 else 0.0
        asr_text = _placeholder_asr(raw.content or b"")

        asr_engine = "hashlib_stub"
        fallback = False
        if not settings.demo.enabled and importlib.util.find_spec("whisper") is not None:
            # 可选依赖只在局部 try 内导入；processor 契约不落盘，
            # 没有可供 whisper 使用的文件路径，因此真实转写不在本层执行，
            # 仍回退确定性占位 ASR 并如实标记 fallback。
            try:
                import whisper  # noqa: F401  # type: ignore[import-not-found]
            except ImportError:
                fallback = True
            else:
                fallback = True

        content = (
            f"音频 WAV 占位转写：{asr_text}。时长 {duration:.3f} 秒，"
            f"采样率 {frame_rate} Hz，{channels} 声道，采样宽度 {sample_width} 字节，"
            f"共 {n_frames} 帧。"
            "该音频被统一抽象为描述性文本证据，含音频、WAV、时长等可检索关键词。"
        )
        metadata: dict[str, Any] = {
            "sample_rate": frame_rate,
            "channels": channels,
            "sample_width": sample_width,
            "frames": n_frames,
            "duration_seconds": round(duration, 6),
            "asr_engine": asr_engine,
            "fallback": fallback,
        }
        return [build_chunk(raw, self.modality, 0, content, metadata)]


__all__ = ["AudioProcessor"]
