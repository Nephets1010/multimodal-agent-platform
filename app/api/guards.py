"""上传安全护栏（Q3 / NF-6）：文件名净化、白名单、大小与数量上限、临时文件隔离。

* 扩展名白名单来自 ``modalities.base.MODALITY_BY_EXT``（大小写不敏感）。
* 单文件 10 MiB / 单次总 50 MiB / 最多 20 文件，用 ``await f.read()`` 实际字节数。
* 临时文件只写 ``data/tmp/``，名字 ``uuid4().hex + "_" + safe_name``，
  **绝不写用户指定路径**，由 routes 在 ``finally`` 中清理。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import UploadFile

from app.modalities.base import MODALITY_BY_EXT
from app.observability.logging import get_logger
from app.schemas import IngestError

if TYPE_CHECKING:
    from app.config import Settings

_UNSAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._\-\u4e00-\u9fff]")


def sanitize_filename(name: str) -> str:
    """``Path(name).name`` 去掉路径部分 → 正则净化 → 拒绝 ``..`` / 空名 / 隐藏名。"""
    base = Path(name or "").name
    safe = _UNSAFE_NAME_RE.sub("_", base)
    if not safe or ".." in safe or safe.startswith("."):
        raise IngestError(f"非法文件名：{name or '(空)'}（不允许路径穿越、空名或隐藏文件）")
    # save_temporary 会拼 32 字符 uuid 前缀，128 上限可避开文件系统 NAME_MAX/MAX_PATH。
    if len(safe) > 128:
        raise IngestError("文件名过长（最多 128 字符），请缩短后重试")
    return safe


async def validate_uploads(
    files: list[UploadFile], settings: "Settings"
) -> list[tuple[str, bytes, str]]:
    """返回 ``[(safe_name, bytes, mime)]``；任何违规抛 ``IngestError``（400 + 可读 detail）。"""
    cfg = settings.ingest
    file_list = list(files or [])
    if len(file_list) > int(cfg.max_files):
        raise IngestError(f"单次最多上传 {cfg.max_files} 个文件，当前 {len(file_list)} 个")

    validated: list[tuple[str, bytes, str]] = []
    total_bytes = 0
    for upload in file_list:
        safe_name = sanitize_filename(upload.filename or "")
        extension = Path(safe_name).suffix.lower()
        if extension not in MODALITY_BY_EXT:
            allowed = ", ".join(sorted(MODALITY_BY_EXT))
            raise IngestError(f"不支持的扩展名 {extension or '(无)'}，仅允许 {allowed}")

        data = await upload.read()
        if len(data) > int(cfg.max_file_bytes):
            raise IngestError(
                f"文件 {safe_name} 超过单文件上限 {cfg.max_file_bytes} 字节（10 MiB）"
            )
        total_bytes += len(data)
        if total_bytes > int(cfg.max_total_bytes):
            raise IngestError(
                f"本次上传总量超过上限 {cfg.max_total_bytes} 字节（50 MiB）"
            )
        validated.append((safe_name, data, upload.content_type or ""))
    return validated


def save_temporary(content: bytes, name: str, tmp_dir: Path) -> Path:
    """把上传字节写入 ``data/tmp/``，文件名带 uuid 前缀，绝不写用户指定路径。"""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    target = tmp_dir / f"{uuid4().hex}_{name}"
    target.write_bytes(content)
    return target


def cleanup_temporary(paths: list[Path]) -> None:
    """尽力删除本次请求产生的临时文件；异常不影响主链路。"""
    for path in paths:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as exc:
            get_logger("api.guards").warning(
                "临时文件清理失败: %s",
                type(exc).__name__,
                extra={"event": "tmp_cleanup_failed"},
            )


__all__ = [
    "sanitize_filename",
    "validate_uploads",
    "save_temporary",
    "cleanup_temporary",
]
