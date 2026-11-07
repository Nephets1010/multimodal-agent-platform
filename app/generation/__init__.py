"""生成层：模板/LLM 答案合成、11 字段统一应答、SSE 帧格式化。"""

from __future__ import annotations

from app.generation.router import (
    AnswerGenerator,
    build_unified_response,
    format_sse,
    route_output,
    slice_tokens,
    stringify_output,
    synthesize_answer,
)

__all__ = [
    "route_output",
    "synthesize_answer",
    "build_unified_response",
    "format_sse",
    "slice_tokens",
    "stringify_output",
    "AnswerGenerator",
]
