"""可序列化的 Agent 状态（供轨迹快照与 ``resume()`` 使用）。

``AgentState`` 是 dataclass，节点函数用 ``dataclasses.replace`` 产出新快照，
保证每个 SSE ``step`` 帧与 JSONL 轨迹快照互不污染。
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from pydantic import BaseModel

from app.schemas import Evidence, ToolCall, ToolResult


def make_trace_id(query: str, session_id: str = "default") -> str:
    """生成请求内全局唯一的 trace_id（``hashlib``，禁用内置 ``hash()``）。

    不要求逐次一致（含 ``monotonic_ns``），但同一请求内贯穿日志／轨迹／响应。
    """
    seed = f"{time.monotonic_ns()}|{query}|{session_id}".encode("utf-8")
    return "tr_" + hashlib.sha256(seed).hexdigest()[:16]


def _serialize(value: Any) -> Any:
    """把模型/枚举/list/dict 递归转成纯 JSON 可序列化结构。"""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    return value


def _restore_list(model_cls: type[BaseModel], values: Any) -> list[Any]:
    """把 dict 列表还原为契约模型列表；非法项跳过而不抛异常。"""
    restored: list[Any] = []
    for item in values or []:
        if isinstance(item, model_cls):
            restored.append(item)
            continue
        try:
            restored.append(model_cls.model_validate(item))
        except Exception:
            continue
    return restored


@dataclass
class AgentState:
    """Planner / Worker / Reflector 三节点共享的状态。"""

    trace_id: str = ""
    session_id: str = "default"
    query: str = ""
    steps: int = 0
    max_steps: int = 8
    plan: list[ToolCall] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    evidences: list[Evidence] = field(default_factory=list)
    answer: str = ""
    status: str = "ok"
    node: str = ""
    next_node: str = ""
    last_observation: str = ""
    last_debug: dict[str, Any] = field(default_factory=dict)
    human_required: bool = False
    pending_step: str | None = None
    fallback_flags: list[str] = field(default_factory=list)
    elapsed_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """JSON 可序列化快照（枚举转 str、契约模型转 dict）。"""
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "query": self.query,
            "steps": int(self.steps),
            "max_steps": int(self.max_steps),
            "plan": _serialize(self.plan),
            "tool_calls": _serialize(self.tool_calls),
            "tool_results": _serialize(self.tool_results),
            "evidences": _serialize(self.evidences),
            "answer": self.answer,
            "status": str(self.status),
            "node": self.node,
            "next_node": self.next_node,
            "last_observation": self.last_observation,
            "last_debug": _serialize(self.last_debug),
            "human_required": bool(self.human_required),
            "pending_step": self.pending_step,
            "fallback_flags": list(self.fallback_flags),
            "elapsed_ms": float(self.elapsed_ms),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        """从快照还原；缺字段用安全默认值，兼容 langgraph 的 dict 状态。"""
        source = data or {}
        return cls(
            trace_id=str(source.get("trace_id", "")),
            session_id=str(source.get("session_id", "default")),
            query=str(source.get("query", "")),
            steps=int(source.get("steps", 0) or 0),
            max_steps=int(source.get("max_steps", 8) or 8),
            plan=_restore_list(ToolCall, source.get("plan")),
            tool_calls=_restore_list(ToolCall, source.get("tool_calls")),
            tool_results=_restore_list(ToolResult, source.get("tool_results")),
            evidences=_restore_list(Evidence, source.get("evidences")),
            answer=str(source.get("answer", "") or ""),
            status=str(source.get("status", "ok") or "ok"),
            node=str(source.get("node", "") or ""),
            next_node=str(source.get("next_node", "") or ""),
            last_observation=str(source.get("last_observation", "") or ""),
            last_debug=dict(source.get("last_debug") or {}),
            human_required=bool(source.get("human_required", False)),
            pending_step=source.get("pending_step"),
            fallback_flags=list(source.get("fallback_flags") or []),
            elapsed_ms=float(source.get("elapsed_ms", 0.0) or 0.0),
        )


__all__ = ["AgentState", "make_trace_id"]
