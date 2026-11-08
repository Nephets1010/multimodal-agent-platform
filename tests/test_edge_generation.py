"""QA-T04 · generation 层纯单元覆盖（不触网、不启服务、不改契约）。

``app/generation/router.py`` 的 11 个公共名里有 9 个此前从未被 tests 直接引用；
NEG-4 证明把 ``route_output`` 的 MIXED 分支改成 TEXT 后 139 条仍全绿。本文件
针对每个生产分支与 SSE 帧格式做确定性回归，外部 LLM 调用一律 monkeypatch。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.state import AgentState
from app.generation.router import (
    build_unified_response,
    format_sse,
    route_output,
    slice_tokens,
    stringify_output,
    synthesize_answer,
)
from app.schemas import GraphBackend, OutputModality, Status, ToolResult
from app.schemas import Evidence

_UNIFIED_FIELDS = {
    "answer",
    "evidences",
    "tool_calls",
    "tool_results",
    "trace_id",
    "steps",
    "elapsed_ms",
    "status",
    "output_modality",
    "demo_mode",
    "graph_backend",
}


def _settings() -> SimpleNamespace:
    """真实 Settings 的 DEMO 默认值；生产分支用 ``_production_settings`` 覆盖。"""
    from app.config import get_settings

    return get_settings()


def _production_settings(**overrides: Any) -> SimpleNamespace:
    """最小可用的生产 settings 替身，避免修改全局配置或发起真实网络请求。"""
    llm = SimpleNamespace(
        backend="api",
        api_key="unit-test-key",
        base_url="https://invalid.example/v1",
        model="unit-model",
        max_tokens=64,
        timeout_seconds=1.0,
    )
    for key, value in overrides.items():
        setattr(llm, key, value)
    return SimpleNamespace(demo=SimpleNamespace(enabled=False), llm=llm)


def _evidence(modality: str) -> Evidence:
    return Evidence(
        chunk_id=f"chk_{modality}",
        modality=modality,
        snippet="evidence snippet",
        score=0.5,
    )


# --------------------------------------------------------------------------- #
# stringify_output
# --------------------------------------------------------------------------- #


def test_stringify_output_variants():
    assert stringify_output(None) == "null"
    assert stringify_output("plain") == "plain"
    assert stringify_output({"a": 1}) == '{"a":1}'
    assert stringify_output([1, 2]) == "[1,2]"
    circular: list[Any] = []
    circular.append(circular)
    rendered = stringify_output(circular)
    assert isinstance(rendered, str) and rendered  # 循环引用回退不抛异常


# --------------------------------------------------------------------------- #
# route_output（Q4 五种枚举）
# --------------------------------------------------------------------------- #


def test_route_output_demo_is_always_text():
    state = AgentState(last_debug={"demo_mode": True}, evidences=[_evidence("image")])
    assert route_output(state) is OutputModality.TEXT


@pytest.mark.parametrize(
    ("modalities", "expected"),
    [
        ([], OutputModality.TEXT),
        (["text"], OutputModality.TEXT),
        (["image"], OutputModality.IMAGE),
        (["audio"], OutputModality.AUDIO),
        (["video"], OutputModality.VIDEO),
        (["text", "image"], OutputModality.MIXED),
        (["not_a_modality"], OutputModality.TEXT),
    ],
)
def test_route_output_production_enums(modalities, expected):
    state = AgentState(
        last_debug={"demo_mode": False},
        evidences=[_evidence(modality) for modality in modalities],
    )
    assert route_output(state) is expected


# --------------------------------------------------------------------------- #
# synthesize_answer（生产 httpx 成功 / 失败回退模板）
# --------------------------------------------------------------------------- #


def test_synthesize_answer_demo_never_calls_network(monkeypatch):
    import httpx

    calls: list[Any] = []

    def _forbidden(*args: Any, **kwargs: Any):
        calls.append(args)
        raise AssertionError("DEMO 下禁止 httpx.post")

    monkeypatch.setattr(httpx, "post", _forbidden)
    state = AgentState(query="计算 12*8 的结果", steps=2)
    answer = synthesize_answer(state, _settings())
    assert calls == []
    assert answer.startswith("【结论】")
    assert "【工具结果】" in answer
    assert "【引用证据】" in answer
    assert "【推理轨迹】" in answer


def test_synthesize_answer_uses_llm_api_when_configured(monkeypatch):
    import httpx

    captured: dict[str, Any] = {}

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"choices": [{"message": {"content": "  LLM answer  "}}]}

    def _fake_post(url: str, **kwargs: Any):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _Response()

    monkeypatch.setattr(httpx, "post", _fake_post)
    state = AgentState(query="q", steps=1)
    answer = synthesize_answer(state, _production_settings())
    assert answer == "LLM answer"
    assert captured["url"] == "https://invalid.example/v1/chat/completions"
    assert captured["kwargs"]["headers"]["Authorization"] == "Bearer unit-test-key"
    assert captured["kwargs"]["json"]["model"] == "unit-model"


def test_synthesize_answer_falls_back_to_template_on_api_error(monkeypatch):
    import httpx

    def _boom(*args: Any, **kwargs: Any):
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(httpx, "post", _boom)
    state = AgentState(query="q", steps=1)
    answer = synthesize_answer(state, _production_settings())
    assert answer.startswith("【结论】")
    assert "【工具结果】" in answer and "【推理轨迹】" in answer


def test_synthesize_answer_renders_tool_results_and_evidences():
    state = AgentState(
        query="计算 12*8 的结果",
        steps=2,
        tool_results=[
            ToolResult(name="calculator", ok=True, output=96, error=None, elapsed_ms=1.0)
        ],
        evidences=[_evidence("text")],
    )
    answer = synthesize_answer(state, _settings())
    assert "calculator" in answer
    assert "96" in answer
    assert "evidence snippet" in answer


# --------------------------------------------------------------------------- #
# build_unified_response（三种 status + 非法 backend 回退）
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw_status", "flags", "expected"),
    [
        ("ok", [], Status.OK),
        ("degraded", [], Status.DEGRADED),
        ("error", [], Status.ERROR),
        ("ok", ["tool_failure"], Status.DEGRADED),
    ],
)
def test_build_unified_response_statuses(raw_status, flags, expected):
    state = AgentState(
        trace_id="tr_u",
        status=raw_status,
        fallback_flags=list(flags),
        last_debug={"graph_backend": "pure"},
        steps=3,
    )
    response = build_unified_response(state, _settings(), "tr_u", 12.5)
    assert response.status is expected
    assert response.trace_id == "tr_u"
    assert response.elapsed_ms == 12.5
    assert response.graph_backend is GraphBackend.PURE


def test_build_unified_response_has_exactly_11_fields():
    state = AgentState(trace_id="tr_u", last_debug={"graph_backend": "bogus"})
    response = build_unified_response(state, _settings(), "tr_u", 0.0)
    assert set(response.model_dump(mode="json")) == _UNIFIED_FIELDS
    assert response.graph_backend is GraphBackend.PURE  # 非法值回退 pure


# --------------------------------------------------------------------------- #
# format_sse / slice_tokens
# --------------------------------------------------------------------------- #


def test_format_sse_is_single_line_json_frame():
    frame = format_sse("token", {"delta": "第一行\n第二行"})
    assert frame.startswith("event: token\ndata: ")
    assert frame.endswith("\n\n")
    lines = frame.split("\n")
    assert len(lines) == 4 and lines[2] == "" and lines[3] == ""
    payload = lines[1][6:]
    assert "\n" not in payload
    assert json.loads(payload) == {"delta": "第一行\n第二行"}


def test_slice_tokens_boundaries():
    assert slice_tokens("") == []
    assert slice_tokens("abcde", 2) == ["ab", "cd", "e"]
    assert slice_tokens("abc", 0) == ["a", "b", "c"]  # size 下限 1
    assert "".join(slice_tokens("a" * 700, 24)) == "a" * 700
