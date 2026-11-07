"""生成层：模板四段式答案、**11 字段唯一出口**、SSE 帧格式化、token 切片。

硬约束：
* ``build_unified_response()`` 是全局**唯一**构造 ``UnifiedResponse`` 的地方，
  非流式响应与 SSE ``done`` 共用，天然字段集合一致。
* ``format_sse()`` 的 ``data:`` 必须是**单行 JSON**（禁止 ``indent``），
  否则前端 ``parseFrame`` 的 ``JSON.parse`` 会静默吞错导致面板空白。
* ``token`` 恒由最终答案定长切片模拟，**不得改挂 ``LLMClient.chat_stream``**。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.observability.logging import get_logger
from app.schemas import GraphBackend, OutputModality, Status, UnifiedResponse

if TYPE_CHECKING:
    from app.agent.state import AgentState
    from app.config import Settings

_OUTPUT_MODALITY_MAP: dict[str, OutputModality] = {
    "text": OutputModality.TEXT,
    "image": OutputModality.IMAGE,
    "audio": OutputModality.AUDIO,
    "video": OutputModality.VIDEO,
    "mixed": OutputModality.MIXED,
}


def stringify_output(value: Any) -> str:
    """把工具输出原值转成字符串（``96`` → ``"96"``），保证模板答案里出现该值。"""
    if value is None:
        return "null"
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return str(value)


def route_output(state: "AgentState") -> OutputModality:
    """DEMO 固定 ``text``；生产模式按证据模态推断（Q4）。"""
    if bool(state.last_debug.get("demo_mode", True)):
        return OutputModality.TEXT
    modalities = {evidence.modality for evidence in state.evidences if evidence.modality}
    if len(modalities) > 1:
        return OutputModality.MIXED
    if not modalities:
        return OutputModality.TEXT
    return _OUTPUT_MODALITY_MAP.get(next(iter(modalities)), OutputModality.TEXT)


def synthesize_answer(state: "AgentState", settings: "Settings") -> str:
    """模板四段式：结论 + 工具结果 + 引用证据 + 推理轨迹。

    「工具结果」逐条输出 ``r.output`` 原值，保证 ``12*8=96`` 的 ``96`` 出现在答案里。
    生产模式可走 LLM API（httpx），失败一律回退模板；DEMO 下 **0 外部请求**。
    """
    lines: list[str] = [
        f"【结论】针对问题「{state.query}」，本轮共执行 {state.steps} 步、"
        f"调用 {len(state.tool_calls)} 个工具，已生成可溯源的统一应答。",
        "【工具结果】",
    ]
    if state.tool_results:
        for result in state.tool_results:
            lines.append(
                f"- {result.name}：{'成功' if result.ok else '失败'}，"
                f"输出 {stringify_output(result.output)}，"
                f"错误 {result.error or '无'}，耗时 {result.elapsed_ms:.2f}ms"
            )
    else:
        lines.append("- 本轮未调用工具。")

    lines.append("【引用证据】")
    if state.evidences:
        for evidence in state.evidences[:5]:
            lines.append(
                f"- [{evidence.modality}] score={evidence.score} · {evidence.snippet}"
            )
    else:
        lines.append("- 暂无命中证据（已走关键词回退或空索引）。")

    strategy = str(state.last_debug.get("strategy", "empty"))
    backend = str(state.last_debug.get("graph_backend", "pure"))
    lines.append(
        f"【推理轨迹】planner → worker → reflector；图后端 {backend}；"
        f"检索策略 {strategy}；链路状态 {state.status}。"
    )
    template_answer = "\n".join(lines)

    if (
        not settings.demo.enabled
        and settings.llm.backend == "api"
        and settings.llm.api_key
        and settings.llm.base_url
    ):
        try:
            import httpx

            response = httpx.post(
                settings.llm.base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm.api_key}"},
                json={
                    "model": settings.llm.model or "gpt-4o-mini",
                    "messages": [{"role": "user", "content": template_answer}],
                    "max_tokens": int(settings.llm.max_tokens),
                },
                timeout=float(settings.llm.timeout_seconds),
            )
            response.raise_for_status()
            candidate = response.json()["choices"][0]["message"]["content"]
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        except Exception as exc:
            get_logger("generation.router").warning(
                "LLM API 失败，回退模板答案：%s",
                type(exc).__name__,
                extra={"event": "fallback", "fallback": True},
            )
    return template_answer


def build_unified_response(
    state: "AgentState",
    settings: "Settings",
    trace_id: str,
    elapsed_ms: float,
) -> UnifiedResponse:
    """**11 字段唯一出口**：非流式与 SSE ``done`` 都由本函数产出。"""
    raw_status = str(state.status or "ok")
    if raw_status == "error":
        status = Status.ERROR
    elif raw_status == "degraded" or bool(state.fallback_flags):
        status = Status.DEGRADED
    else:
        status = Status.OK

    raw_backend = str(state.last_debug.get("graph_backend", "pure"))
    try:
        backend = GraphBackend(raw_backend)
    except ValueError:
        backend = GraphBackend.PURE

    return UnifiedResponse(
        answer=state.answer or "",
        evidences=list(state.evidences),
        tool_calls=list(state.tool_calls),
        tool_results=list(state.tool_results),
        trace_id=trace_id,
        steps=int(state.steps),
        elapsed_ms=float(elapsed_ms),
        status=status,
        output_modality=route_output(state),
        demo_mode=bool(settings.demo.enabled),
        graph_backend=backend,
    )


def format_sse(event: str, data: dict[str, Any]) -> str:
    """``event: X\\ndata: <单行 JSON>\\n\\n``；断言 payload 中无真实换行。"""
    payload = json.dumps(
        data, ensure_ascii=False, separators=(",", ":"), default=str
    )
    assert "\n" not in payload, "SSE data 必须是单行 JSON（禁止 indent / 多行 JSON）"
    return f"event: {event}\ndata: {payload}\n\n"


def slice_tokens(answer: str, chunk_chars: int = 24) -> list[str]:
    """最终答案定长切片；所有 ``token.delta`` 拼接后恒等于 ``done.answer``。"""
    text = answer or ""
    if not text:
        return []
    size = max(1, int(chunk_chars))
    return [text[start : start + size] for start in range(0, len(text), size)]


class AnswerGenerator:
    """组合根装配的生成器门面（薄封装，委托给模块级唯一实现，避免两套业务逻辑）。"""

    def __init__(self, settings: "Settings") -> None:
        self.settings = settings

    def route_output(self, state: "AgentState") -> OutputModality:
        return route_output(state)

    def synthesize_answer(self, state: "AgentState") -> str:
        return synthesize_answer(state, self.settings)

    def build_unified_response(
        self, state: "AgentState", trace_id: str, elapsed_ms: float
    ) -> UnifiedResponse:
        return build_unified_response(state, self.settings, trace_id, elapsed_ms)

    def format_sse(self, event: str, data: dict[str, Any]) -> str:
        return format_sse(event, data)

    def slice_tokens(self, answer: str, chunk_chars: int | None = None) -> list[str]:
        size = chunk_chars if chunk_chars is not None else self.settings.agent.token_chunk_chars
        return slice_tokens(answer, size)


__all__ = [
    "route_output",
    "synthesize_answer",
    "build_unified_response",
    "format_sse",
    "slice_tokens",
    "stringify_output",
    "AnswerGenerator",
]
