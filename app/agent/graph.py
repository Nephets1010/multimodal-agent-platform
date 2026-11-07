"""唯一图实现：三份纯数据常量 + ``CompiledGraph`` 基类模板方法 + 两个仅实现 ``_iterate`` 的子类。

硬约束 3 的落地：
* ``NODE_FUNCTIONS`` / ``EDGE_SPEC`` / ``CONDITIONAL_EDGES`` 是**模块级纯数据常量**，
  ``PureStateMachine`` 与 ``LangGraphCompiled`` 都从它们读取，禁止各自硬编码节点顺序或边。
* ``CompiledGraph`` 基类用**模板方法**统一实现 ``run()`` / ``stream_events()`` / ``resume()``，
  包含步数保护、SSE 事件顺序、token 定长切片、``done`` 调 ``build_unified_response()``。
* 子类**只允许实现 ``_iterate()``**，不得生成 SSE 帧、拼答案、执行工具或写轨迹。
* ``build_graph()`` 是创建图实例的唯一入口；DEMO 下生效后端恒为 ``pure``。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, Iterator

from app.agent.nodes import (
    planner_node,
    reflector_node,
    route_after_planner,
    route_after_reflector,
    route_after_worker,
    worker_node,
)
from app.agent.state import AgentState
from app.generation.router import build_unified_response, slice_tokens, synthesize_answer
from app.observability.logging import get_logger
from app.schemas import SSEFrame, TraceEvent

if TYPE_CHECKING:
    from app.config import Settings
    from app.runtime import AppContext

# --------------------------------------------------------------------------- #
# 三份纯数据常量（唯一一份，两后端共用）
# --------------------------------------------------------------------------- #

NODE_FUNCTIONS: dict[str, Callable[[AgentState, Any], AgentState]] = {
    "planner": planner_node,
    "worker": worker_node,
    "reflector": reflector_node,
}

EDGE_SPEC: dict[str, str] = {
    "planner": "worker",
    "worker": "reflector",
    "reflector": "done",
}

CONDITIONAL_EDGES: dict[
    str, tuple[Callable[[AgentState], str], dict[str, str]]
] = {
    "planner": (
        route_after_planner,
        {"worker": "worker", "reflector": "reflector"},
    ),
    "worker": (
        route_after_worker,
        {"reflector": "reflector", "planner": "planner"},
    ),
    "reflector": (
        route_after_reflector,
        {"done": "done", "planner": "planner"},
    ),
}


def _emit_trace(ctx: Any, snap: AgentState, event_name: str) -> None:
    """写 JSONL 轨迹（脱敏由 tracer 负责）；失败绝不影响主链路。"""
    try:
        ctx.tracer.emit(
            TraceEvent(
                ts=datetime.now(timezone.utc).isoformat(),
                trace_id=snap.trace_id,
                session_id=snap.session_id,
                event=event_name,
                node=snap.node,
                steps=int(snap.steps),
                status=str(snap.status),
                elapsed_ms=float(snap.elapsed_ms),
                state_snapshot=snap.to_dict(),
            )
        )
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 基类模板方法
# --------------------------------------------------------------------------- #


class CompiledGraph(ABC):
    """对外唯一图接口；基类统一实现全部模板方法，子类只实现 ``_iterate()``。"""

    def __init__(self, ctx: "AppContext") -> None:
        self.ctx = ctx

    # -- 子类唯一差异点 ----------------------------------------------------- #
    @abstractmethod
    def _iterate(self, state: AgentState) -> Iterator[AgentState]:
        """按 ``EDGE_SPEC`` / ``CONDITIONAL_EDGES`` 驱动节点，产出状态快照流。"""
        raise NotImplementedError

    # -- 基类提供的公共设施（子类调用，不重写） ----------------------------- #
    def apply_node(self, state: AgentState, node_name: str) -> AgentState:
        """执行 ``NODE_FUNCTIONS`` 中的节点（唯一一份），并推进步数。"""
        function = NODE_FUNCTIONS[node_name]
        result = function(state, self.ctx)
        return replace(result, steps=state.steps + 1, node=node_name)

    def select_next(self, state: AgentState, node_name: str) -> str:
        """按条件边或固定边选择下一个节点名（只从三份常量读取）。"""
        if node_name in CONDITIONAL_EDGES:
            route_function, mapping = CONDITIONAL_EDGES[node_name]
            branch = route_function(state)
            return mapping.get(branch, EDGE_SPEC.get(node_name, "done"))
        return EDGE_SPEC.get(node_name, "done")

    def guard_steps(self, state: AgentState, proposed_next: str) -> str:
        """步数保护：``steps >= max_steps`` 且未到 done → 强制进 Reflector 收敛。"""
        if state.steps >= state.max_steps and proposed_next != "done":
            return "reflector"
        return proposed_next

    def _drive(self, state: AgentState) -> Iterator[AgentState]:
        """基类统一节点驱动引擎（PureStateMachine 直接复用）。"""
        current = state
        node = "planner"
        hard_limit = max(3, int(current.max_steps) * 3)
        for _ in range(hard_limit):
            if node == "done":
                break
            current = self.apply_node(current, node)
            proposed = self.select_next(current, node)
            next_node = self.guard_steps(current, proposed)
            current = replace(current, next_node=next_node)
            yield current
            node = next_node

    def converge(self, state: AgentState) -> AgentState:
        """兜底收敛：确保答案已生成、``next_node="done"``，不再继续条件边。"""
        if state.answer and state.next_node == "done":
            return state
        out = reflector_node(state, self.ctx)
        if not out.answer:
            out = replace(out, answer=synthesize_answer(out, self.ctx.settings))
        return replace(
            out,
            next_node="done",
            node="reflector",
            last_debug={**out.last_debug, "need_replan": False},
        )

    def _prepare(self, state: AgentState) -> AgentState:
        """把生效后端 / demo 标记写入 last_debug，供生成层与轨迹使用。"""
        return replace(
            state,
            last_debug={
                **state.last_debug,
                "graph_backend": self.ctx.graph_backend,
                "demo_mode": bool(self.ctx.settings.demo.enabled),
            },
        )

    # -- 模板方法：run / stream_events / resume ----------------------------- #
    def run(self, state: AgentState) -> AgentState:
        """非流式执行（评测与 ``/v1/chat stream=false`` 共用）。"""
        started = time.perf_counter()
        prepared = self._prepare(state)
        final = prepared
        for snapshot in self._iterate(prepared):
            final = snapshot
            _emit_trace(self.ctx, snapshot, "step")
        final = self.converge(final)
        final = replace(final, elapsed_ms=(time.perf_counter() - started) * 1000.0)
        _emit_trace(self.ctx, final, "done")
        return final

    def stream_events(self, state: AgentState) -> Iterator[SSEFrame]:
        """模板方法统一事件顺序：``meta → step* → token* → [human_required] → done``。"""
        started = time.perf_counter()
        prepared = self._prepare(state)
        yield ("meta", {"trace_id": prepared.trace_id, "backend": self.ctx.graph_backend})

        final = prepared
        for snapshot in self._iterate(prepared):
            final = snapshot
            _emit_trace(self.ctx, snapshot, "step")
            yield (
                "step",
                {
                    "steps": int(snapshot.steps),
                    "node": snapshot.node,
                    "next_node": snapshot.next_node,
                    "status": str(snapshot.status),
                    "last_observation": snapshot.last_observation,
                },
            )

        final = self.converge(final)
        final = replace(final, elapsed_ms=(time.perf_counter() - started) * 1000.0)

        for delta in slice_tokens(final.answer, self.ctx.settings.agent.token_chunk_chars):
            yield ("token", {"delta": delta})

        if final.human_required or (
            self.ctx.settings.agent.human_in_loop and final.pending_step
        ):
            yield (
                "human_required",
                {"prompt": "该轮推理需要人工确认；resume(state, 'approved') 仅图层 API 可用"},
            )

        # done 恒存在、恒为最后一帧，携带完整 11 字段 UnifiedResponse
        unified = build_unified_response(
            final, self.ctx.settings, final.trace_id, final.elapsed_ms
        )
        yield ("done", unified.model_dump(mode="json"))
        _emit_trace(self.ctx, final, "done")

    def resume(self, state: AgentState, decision: str = "approved") -> AgentState:
        """Q10：仅图层 API，本期无 REST 恢复端点。批准即清除断点并收敛。"""
        if decision != "approved":
            return state
        cleared = replace(
            state,
            human_required=False,
            pending_step=None,
            next_node="done",
            last_debug={**state.last_debug, "resumed": True, "need_replan": False},
        )
        return self.converge(cleared)


# --------------------------------------------------------------------------- #
# 两个子类：只允许实现 _iterate()
# --------------------------------------------------------------------------- #


class PureStateMachine(CompiledGraph):
    """纯 Python 等价状态机：直接复用基类 ``_drive`` 按三份常量驱动节点。"""

    def _iterate(self, state: AgentState) -> Iterator[AgentState]:
        yield from self._drive(state)


class LangGraphCompiled(CompiledGraph):
    """真实 LangGraph ``StateGraph`` 适配器。

    构造时用**同一份** ``NODE_FUNCTIONS`` / ``EDGE_SPEC`` / ``CONDITIONAL_EDGES``
    注册并编译图；``_iterate`` 用编译结果驱动节点顺序，再复用基类的
    ``select_next`` / ``guard_steps`` 生成一致的快照流（步数保护与 SSE 语义不重复实现）。
    构造／运行异常一律由 ``build_graph`` 捕获回退 ``PureStateMachine``，绝不崩溃。
    """

    def __init__(self, ctx: "AppContext") -> None:
        super().__init__(ctx)
        self._compiled = self._compile(ctx)

    def _compile(self, ctx: "AppContext") -> Any:
        from langgraph.graph import END, StateGraph  # type: ignore[import-not-found]

        builder = StateGraph(dict)

        def _wrap(function: Callable[[AgentState, Any], AgentState]) -> Callable:
            def _node(state_dict: dict[str, Any]) -> dict[str, Any]:
                current = AgentState.from_dict(state_dict)
                result = function(current, ctx)
                return result.to_dict()

            return _node

        for node_name, function in NODE_FUNCTIONS.items():
            builder.add_node(node_name, _wrap(function))
        builder.set_entry_point("planner")

        for source, (route_function, mapping) in CONDITIONAL_EDGES.items():
            path_map = {
                branch: (END if target == "done" else target)
                for branch, target in mapping.items()
            }

            def _router(
                state_dict: dict[str, Any], _route: Callable[[AgentState], str] = route_function
            ) -> str:
                return _route(AgentState.from_dict(state_dict))

            builder.add_conditional_edges(source, _router, path_map)

        for source, target in EDGE_SPEC.items():
            if source not in CONDITIONAL_EDGES:
                builder.add_edge(source, END if target == "done" else target)
        return builder.compile()

    def _iterate(self, state: AgentState) -> Iterator[AgentState]:
        current = state
        hard_limit = max(3, int(state.max_steps) * 3)
        count = 0
        try:
            for update in self._compiled.stream(current.to_dict()):
                if not isinstance(update, dict):
                    continue
                for node_name, state_dict in update.items():
                    if node_name not in NODE_FUNCTIONS or not isinstance(state_dict, dict):
                        continue
                    count += 1
                    if count > hard_limit:
                        return
                    snapshot = AgentState.from_dict(state_dict)
                    snapshot = replace(
                        snapshot, steps=current.steps + 1, node=node_name
                    )
                    proposed = self.select_next(snapshot, node_name)
                    next_node = self.guard_steps(snapshot, proposed)
                    snapshot = replace(snapshot, next_node=next_node)
                    yield snapshot
                    current = snapshot
        except Exception as exc:
            get_logger("agent.graph").warning(
                "langgraph 运行期异常，交给基类收敛：%s",
                type(exc).__name__,
                extra={"event": "fallback", "fallback": True},
            )


# --------------------------------------------------------------------------- #
# 唯一入口
# --------------------------------------------------------------------------- #


def _record_langgraph_fallback(ctx: "AppContext", reason: str) -> None:
    if "langgraph" not in ctx.fallback_flags:
        ctx.fallback_flags.append("langgraph")
    get_logger("agent.graph").warning(
        "graph fallback -> pure (%s)",
        reason,
        extra={"event": "fallback", "fallback": True},
    )


def build_graph(settings: "Settings", ctx: "AppContext") -> CompiledGraph:
    """创建图实例的**唯一入口**。

    DEMO 下即使 ``probes.langgraph == "native"`` 也强制 ``pure``：
    探测结果与生效后端是两条独立数据流（ARCH §5.6）。
    """
    ctx.graph_backend = "pure"
    if settings.demo.enabled or ctx.probes.get("langgraph") != "native":
        return PureStateMachine(ctx)
    try:
        graph = LangGraphCompiled(ctx)
    except Exception as exc:
        _record_langgraph_fallback(ctx, type(exc).__name__)
        return PureStateMachine(ctx)
    ctx.graph_backend = "langgraph"
    return graph


__all__ = [
    "NODE_FUNCTIONS",
    "EDGE_SPEC",
    "CONDITIONAL_EDGES",
    "CompiledGraph",
    "PureStateMachine",
    "LangGraphCompiled",
    "build_graph",
]
