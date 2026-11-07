"""T03 Agent 编排回归：三节点、4 工具、受限 AST、白名单、超时、max_steps、两图后端、resume。"""

from __future__ import annotations

import time

import pytest

from app.agent.graph import (
    CONDITIONAL_EDGES,
    EDGE_SPEC,
    NODE_FUNCTIONS,
    CompiledGraph,
    LangGraphCompiled,
    PureStateMachine,
    build_graph,
)
from app.agent.nodes import (
    planner_node,
    reflector_node,
    route_after_planner,
    route_after_reflector,
    route_after_worker,
    worker_node,
)
from app.agent.state import AgentState, make_trace_id
from app.agent.tools import safe_calculate
from app.schemas import ToolCall


def _state(query: str, max_steps: int = 8) -> AgentState:
    return AgentState(
        trace_id=make_trace_id(query, "pytest"),
        session_id="pytest",
        query=query,
        max_steps=max_steps,
        last_debug={"modalities": []},
    )


def test_shared_graph_constants():
    """硬约束 3：三份常量唯一，两个子类只继承同一个 CompiledGraph 基类。"""
    assert set(NODE_FUNCTIONS) == {"planner", "worker", "reflector"}
    assert EDGE_SPEC == {
        "planner": "worker",
        "worker": "reflector",
        "reflector": "done",
    }
    assert set(CONDITIONAL_EDGES) == {"planner", "worker", "reflector"}
    assert PureStateMachine.__mro__[1] is CompiledGraph
    assert LangGraphCompiled.__mro__[1] is CompiledGraph


def test_conditional_routes():
    with_plan = AgentState(plan=[ToolCall(name="calculator", arguments={})])
    assert route_after_planner(with_plan) == "worker"
    assert route_after_worker(with_plan) == "reflector"
    assert route_after_reflector(with_plan) == "done"

    need_replan = AgentState(plan=[], last_debug={"need_replan": True})
    assert route_after_planner(need_replan) == "reflector"
    assert route_after_worker(need_replan) == "planner"
    assert route_after_reflector(need_replan) == "planner"


def test_planner_extracts_12_times_8(ctx):
    """P0-3：必须从自然语言抽出 calculator{expression:"12*8"}。"""
    state = planner_node(_state("计算 12*8 的结果"), ctx)
    assert any(
        call.name == "calculator" and call.arguments["expression"] == "12*8"
        for call in state.plan
    )
    assert state.next_node == "worker"


def test_planner_no_tool_intent_goes_to_reflector(ctx):
    state = planner_node(_state("你好，请简单回应一下"), ctx)
    assert state.plan == []
    assert state.next_node == "reflector"


def test_three_nodes_are_pure_functions(ctx):
    initial = _state("计算 12*8 的结果")
    after_planner = planner_node(initial, ctx)
    assert after_planner is not initial
    assert initial.plan == []  # 未就地修改入参

    after_worker = worker_node(after_planner, ctx)
    assert after_worker.tool_calls and after_worker.tool_results
    assert after_worker.tool_results[0].name == "calculator"
    assert after_worker.tool_results[0].ok is True
    assert after_worker.tool_results[0].error is None

    after_reflector = reflector_node(after_worker, ctx)
    assert "96" in after_reflector.answer
    assert after_reflector.next_node == "done"


def test_four_registered_tools_are_reachable(ctx):
    queries = {
        "calculator": "计算 12*8 的结果",
        "current_time": "现在几点了",
        "text_stats": "请统计这段文字的字数并给出摘要",
        "knowledge_search": "介绍一下平台的统一抽象层",
    }
    for tool, query in queries.items():
        final = ctx.graph.run(_state(query))
        assert tool in [call.name for call in final.tool_calls], tool
        assert final.answer


def test_calculator_is_limited_ast_only():
    valid = [("12*8", 96), ("100/4", 25.0), ("2+3*4", 14), ("-5+2", -3)]
    for expression, expected in valid:
        assert safe_calculate(expression) == expected
    for forbidden in (
        "__import__('os').system('echo hi')",
        "a.b",
        "1 if True else 2",
        "[1,2]",
        "1/0",
        "2**100000",
        "abs(-3)",
        "1 & 2",
    ):
        with pytest.raises(Exception):
            safe_calculate(forbidden)


def test_tool_whitelist_and_structured_failure(ctx):
    assert ctx.tools.whitelist() == [
        "calculator",
        "current_time",
        "knowledge_search",
        "text_stats",
    ]
    unknown = ctx.tools.invoke("rm_rf", {})
    assert unknown.ok is False
    assert unknown.error
    assert set(unknown.model_dump()) == {"name", "ok", "elapsed_ms", "output", "error"}

    invalid = ctx.tools.invoke("calculator", {})
    assert invalid.ok is False and "参数校验失败" in invalid.error


def test_tool_timeout_returns_failure_and_chain_continues(ctx, monkeypatch):
    monkeypatch.setattr(ctx.tools, "_timeout", 0.1)
    monkeypatch.setattr(
        ctx.tools._tools["calculator"], "run", lambda **kwargs: time.sleep(0.5)
    )
    result = ctx.tools.invoke("calculator", {"expression": "1+1"})
    assert result.ok is False and "timeout" in result.error
    final = ctx.graph.run(_state("计算 12*8 的结果"))
    assert final.answer  # 链路不中断


def test_max_steps_forces_reflector_convergence(ctx):
    final = ctx.graph.run(_state("计算 12*8 的结果", max_steps=2))
    assert final.answer
    assert final.next_node == "done"
    assert "96" in final.answer


def test_demo_mode_forces_pure_backend_even_if_langgraph_native(ctx, monkeypatch):
    """探测结果 ≠ 启用状态：DEMO 下即使 langgraph=native 也必须 pure。"""
    monkeypatch.setattr(ctx, "probes", {**ctx.probes, "langgraph": "native"})
    graph = build_graph(ctx.settings, ctx)
    assert ctx.graph_backend == "pure"
    assert isinstance(graph, PureStateMachine)


def test_build_graph_falls_back_without_crash(ctx, monkeypatch):
    """生产 + 模拟 langgraph 可用但包缺失 → 捕获异常回退 pure，绝不崩溃。"""
    monkeypatch.setattr(ctx, "probes", {**ctx.probes, "langgraph": "native"})
    monkeypatch.setattr(ctx.settings.demo, "enabled", False)
    graph = build_graph(ctx.settings, ctx)
    assert isinstance(graph, CompiledGraph)
    assert ctx.graph_backend in ("pure", "langgraph")


def test_resume_is_graph_layer_api(ctx):
    state = _state("介绍一下平台")
    state.human_required = True
    state.pending_step = "reflector"
    resumed = ctx.graph.resume(state, "approved")
    assert resumed.human_required is False
    assert resumed.pending_step is None
    assert resumed.answer
    assert ctx.graph.resume(state, "rejected") is state


def test_state_roundtrip_serialization(ctx):
    final = ctx.graph.run(_state("计算 12*8 的结果"))
    restored = AgentState.from_dict(final.to_dict())
    assert restored.query == final.query
    assert restored.steps == final.steps
    assert [r.name for r in restored.tool_results] == [
        r.name for r in final.tool_results
    ]
