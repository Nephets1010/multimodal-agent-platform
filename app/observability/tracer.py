"""JSONL 轨迹落盘与回放（P0-5）。

落盘前统一调 :func:`app.observability.logging.redact_snapshot` 剔除敏感键与文件正文；
``replay(trace_id)`` 不存在时返回 ``[]``（由 routes 层转 HTTP 200 空集，Q7）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.observability.logging import collect_secrets, redact_snapshot
from app.schemas import TraceEvent

if TYPE_CHECKING:
    from app.config import Paths, Settings


class AgentTracer:
    """追加写 ``data/traces.jsonl``，每行一条单行 JSON。"""

    def __init__(self, paths: "Paths", settings: "Settings") -> None:
        self._path = paths.trace_path
        self._secrets = collect_secrets(settings)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: TraceEvent) -> None:
        """写一条轨迹；``state_snapshot`` 与整条记录都先脱敏。"""
        data: dict[str, Any] = (
            event.model_dump(mode="json")
            if isinstance(event, TraceEvent)
            else dict(event)
        )
        data.setdefault("ts", datetime.now(timezone.utc).isoformat())
        safe = redact_snapshot(data, self._secrets)
        line = json.dumps(
            safe, ensure_ascii=False, separators=(",", ":"), default=str
        )
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def replay(self, trace_id: str) -> list[dict[str, Any]]:
        """按写入顺序返回该 trace 的全部事件；文件不存在／损坏行都安全跳过。"""
        if not self._path.exists():
            return []
        events: list[dict[str, Any]] = []
        try:
            text = self._path.read_text(encoding="utf-8")
        except OSError:
            return []
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("trace_id") == trace_id:
                events.append(record)
        return events

    def close(self) -> None:
        """追加写模式无需持有句柄；保留接口供组合根 shutdown 调用。"""
        return None


__all__ = ["AgentTracer"]
