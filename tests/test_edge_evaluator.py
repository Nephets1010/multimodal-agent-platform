"""QA-T10 · evaluator 分支覆盖（JSONL 损坏行 / 空样例 / 命中口径 / override）。

``app/observability/evaluator.py`` 三个公共方法此前从未被 tests 直接引用；
NEG-6 证明把 ``hit_rate`` 恒置 0 后 139 条仍全绿。本文件用组合根里的真实
Evaluator 做纯本地验证，不启动服务、不发网络请求、不写仓库 samples/。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas import EvalSample


def _write_samples(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_samples_skips_corrupt_and_empty_lines(ctx, monkeypatch, tmp_path: Path):
    target = tmp_path / "samples" / "eval.jsonl"
    valid = {
        "query": "计算 12*8 的结果",
        "expected_keywords": ["96"],
        "expected_tools": ["calculator"],
        "expected_answer_contains": [],
    }
    other = {
        "query": "介绍一下平台",
        "expected_keywords": [],
        "expected_tools": [],
        "expected_answer_contains": [],
    }
    _write_samples(
        target,
        [
            json.dumps(valid, ensure_ascii=False),
            "{broken json",
            "",
            "not-json-at-all",
            json.dumps(other, ensure_ascii=False),
        ],
    )
    monkeypatch.setattr(ctx.paths, "eval_samples_path", target)
    samples = ctx.evaluator.load_samples()
    assert [sample.query for sample in samples] == [
        "计算 12*8 的结果",
        "介绍一下平台",
    ]
    assert samples[0].expected_tools == ["calculator"]


def test_load_samples_override_bypasses_file(ctx, monkeypatch, tmp_path: Path):
    target = tmp_path / "samples" / "eval.jsonl"
    _write_samples(target, [json.dumps({"query": "from-file"})])
    monkeypatch.setattr(ctx.paths, "eval_samples_path", target)
    override = [EvalSample(query="from-override", expected_keywords=["x"])]
    assert [sample.query for sample in ctx.evaluator.load_samples(override)] == [
        "from-override"
    ]


def test_evaluate_empty_samples_returns_zeroed_six_fields(ctx):
    body = ctx.evaluator.evaluate([]).model_dump(mode="json")
    assert set(body) == {
        "hit_rate",
        "tool_hit_rate",
        "avg_steps",
        "avg_latency_ms",
        "samples",
        "details",
    }
    assert body["samples"] == 0
    assert body["details"] == []
    assert body["hit_rate"] == 0.0
    assert body["tool_hit_rate"] == 0.0
    assert body["avg_steps"] == 0.0
    assert body["avg_latency_ms"] == 0.0


def test_expected_answer_contains_does_not_affect_hit(ctx):
    """Q9：``expected_answer_contains`` 仅是元数据，不参与命中判定。"""
    sample = EvalSample(
        query="计算 12*8 的结果",
        expected_keywords=["96"],
        expected_tools=["calculator"],
        expected_answer_contains=["_绝对不会出现的字符串_"],
    )
    detail = ctx.evaluator.evaluate_one(sample)
    assert detail.hit is True
    assert "calculator" in detail.actual_tools


def test_evaluate_one_negative_paths(ctx):
    keyword_miss = ctx.evaluator.evaluate_one(
        EvalSample(
            query="计算 12*8 的结果",
            expected_keywords=["_不可能出现的关键词_"],
            expected_tools=["calculator"],
        )
    )
    assert keyword_miss.hit is False

    tool_miss = ctx.evaluator.evaluate_one(
        EvalSample(
            query="计算 12*8 的结果",
            expected_keywords=["96"],
            expected_tools=["calculator", "not_registered_tool"],
        )
    )
    assert tool_miss.hit is False
    assert tool_miss.actual_tools == ["calculator"]


def test_evaluate_tool_hit_rate_is_independent_of_keyword_hit(ctx):
    """tool_hit_rate 只看 expected_tools ⊆ actual_tools，与关键词命中解耦。"""
    samples = [
        EvalSample(
            query="计算 12*8 的结果",
            expected_keywords=["_不可能_"],
            expected_tools=["calculator"],
        )
    ]
    body = ctx.evaluator.evaluate(samples).model_dump(mode="json")
    assert body["samples"] == 1
    assert body["hit_rate"] == 0.0
    assert body["tool_hit_rate"] == 1.0
    assert body["details"][0]["actual_tools"] == ["calculator"]
