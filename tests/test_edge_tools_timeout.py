"""TD-21 · C 系列：工具执行 deadline / 协作取消 / 孤儿上限 / 线程池换代。

全部用**局部构造**的 ``ToolRegistry``（stub retriever + 局部 ``Settings``）驱动，
不经组合根 fixture、不碰 ``get_settings`` 的 lru_cache，与全局配置完全隔离。

硬约束（设计 §7）：
* 假慢工具只允许**有限 sleep**（本文件上限 1.0s），禁止无限循环——
  孤儿线程非 daemon，无限循环会挂住进程退出。
* ``invoke`` 恒返回 5 字段 ``ToolResult``；超时文案 ``tool timeout after {timeout}s`` 逐字不变。
* 文件总耗时应 < 3s。

C3 实现说明：``invoke`` 的 ``future.result(timeout)`` 计时起点早于 worker 内
``_TOOL_DEADLINE.set()`` 的起点（worker 启动晚于 submit 返回），两个窗口同为
``tool_timeout_seconds`` 时纯靠 deadline 过期的协作取消与 ``FuturesTimeout``
存在竞态且必输。因此协作测试工具在循环调 ``check_tool_deadline()`` 的同时，
带一个早于注册表硬超时的内部放弃点（0.1s < 0.2s）主动抛 ``ToolCancelled``：
ContextVar → ToolCancelled → ``_CANCELLED`` 哨兵 → invoke 协作分支的机制链路
全部真实走通，且结果确定（不 flaky）。deadline 过期判定本身由下面的直接单测钉住。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from app.agent.tools import (
    _CANCELLED,
    _TOOL_DEADLINE,
    BaseTool,
    ToolCancelled,
    ToolRegistry,
    _run_with_deadline,
    check_tool_deadline,
)
from app.config import AgentCfg, Settings


# --------------------------------------------------------------------------- #
# 局部测试替身（不依赖组合根与全局配置）
# --------------------------------------------------------------------------- #


class _StubRetriever:
    """``KnowledgeSearchTool`` 只调用 ``retrieve(query, [], top_k)``。"""

    def retrieve(self, query: str, extra: list[Any], top_k: int):
        return [], {"strategy": "empty"}


class _SlowTool(BaseTool):
    """假慢工具：无协作检查，sleep 后返回 → 必然走 ``FuturesTimeout`` 硬超时路径。"""

    name = "slow"
    description = "test-only slow tool (finite sleep)"
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs: Any) -> Any:
        time.sleep(1.0)  # 文件内 sleep 上限 1.0s，孤儿线程会自行退出
        return "slow-done"


class _CooperativeSlowTool(BaseTool):
    """协作慢工具：循环调 ``check_tool_deadline()``，0.1s（< 注册表 0.2s）后主动放弃。"""

    name = "cooperative_slow"
    description = "test-only cooperative tool (finite give-up window)"
    parameters = {"type": "object", "properties": {}, "required": []}

    def run(self, **kwargs: Any) -> Any:
        give_up = time.monotonic() + 0.1
        while True:
            check_tool_deadline()  # 注册表 deadline 已过时抛 ToolCancelled
            if time.monotonic() > give_up:
                raise ToolCancelled("cooperative give-up before registry hard timeout")
            time.sleep(0.005)


def _local_settings(**overrides: Any) -> Settings:
    """局部 Settings：不读 YAML、不碰 lru_cache；其余节用默认值。"""
    agent = AgentCfg(
        max_steps=8,
        tool_timeout_seconds=float(overrides.get("tool_timeout_seconds", 0.2)),
        tool_orphan_max=int(overrides.get("tool_orphan_max", 8)),
    )
    return Settings(agent=agent)


def _make_registry(**overrides: Any) -> ToolRegistry:
    """局部构造 ToolRegistry：stub retriever + 慢/协作工具 + 内置 calculator。"""
    settings = _local_settings(**overrides)
    registry = ToolRegistry(retriever=_StubRetriever(), settings=settings)  # type: ignore[arg-type]
    registry.register(_SlowTool())
    registry.register(_CooperativeSlowTool())
    return registry


_TOOL_RESULT_FIELDS = {"name", "ok", "elapsed_ms", "output", "error"}


@pytest.fixture
def registry():
    """每个用例独立注册表；退出时统一关闭（含已换代旧池）。"""
    instance = _make_registry()
    try:
        yield instance
    finally:
        instance.shutdown()


# --------------------------------------------------------------------------- #
# check_tool_deadline / _run_with_deadline 直接单测（无竞态窗口）
# --------------------------------------------------------------------------- #


def test_check_tool_deadline_no_deadline_is_noop():
    """未设 deadline（ContextVar 默认 None）→ no-op，不抛。"""
    _TOOL_DEADLINE.set(None)
    check_tool_deadline()  # 必须不抛


def test_check_tool_deadline_expired_raises():
    """deadline 已过 → 抛 ``ToolCancelled``。"""
    _TOOL_DEADLINE.set(time.monotonic() - 1.0)
    with pytest.raises(ToolCancelled):
        check_tool_deadline()


def test_check_tool_deadline_future_deadline_passes():
    """deadline 未到 → no-op。"""
    _TOOL_DEADLINE.set(time.monotonic() + 60.0)
    check_tool_deadline()


def test_run_with_deadline_negative_timeout_returns_cancelled_sentinel():
    """timeout=-1 → worker 起点 deadline 已过期 → 预检即取消，返回哨兵。"""
    tool = _SlowTool()
    output = _run_with_deadline(tool, {}, timeout=-1.0)
    assert output is _CANCELLED


# --------------------------------------------------------------------------- #
# C2：硬超时（future.result 抛 FuturesTimeout）
# --------------------------------------------------------------------------- #


def test_hard_timeout_returns_exact_text_and_five_fields(registry):
    """C2：sleep(1.0) + timeout 0.2 → ok=False、超时文案逐字、5 字段齐备。"""
    result = registry.invoke("slow", {})
    assert result.ok is False
    assert result.error == "tool timeout after 0.2s"
    assert result.output is None
    assert set(result.model_dump()) == _TOOL_RESULT_FIELDS
    assert len(result.model_dump()) == 5


# --------------------------------------------------------------------------- #
# C3：协作取消 → 无孤儿、不换代
# --------------------------------------------------------------------------- #


def test_cooperative_cancel_leaves_no_orphans(registry):
    """C3：协作工具 → 同一超时文案且 _orphans==0、_retired 为空。"""
    result = registry.invoke("cooperative_slow", {})
    assert result.ok is False
    assert result.error == "tool timeout after 0.2s"
    assert set(result.model_dump()) == _TOOL_RESULT_FIELDS
    # worker 自行退出、无泄漏：不计孤儿、不换代
    assert registry._orphans == 0
    assert registry._retired == []


# --------------------------------------------------------------------------- #
# 换代：硬超时后新池立即服务
# --------------------------------------------------------------------------- #


def test_pool_rotated_after_hard_timeout_and_serves_immediately(registry, caplog):
    """一次硬超时后：旧池进 _retired、calculator 立即成功、换代事件入库。"""
    caplog.set_level(logging.WARNING, logger="multimodal_agent_platform")
    timeout_result = registry.invoke("slow", {})
    assert timeout_result.error == "tool timeout after 0.2s"
    assert len(registry._retired) == 1

    fast = registry.invoke("calculator", {"expression": "1+2"})
    assert fast.ok is True
    assert fast.output == 3
    assert registry._orphans == 1

    events = [getattr(record, "event", None) for record in caplog.records]
    assert "tool_pool_rotated" in events


# --------------------------------------------------------------------------- #
# C4：孤儿上限 + 饱和拒绝
# --------------------------------------------------------------------------- #


def test_orphan_cap_rejects_ninth_invoke_after_eight_hard_timeouts(caplog):
    """C4：连续 8 次硬超时 → 第 9 次 invoke 立即返回饱和文案 + tool_orphan_capped。"""
    caplog.set_level(logging.WARNING, logger="multimodal_agent_platform")
    registry = _make_registry()
    try:
        for _ in range(8):
            result = registry.invoke("slow", {})
            assert result.error == "tool timeout after 0.2s"
        assert registry._orphans == 8
        assert len(registry._retired) == 8

        capped = registry.invoke("slow", {})
        assert capped.ok is False
        assert capped.error == "tool pool saturated: 8 orphaned workers (max 8)"
        assert capped.output is None
        assert set(capped.model_dump()) == _TOOL_RESULT_FIELDS
        # 饱和拒绝必须立即返回，不再等 0.2s 超时窗口
        assert capped.elapsed_ms < 100.0
        assert registry._orphans == 8  # 饱和拒绝不计新孤儿
    finally:
        registry.shutdown()

    events = [getattr(record, "event", None) for record in caplog.records]
    assert "tool_orphan_capped" in events
    assert events.count("tool_pool_rotated") == 8
