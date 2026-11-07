"""结构化 JSON 行日志与强制脱敏（Q12 / NF-2）。

三个脱敏出口统一收口：
  ① 日志 Formatter（本模块 ``JsonFormatter`` + ``RedactFilter``）
  ② 轨迹 ``AgentTracer.emit()`` 落盘前调用 :func:`redact_snapshot`
  ③ HTTP 异常响应构造（``app/main.py`` 只返回 ``{"detail": ...}``）

日志**只写 stdout**，不写文件、不写第三方服务；轨迹另走 ``data/traces.jsonl``。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

from app.config import PROJECT_ROOT, load_dotenv_simple

REDACTED = "***REDACTED***"

#: Authorization / Bearer / token= / password= / sk- 前缀凭据（大小写不敏感）。
#: 命中后整行剩余内容一并脱敏，避免 ``Bearer <token>`` 只吃掉前缀而残留密钥值。
_SECRET_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]\s*|bearer\s+|token=|password=|sk-)[^\n]*"
)
_SENSITIVE_KEY_PARTS = (
    "key",
    "token",
    "secret",
    "password",
    "authorization",
    "credential",
)
#: 轨迹快照中需要剔除／摘要化的键（文件正文、完整 prompt 原文等）。
_SENSITIVE_SNAPSHOT_KEYS = (
    "api_key",
    "apikey",
    "authorization",
    "token",
    "secret",
    "password",
    "credential",
    "raw_content",
    "content",
    "bytes",
    "file_content",
    "body",
    "prompt",
    "query",
    "answer",
)
_MAX_MESSAGE = 512

_GLOBAL_SECRETS: set[str] = set()
_CONFIGURED = False


# --------------------------------------------------------------------------- #
# secrets 收集
# --------------------------------------------------------------------------- #


def collect_secrets(settings: Any | None = None) -> set[str]:
    """收集需要脱敏的明文值：``.env`` 全部值 + 键名敏感的非空环境／配置值。"""
    secrets: set[str] = set()

    for value in load_dotenv_simple(PROJECT_ROOT / ".env").values():
        if value and len(value) >= 4:
            secrets.add(value)

    for key, value in os.environ.items():
        if value and len(value) >= 4 and any(p in key.lower() for p in _SENSITIVE_KEY_PARTS):
            secrets.add(value)

    if settings is not None:
        try:
            dump = settings.model_dump()
        except Exception:
            dump = {}

        def _walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    if isinstance(value, (dict, list)):
                        _walk(value)
                    elif value and any(p in str(key).lower() for p in _SENSITIVE_KEY_PARTS):
                        text = str(value)
                        if len(text) >= 4:
                            secrets.add(text)
            elif isinstance(obj, list):
                for item in obj:
                    _walk(item)

        _walk(dump)
    return secrets


# --------------------------------------------------------------------------- #
# 公共脱敏函数（供 tracer / 日志共用）
# --------------------------------------------------------------------------- #


def redact_text(text: Any, secrets: set[str] | None = None) -> str:
    """正则脱敏 + 已知明文子串替换 + 长度截断（保证单行且不含敏感原文）。"""
    result = text if isinstance(text, str) else str(text)
    active = set(secrets or ()) | _GLOBAL_SECRETS
    result = _SECRET_PATTERN.sub(REDACTED, result)
    for secret in sorted(active, key=len, reverse=True):
        if secret and len(secret) >= 4 and secret in result:
            result = result.replace(secret, REDACTED)
    if len(result) > _MAX_MESSAGE:
        result = result[:_MAX_MESSAGE] + "…(truncated)"
    return result


def redact_snapshot(
    snapshot: dict[str, Any], secrets: set[str] | None = None
) -> dict[str, Any]:
    """递归脱敏状态快照：剔除敏感键与文件字节，``query``/``answer`` 只留长度＋前 120 字摘要。"""

    def _walk(obj: Any, depth: int = 0) -> Any:
        if depth > 8:
            return REDACTED
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for key, value in obj.items():
                lowered = str(key).lower()
                if any(part in lowered for part in _SENSITIVE_SNAPSHOT_KEYS):
                    if lowered in ("query", "answer"):
                        text = value if isinstance(value, str) else str(value)
                        out[key] = {
                            "length": len(text),
                            "preview": redact_text(text[:120], secrets),
                        }
                    else:
                        out[key] = REDACTED
                else:
                    out[key] = _walk(value, depth + 1)
            return out
        if isinstance(obj, (list, tuple)):
            return [_walk(item, depth + 1) for item in list(obj)[:50]]
        if isinstance(obj, str):
            return redact_text(obj, secrets)
        if isinstance(obj, (bytes, bytearray)):
            return REDACTED
        if obj is None or isinstance(obj, (int, float, bool)):
            return obj
        return redact_text(str(obj), secrets)

    return _walk(snapshot)


# --------------------------------------------------------------------------- #
# Formatter / Filter / Adapter
# --------------------------------------------------------------------------- #


class JsonFormatter(logging.Formatter):
    """输出**单行 JSON**，必需 ``ts``/``level``/``event``/``component``/``trace_id``/``message``。"""

    def __init__(self, secrets: set[str] | None = None) -> None:
        super().__init__()
        self._secrets = set(secrets or ())

    def format(self, record: logging.LogRecord) -> str:
        active = self._secrets | _GLOBAL_SECRETS
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "event": str(getattr(record, "event", "log")),
            "component": str(getattr(record, "component", "-")),
            "trace_id": str(getattr(record, "trace_id", "-")),
            "message": redact_text(record.getMessage(), active),
        }
        for extra_key in ("elapsed_ms", "fallback", "node", "strategy", "steps"):
            if hasattr(record, extra_key):
                payload[extra_key] = getattr(record, extra_key)
        if record.exc_info:
            # 堆栈只进结构化日志（且经脱敏），绝不进 HTTP 响应。
            payload["traceback"] = redact_text(
                self.formatException(record.exc_info), active
            )
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


class RedactFilter(logging.Filter):
    """在 ``record`` 进入 Formatter 前，对 ``message`` 与 ``args`` 渲染结果做脱敏。"""

    def __init__(self, secrets: set[str] | None = None) -> None:
        super().__init__()
        self.secrets = set(secrets or ())

    def filter(self, record: logging.LogRecord) -> bool:
        active = self.secrets | _GLOBAL_SECRETS
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        cleaned = redact_text(rendered, active)
        if cleaned != rendered:
            # 用已渲染的脱敏文本替换 msg 并清空 args，避免破坏 %-formatting。
            record.msg = cleaned
            record.args = ()
        return True


class TraceLoggerAdapter(logging.LoggerAdapter):
    """把 ``component`` / ``trace_id`` / ``event`` 注入每条日志，贯穿一次请求。"""

    def process(
        self, msg: Any, kwargs: dict[str, Any]
    ) -> tuple[Any, dict[str, Any]]:
        merged: dict[str, Any] = dict(self.extra or {})
        merged.update(kwargs.get("extra") or {})
        kwargs["extra"] = merged
        return msg, kwargs


def get_logger(component: str, trace_id: str | None = None) -> logging.LoggerAdapter:
    """返回带组件／轨迹上下文的 logger；事件名通过 ``extra={"event": ...}`` 覆盖。"""
    base = logging.getLogger("multimodal_agent_platform")
    return TraceLoggerAdapter(
        base,
        {"component": component, "trace_id": trace_id or "-", "event": "log"},
    )


def configure_logging(settings: Any | None = None) -> None:
    """幂等地挂载 ``StreamHandler(sys.stdout)`` + ``JsonFormatter`` + ``RedactFilter``。

    只移除本平台自己安装的 handler，不干扰 pytest / uvicorn 的既有 handler。
    """
    global _CONFIGURED, _GLOBAL_SECRETS  # noqa: PLW0603 - 全局脱敏集合是进程级状态
    if settings is None:
        from app.config import get_settings  # 局部导入，避免模块级循环依赖

        settings = get_settings()

    _GLOBAL_SECRETS = collect_secrets(settings)
    root = logging.getLogger()
    level_name = str(getattr(settings.observability, "log_level", "INFO")).upper()
    root.setLevel(getattr(logging, level_name, logging.INFO))

    for handler in list(root.handlers):
        if getattr(handler, "_map_handler", False):
            root.removeHandler(handler)

    stream = logging.StreamHandler(sys.stdout)
    stream._map_handler = True  # type: ignore[attr-defined]
    stream.setFormatter(JsonFormatter(_GLOBAL_SECRETS))
    stream.addFilter(RedactFilter(_GLOBAL_SECRETS))
    root.addHandler(stream)

    # 第三方库（httpx / uvicorn / matplotlib 等）降噪，避免污染结构化日志。
    for noisy in ("httpx", "httpcore", "uvicorn.access", "PIL", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def is_configured() -> bool:
    """是否已安装本平台日志 handler（供组合根判断是否跳过重复配置）。"""
    return _CONFIGURED


__all__ = [
    "REDACTED",
    "JsonFormatter",
    "RedactFilter",
    "TraceLoggerAdapter",
    "configure_logging",
    "get_logger",
    "collect_secrets",
    "redact_text",
    "redact_snapshot",
    "is_configured",
]
