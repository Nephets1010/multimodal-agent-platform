"""QA-T12 · 上传护栏纯单元覆盖（guards.py 4 个公共函数 + MIME 兜底）。

此前 ``grep -rn 'save_temporary|cleanup_temporary|validate_uploads|sanitize_filename'
tests/*.py`` 无任何命中，4 个函数只经 API smoke 间接覆盖。本文件用 duck-typed
UploadFile 替身与 ``asyncio.run`` 直接驱动，全部临时文件走 ``tmp_path``。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest

from app.api.guards import (
    cleanup_temporary,
    sanitize_filename,
    save_temporary,
    validate_uploads,
)
from app.modalities.base import detect_modality
from app.schemas import IngestError


class _FakeUpload:
    """validate_uploads 只用到 filename / read() / content_type 三个成员。"""

    def __init__(self, filename: str, data: bytes, content_type: str = "text/plain"):
        self.filename = filename
        self.content_type = content_type
        self._data = data

    async def read(self) -> bytes:
        return self._data


def _run(files: list[_FakeUpload], settings: Any):
    return asyncio.run(validate_uploads(files, settings))


# --------------------------------------------------------------------------- #
# sanitize_filename
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", ["", ".hidden.txt", "..", "...", "..%2f..%2fevil.txt"])
def test_sanitize_filename_rejects_unsafe_names(name):
    with pytest.raises(IngestError) as raised:
        sanitize_filename(name)
    assert raised.value.http_status == 400
    assert "非法文件名" in raised.value.detail


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("../../evil.txt", "evil.txt"),
        ("a/b.txt", "b.txt"),
        ("中文 名.png", "中文_名.png"),
        ("report-2026.Q1.txt", "report-2026.Q1.txt"),
    ],
)
def test_sanitize_filename_accepts_and_sanitizes(name, expected):
    assert sanitize_filename(name) == expected


def test_sanitize_filename_length_boundary():
    """TD-01：<=128 字符通过，>128 抛 IngestError 且 detail 含「文件名」。

    按「修复后行为」断言；源码未落地时该用例应标注「待源码落地后回归」。
    """
    at_limit = "a" * 124 + ".txt"
    assert len(at_limit) == 128
    assert sanitize_filename(at_limit) == at_limit

    over_limit = "a" * 125 + ".txt"
    assert len(over_limit) == 129
    with pytest.raises(IngestError) as raised:
        sanitize_filename(over_limit)
    assert "文件名" in raised.value.detail


# --------------------------------------------------------------------------- #
# validate_uploads 边界
# --------------------------------------------------------------------------- #


def test_validate_uploads_single_file_exact_and_over_limit(settings, monkeypatch):
    monkeypatch.setattr(settings.ingest, "max_file_bytes", 10)
    monkeypatch.setattr(settings.ingest, "max_total_bytes", 100)
    assert len(_run([_FakeUpload("a.txt", b"x" * 10)], settings)) == 1
    with pytest.raises(IngestError) as raised:
        _run([_FakeUpload("a.txt", b"x" * 11)], settings)
    assert "单文件上限" in raised.value.detail


def test_validate_uploads_total_exact_and_over_limit(settings, monkeypatch):
    monkeypatch.setattr(settings.ingest, "max_file_bytes", 10)
    monkeypatch.setattr(settings.ingest, "max_total_bytes", 25)
    assert len(
        _run(
            [
                _FakeUpload("a.txt", b"x" * 10),
                _FakeUpload("b.txt", b"x" * 10),
                _FakeUpload("c.txt", b"x" * 5),
            ],
            settings,
        )
    ) == 3
    with pytest.raises(IngestError) as raised:
        _run(
            [
                _FakeUpload("a.txt", b"x" * 10),
                _FakeUpload("b.txt", b"x" * 10),
                _FakeUpload("c.txt", b"x" * 5),
                _FakeUpload("d.txt", b"x"),
            ],
            settings,
        )
    assert "总量超过上限" in raised.value.detail


def test_validate_uploads_file_count_boundary(settings):
    cap = int(settings.ingest.max_files)
    assert len(
        _run([_FakeUpload(f"f{i}.txt", b"x") for i in range(cap)], settings)
    ) == cap
    with pytest.raises(IngestError) as raised:
        _run([_FakeUpload(f"f{i}.txt", b"x") for i in range(cap + 1)], settings)
    assert "最多上传" in raised.value.detail


def test_validate_uploads_rejects_unknown_extension(settings):
    with pytest.raises(IngestError) as raised:
        _run([_FakeUpload("evil.exe", b"MZ")], settings)
    assert "不支持的扩展名" in raised.value.detail


# --------------------------------------------------------------------------- #
# save_temporary / cleanup_temporary
# --------------------------------------------------------------------------- #


def test_save_temporary_uses_uuid_prefix_and_isolated_dir(tmp_path: Path):
    target_dir = tmp_path / "data" / "tmp"
    path = save_temporary(b"qa-bytes", "a.txt", target_dir)
    assert path.parent == target_dir
    assert path.read_bytes() == b"qa-bytes"
    assert re.fullmatch(r"[0-9a-f]{32}_a\.txt", path.name), path.name
    assert ".." not in path.name and "/" not in path.name


def test_cleanup_temporary_swallows_oserror(monkeypatch, tmp_path: Path):
    def _boom(self, *args: Any, **kwargs: Any):
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(Path, "unlink", _boom)
    cleanup_temporary([tmp_path / "missing.bin"])  # 必须不抛


def test_cleanup_temporary_removes_real_files(tmp_path: Path):
    one = tmp_path / "one.bin"
    two = tmp_path / "two.bin"
    one.write_bytes(b"1")
    two.write_bytes(b"2")
    cleanup_temporary([one, two, tmp_path / "absent.bin"])
    assert not one.exists() and not two.exists()


# --------------------------------------------------------------------------- #
# detect_modality MIME 兜底（此前从未被测试触发）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("name", "mime", "expected"),
    [
        ("blob.unknown", "image/png", "image"),
        ("blob.unknown", "text/plain; charset=utf-8", "text"),
        ("blob.unknown", "application/json", "text"),
        ("A.PNG", "", "image"),
        ("b.WaV", "", "audio"),
    ],
)
def test_detect_modality_mime_fallback_and_case_insensitive(settings, name, mime, expected):
    assert detect_modality(name, mime, settings) == expected


def test_detect_modality_unknown_mime_raises(settings):
    with pytest.raises(IngestError) as raised:
        detect_modality("blob.unknown", "application/octet-stream", settings)
    assert "不支持的扩展名" in raised.value.detail


# --------------------------------------------------------------------------- #
# TD-16 · B2/B4：白名单随配置同源变化，拒绝文案与当前配置一致
# --------------------------------------------------------------------------- #


def test_whitelist_follows_config_changes(settings, monkeypatch):
    """B2：删 .txt / 加 .yaml 后，detect_modality 与 validate_uploads 同步变化。"""
    monkeypatch.setattr(
        settings.ingest,
        "allowed_extensions",
        {"text": [".md", ".yaml"], "image": [".png"]},
    )

    # 新白名单内的扩展名按配置判定
    assert detect_modality("a.yaml", "", settings) == "text"
    assert detect_modality("b.md", "", settings) == "text"
    assert detect_modality("c.png", "", settings) == "image"

    # 被删除的 .txt 不再放行（MIME 兜底也必须兜不住：mime 留空绕过 MIME 路径）
    with pytest.raises(IngestError) as raised:
        detect_modality("a.txt", "", settings)
    assert raised.value.http_status == 400
    assert raised.value.code == "unsupported_extension"
    assert "仅允许 .md, .png, .yaml" in raised.value.detail

    # validate_uploads 与 detect_modality 同源：.txt 拒绝、.yaml 放行
    with pytest.raises(IngestError) as raised:
        _run([_FakeUpload("a.txt", b"x")], settings)
    assert "不支持的扩展名 .txt" in raised.value.detail
    assert _run([_FakeUpload("a.yaml", b"x")], settings)


def test_rejection_message_uses_current_config(settings, monkeypatch):
    """B4：自定义白名单下，错误文案「仅允许 ...」与当前配置一致，不引用旧常量。"""
    monkeypatch.setattr(settings.ingest, "allowed_extensions", {"text": [".txt"]})
    with pytest.raises(IngestError) as raised:
        _run([_FakeUpload("b.png", b"x")], settings)
    detail = raised.value.detail
    assert "仅允许 .txt" in detail
    assert ", " not in detail  # 只有 1 个扩展名，文案不应出现任何旧白名单项
    assert ".md" not in detail and ".wav" not in detail and ".mp4" not in detail
