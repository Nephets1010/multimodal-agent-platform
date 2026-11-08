"""自动评测（Q9 / P1-4）：8 条自建样例，组合根直调 ``graph.run()``。

命中判定**只有两条**（ARCH §5.8）：
    ``hit = all(k in answer for k in expected_keywords)
            AND set(expected_tools) ⊆ set(actual_tools)``
``expected_answer_contains`` 仅是 schema 规定的样例元数据，**不参与判定**。
请求 ``samples`` 是数组、响应 ``samples`` 是数量数字；``actual_tools`` 必须是 list。
``python3 -m app.observability.evaluator`` 输出文本报告并落盘 ``data/eval_report.json``。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.agent.state import AgentState, make_trace_id
from app.observability.logging import get_logger
from app.schemas import EvalDetail, EvalResponse, EvalSample

if TYPE_CHECKING:
    from app.runtime import AppContext


class Evaluator:
    """逐样例复用组合根的 ``CompiledGraph.run()``，不做 HTTP 自请求。"""

    def __init__(self, ctx: "AppContext") -> None:
        self.ctx = ctx

    def load_samples(self, override: list[EvalSample] | None = None) -> list[EvalSample]:
        """读 ``samples/eval.jsonl``；显式传入数组时优先使用。"""
        if override is not None:
            return list(override)
        path = self.ctx.paths.eval_samples_path
        samples: list[EvalSample] = []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            get_logger("observability.evaluator").warning(
                "评测样例文件读取失败: %s",
                type(exc).__name__,
                extra={"event": "eval_samples_unreadable"},
            )
            return samples
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                samples.append(EvalSample.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValueError):
                continue
        return samples

    def _new_state(self, query: str) -> AgentState:
        return AgentState(
            trace_id=make_trace_id(query, "eval"),
            session_id="default",
            query=query,
            max_steps=int(self.ctx.settings.agent.max_steps),
            last_debug={"modalities": []},
        )

    def evaluate_one(self, sample: EvalSample) -> EvalDetail:
        """单条评测；``hit`` 严格按两条口径，``expected_answer_contains`` 不参与。"""
        started = time.perf_counter()
        final = self.ctx.graph.run(self._new_state(sample.query))
        latency_ms = (time.perf_counter() - started) * 1000.0

        answer = final.answer or ""
        actual_tools: list[str] = [call.name for call in final.tool_calls]
        keyword_hit = all(keyword in answer for keyword in sample.expected_keywords)
        tool_hit = set(sample.expected_tools).issubset(set(actual_tools))
        hit = bool(keyword_hit and tool_hit)

        return EvalDetail(
            hit=hit,
            query=sample.query,
            actual_tools=actual_tools,
            steps=int(final.steps),
            latency_ms=round(latency_ms, 3),
        )

    def evaluate(self, samples: list[EvalSample] | None = None) -> EvalResponse:
        """返回 6 字段齐备的 ``EvalResponse``（``samples`` 为数量数字）。"""
        items = self.load_samples(samples)
        details = [self.evaluate_one(sample) for sample in items]
        total = len(details)
        tool_hits = [
            set(sample.expected_tools).issubset(set(detail.actual_tools))
            for sample, detail in zip(items, details)
        ]
        if total == 0:
            return EvalResponse(
                hit_rate=0.0,
                tool_hit_rate=0.0,
                avg_steps=0.0,
                avg_latency_ms=0.0,
                samples=0,
                details=[],
            )
        return EvalResponse(
            hit_rate=round(sum(detail.hit for detail in details) / total, 6),
            tool_hit_rate=round(sum(tool_hits) / total, 6),
            avg_steps=round(sum(detail.steps for detail in details) / total, 6),
            avg_latency_ms=round(
                sum(detail.latency_ms for detail in details) / total, 6
            ),
            samples=total,
            details=details,
        )


def _main() -> None:
    """``python3 -m app.observability.evaluator`` 入口：文本报告 + 落盘（不改响应字段）。"""
    from app.runtime import build_context  # 局部导入，避免与组合根形成模块级循环

    ctx = build_context()
    response = ctx.evaluator.evaluate()

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "demo_mode": bool(ctx.settings.demo.enabled),
        "graph_backend": ctx.graph_backend,
        "fallback_flags": list(ctx.fallback_flags),
        **response.model_dump(mode="json"),
    }
    ctx.paths.eval_report_path.parent.mkdir(parents=True, exist_ok=True)
    ctx.paths.eval_report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("=== 多模态通用智能体开发平台 · 自动评测报告 ===")
    print(f"模式：DEMO_MODE={1 if ctx.settings.demo.enabled else 0} | 图后端：{ctx.graph_backend}")
    print(f"样例数：{response.samples}")
    for index, detail in enumerate(response.details, start=1):
        mark = "✓" if detail.hit else "✗"
        tools = ",".join(detail.actual_tools) or "-"
        print(
            f"  [{index:02d}] {mark} {detail.query} | tools={tools} "
            f"| steps={detail.steps} | {detail.latency_ms}ms"
        )
    print(
        f"命中率：{response.hit_rate:.4f} | 工具命中率：{response.tool_hit_rate:.4f} "
        f"| 平均步数：{response.avg_steps} | 平均延迟：{response.avg_latency_ms}ms"
    )
    print("说明：DEMO 指标只用于链路正确性与回归验证，不代表业务准确率。")
    print(f"报告已写入：{ctx.paths.eval_report_path}")

    ctx.tools.shutdown()
    ctx.tracer.close()


if __name__ == "__main__":
    _main()


__all__ = ["Evaluator"]
