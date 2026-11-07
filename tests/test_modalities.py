"""T02 多模态接入层回归：四模态 / 确定性 / 失败隔离 / 未知扩展名 / 视频降级帧。"""

from __future__ import annotations

import pytest

from app.modalities import PROCESSORS, detect_modality
from app.modalities.image import ImageProcessor
from app.modalities.text import TextProcessor
from app.modalities.video import VideoProcessor
from app.schemas import IngestError, ModalityError, RawInput


def test_four_modalities_each_produce_chunks(sample_resources, settings):
    """P0-1：四模态各 ≥1 切片，每个 chunk 恰好 5 字段。"""
    for modality, raw in sample_resources.items():
        chunks = PROCESSORS[modality]().process(raw, settings)
        assert len(chunks) >= 1, f"{modality} 未产出切片"
        for chunk in chunks:
            assert len(chunk.model_dump()) == 5
            assert chunk.modality == modality
            assert chunk.metadata.get("source_tag") == "pytest"
            assert "chunk_index" in chunk.metadata


def test_chunk_is_fully_deterministic(sample_resources, settings):
    """同一 RawInput 连续两次调用，model_dump() 逐字节相等（含 chunk_id / 指纹 / 占位 ASR）。"""
    for modality, raw in sample_resources.items():
        first = PROCESSORS[modality]().process(raw, settings)
        second = PROCESSORS[modality]().process(raw, settings)
        assert [c.model_dump() for c in first] == [c.model_dump() for c in second]


def test_unknown_extension_raises_readable_ingest_error(settings):
    with pytest.raises(IngestError) as raised:
        detect_modality("x.exe", "application/octet-stream", settings)
    assert raised.value.http_status == 400
    assert "不支持的扩展名" in raised.value.detail
    assert ".txt" in raised.value.detail


def test_extension_case_insensitive(settings):
    assert detect_modality("A.PNG", "", settings) == "image"
    assert detect_modality("b.WaV", "", settings) == "audio"


def test_corrupted_binary_files_are_isolated(settings, corrupt_resources):
    """损坏 PNG / 非 WAV 抛 ModalityError；不可解码 MP4 走确定性降级、不崩溃。"""
    for modality in ("image", "audio"):
        with pytest.raises(ModalityError):
            PROCESSORS[modality]().process(corrupt_resources[modality], settings)

    video_chunks = PROCESSORS["video"]().process(corrupt_resources["video"], settings)
    assert video_chunks
    assert all(chunk.modality == "video" for chunk in video_chunks)
    assert all(chunk.metadata.get("fallback") is True for chunk in video_chunks)
    assert all("图像" in chunk.content for chunk in video_chunks)


def test_video_reuses_image_processor():
    """视频不得另写一套图像处理逻辑。"""
    processor = VideoProcessor()
    assert isinstance(processor._image, ImageProcessor)


def test_video_fallback_frames_are_content_hash_deterministic(settings):
    raw = RawInput(
        name="v.mp4", content=b"seed-content-A", mime="video/mp4", source_tag="pytest"
    )
    other = RawInput(
        name="v.mp4", content=b"seed-content-B", mime="video/mp4", source_tag="pytest"
    )
    first = PROCESSORS["video"]().process(raw, settings)
    second = PROCESSORS["video"]().process(raw, settings)
    different = PROCESSORS["video"]().process(other, settings)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]
    assert [c.chunk_id for c in first] != [c.chunk_id for c in different]


def test_empty_text_returns_empty_list(settings):
    raw = RawInput(
        name="empty.txt", content=b"", mime="text/plain", source_tag="pytest", text="  \n\n "
    )
    assert TextProcessor().process(raw, settings) == []


def test_text_chunk_size_and_overlap(settings):
    long_text = "".join(f"第{i}段内容。" for i in range(200))
    raw = RawInput(
        name="long.txt",
        content=long_text.encode("utf-8"),
        mime="text/plain",
        source_tag="pytest",
        text=long_text,
    )
    chunks = TextProcessor().process(raw, settings)
    assert len(chunks) >= 2
    assert all(len(chunk.content) <= settings.ingest.chunk_size for chunk in chunks)
    assert [c.metadata["chunk_index"] for c in chunks] == list(range(len(chunks)))
