"""**唯一一份** Planner / Worker / Reflector 节点函数 + 3 个条件路由。

三个节点都是纯函数（``state in → state out``）：不写日志／轨迹／SSE，
不直接执行工具（经 ``ctx.tools.invoke``）、不直接检索（经 ``ctx.retriever.retrieve``）。
``CompiledGraph`` 基类与两个图后端都从 ``graph.py`` 的 ``NODE_FUNCTIONS`` 读取本模块函数，
因此不存在两套业务逻辑。

组合根类型用 :class:`GraphContext` Protocol 标注，**运行时不 import ``app.runtime``**。
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Protocol

from app.agent.state import AgentState
from app.generation.router import stringify_output, synthesize_answer
from app.schemas import ToolCall

# --------------------------------------------------------------------------- #
# 组合根协议（避免硬 import app.runtime）
# --------------------------------------------------------------------------- #


class GraphContext(Protocol):
    """图执行所需的最小组合根契约。"""

    settings: Any
    tools: Any
    retriever: Any
    index: Any
    graph_backend: str
    fallback_flags: list[str]


# --------------------------------------------------------------------------- #
# 规则式 Planner
# --------------------------------------------------------------------------- #

#: 匹配 ``12*8`` / ``100/4`` / ``1 + 2 * 3`` 之类的纯算式。
_EXPRESSION_RE = re.compile(
    r"(?<![\d.])([+-]?\d+(?:\.\d+)?(?:\s*[-+*/%]\s*[+-]?\d+(?:\.\d+)?)+)(?![\d.])"
)

_TIME_WORDS: tuple[str, ...] = (
    "时间", "几点", "当前", "日期", "现在", "今天", "时刻", "时区", "utc",
)
_STATS_WORDS: tuple[str, ...] = (
    "统计", "字数", "摘要", "多少字", "文本分析", "字符数", "词频",
)
_SEARCH_WORDS: tuple[str, ...] = (
    "检索", "搜索", "查询", "知识", "说明", "介绍", "平台", "资料", "混合",
    "什么是", "解释", "原理", "如何", "文档", "内容", "策略", "抽象层", "证据",
)


def _extract_expression(query: str) -> str | None:
    """从自然语言中抽出可计算的算式；``"计算 12*8 的结果"`` → ``"12*8"``。"""
    match = _EXPRESSION_RE.search(query or "")
    if match is None:
        return None
    expression = match.group(1).strip()
    return expression or None


def planner_node(state: AgentState, ctx: GraphContext) -> AgentState:
    """规则式识别算术／时间／统计／检索意图 → ``plan: list[ToolCall]``。

    无工具意图 → ``next_node="reflector"``（Reflector 仍会检索并合成答案）。
    重规划最多一次：``replan_count >= 1`` 时生成空 plan 直接收敛。
    """
    debug = dict(state.last_debug)
    base_debug = {
        **debug,
        "graph_backend": ctx.graph_backend,
        "demo_mode": bool(ctx.settings.demo.enabled),
    }
    if int(debug.get("replan_count", 0)) >= 1:
        return replace(
            state,
            plan=[],
            node="planner",
            next_node="reflector",
            last_debug={**base_debug, "planner_plan_size": 0},
        )

    query = state.query or ""
    lowered = query.lower()
    plan: list[ToolCall] = []

    expression = _extract_expression(query)
    if expression:
        plan.append(ToolCall(name="calculator", arguments={"expression": expression}))
    if any(word in lowered for word in _TIME_WORDS):
        plan.append(ToolCall(name="current_time", arguments={}))
    if any(word in lowered for word in _STATS_WORDS):
        plan.append(ToolCall(name="text_stats", arguments={"text": query}))
    if any(word in lowered for word in _SEARCH_WORDS):
        plan.append(
            ToolCall(
                name="knowledge_search",
                arguments={"query": query, "top_k": int(ctx.settings.vector_store.top_k)},
            )
        )

    return replace(
        state,
        plan=plan,
        node="planner",
        next_node="worker" if plan else "reflector",
        last_debug={**base_debug, "planner_plan_size": len(plan)},
    )


def worker_node(state: AgentState, ctx: GraphContext) -> AgentState:
    """逐条 ``ctx.tools.invoke(...)`` 回填 ``tool_calls`` / ``tool_results`` 与观察。"""
    results = list(state.tool_results)
    calls = list(state.tool_calls)
    observation = state.last_observation
    planned = list(state.plan)

    for tool_call in planned:
        result = ctx.tools.invoke(tool_call.name, tool_call.arguments)
        results.append(result)
        calls.append(tool_call)
        observation = (
            stringify_output(result.output) if result.ok else (result.error or "工具执行失败")
        )

    return replace(
        state,
        plan=[],
        tool_calls=calls,
        tool_results=results,
        last_observation=observation,
        node="worker",
        next_node="reflector",
        last_debug={**state.last_debug, "worker_executed": len(planned)},
    )


def reflector_node(state: AgentState, ctx: GraphContext) -> AgentState:
    """检索证据 + 判断是否重规划 + 调 ``synthesize_answer()`` 合成四段式答案。"""
    modalities = list(state.last_debug.get("modalities") or [])
    top_k = int(ctx.settings.vector_store.top_k)
    try:
        evidences, debug = ctx.retriever.retrieve(state.query, modalities, top_k)
    except Exception as exc:
        evidences = []
        debug = {"strategy": "empty", "retriever_error": type(exc).__name__}

    merged_debug: dict[str, Any] = {
        **state.last_debug,
        **debug,
        "graph_backend": ctx.graph_backend,
        "demo_mode": bool(ctx.settings.demo.enabled),
        "soft_limit_warning": bool(debug.get("soft_limit_warning"))
        or bool(ctx.index.last_soft_limit_warning),
    }

    failures = [result for result in state.tool_results if not result.ok]
    replan_count = int(state.last_debug.get("replan_count", 0))
    need_replan = bool(failures) and replan_count < 1 and state.steps < state.max_steps - 1
    if need_replan:
        merged_debug["replan_count"] = replan_count + 1
    merged_debug["need_replan"] = need_replan

    flags = list(state.fallback_flags)
    if failures and "tool_failure" not in flags:
        flags.append("tool_failure")

    candidate = replace(
        state,
        evidences=evidences,
        last_debug=merged_debug,
        status="degraded" if failures else "ok",
        fallback_flags=flags,
        node="reflector",
        next_node="planner" if need_replan else "done",
    )
    answer = synthesize_answer(candidate, ctx.settings)
    human_required = bool(ctx.settings.agent.human_in_loop) and not need_replan
    return replace(
        candidate,
        answer=answer,
        human_required=human_required,
        pending_step="reflector" if human_required else None,
    )


# --------------------------------------------------------------------------- #
# 条件路由（纯函数，返回分支字符串）
# --------------------------------------------------------------------------- #


def route_after_planner(state: AgentState) -> str:
    return "worker" if state.plan else "reflector"


def route_after_worker(state: AgentState) -> str:
    return "planner" if state.last_debug.get("need_replan") else "reflector"


def route_after_reflector(state: AgentState) -> str:
    return "planner" if state.last_debug.get("need_replan") else "done"


__all__ = [
    "GraphContext",
    "planner_node",
    "worker_node",
    "reflector_node",
    "route_after_planner",
    "route_after_worker",
    "route_after_reflector",
]
