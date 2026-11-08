"""第 3 批 · 本轮源码修复的定向回归（全部按「修复后行为」断言）。

覆盖 A-01 并发 search+add、A-02 原子写中断、BF-01 done 轨迹时序、
TD-01 超长文件名、TD-02 非有限 float、TD-07 脱敏词边界、
TD-11 流式 replay、TD-12 编码器确定性。

所有临时产物走 ``tmp_path``（conftest 已把 data/ 重定向），不污染仓库；
并发用例用 Event 同步 + join，规模保守，不依赖网络/编解码器/时间/随机数。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from pytest import MonkeyPatch

import app.config as config
from app.agent.state import AgentState, make_trace_id
from app.observability.logging import redact_text
from app.rag.encoder import StubEncoder
from app.rag.store import InMemoryVectorStore
from app.schemas import ConfigError, ModalityChunk


def _chunk(chunk_id: str, content: str = "qa regression doc") -> ModalityChunk:
    return ModalityChunk(
        chunk_id=chunk_id,
        source_id="qa:regression",
        modality="text",
        content=content,
        metadata={},
    )


# --------------------------------------------------------------------------- #
# A-01：并发 search + add 不得抛 "dictionary changed size during iteration"
# --------------------------------------------------------------------------- #


def test_concurrent_search_and_add_never_raises(ctx):
    store = InMemoryVectorStore(ctx.settings, ctx.paths)
    vector = ctx.encoder.encode("QA concurrency seed")
    base = [_chunk(f"chk_base_{i:03d}") for i in range(200)]
    store.add(base, [vector] * len(base))
    assert store.count() == 200

    errors: list[BaseException] = []
    start = threading.Event()

    def reader() -> None:
        start.wait(timeout=5)
        try:
            for _ in range(300):
                store.search(vector, 5, [])
        except BaseException as exc:  # noqa: BLE001 - 收集线程内任何异常
            errors.append(exc)

    def writer() -> None:
        start.wait(timeout=5)
        try:
            for i in range(400):
                store.add([_chunk(f"chk_new_{i:03d}")], [vector])
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    reader_thread = threading.Thread(target=reader, name="qa-reader")
    writer_thread = threading.Thread(target=writer, name="qa-writer")
    reader_thread.start()
    writer_thread.start()
    start.set()
    reader_thread.join(timeout=30)
    writer_thread.join(timeout=30)
    assert not reader_thread.is_alive() and not writer_thread.is_alive(), "线程未在 30s 内结束"
    assert errors == [], f"并发期间出现异常：{errors[:2]}"
    assert store.count() == 600


# --------------------------------------------------------------------------- #
# A-02：原子写中断后目标文件仍是上一次合法 JSON
# --------------------------------------------------------------------------- #


def test_persist_interruption_keeps_last_valid_index(ctx):
    store = InMemoryVectorStore(ctx.settings, ctx.paths)
    vector = [1.0, 2.0]
    store.add([_chunk("chk_v1")], [vector])
    store.persist()
    original = ctx.paths.index_path.read_text(encoding="utf-8")
    assert json.loads(original)["version"] == 1

    store.add([_chunk("chk_v2")], [vector])

    def _fail_replace(self, target):  # noqa: ANN001
        raise OSError("simulated atomic replace failure")

    patch = MonkeyPatch()
    try:
        patch.setattr(Path, "replace", _fail_replace)
        with pytest.raises(OSError):
            store.persist()
    finally:
        patch.undo()

    after = ctx.paths.index_path.read_text(encoding="utf-8")
    assert after == original, "中断后目标文件被改写"
    assert json.loads(after)["version"] == 1
    assert [item["chunk_id"] for item in json.loads(after)["chunks"]] == ["chk_v1"]
    assert not Path(str(ctx.paths.index_path) + ".tmp").exists(), "临时文件未清理"


# --------------------------------------------------------------------------- #
# BF-01：done 帧之前必须已落盘 done 轨迹
# --------------------------------------------------------------------------- #


def test_done_trace_written_before_done_frame(ctx):
    state = AgentState(
        trace_id=make_trace_id("bf01", "qa"),
        session_id="qa",
        query="介绍一下平台",
        max_steps=8,
        last_debug={"modalities": []},
    )
    stream = ctx.graph.stream_events(state)
    names: list[str] = []
    for name, _data in stream:
        names.append(name)
        if name == "done":
            break  # 模拟客户端收到 done 立即断连
    stream.close()
    assert names[-1] == "done"

    events = ctx.tracer.replay(state.trace_id)
    assert events, "必须落盘轨迹"
    assert events[-1]["event"] == "done", [item["event"] for item in events]


# --------------------------------------------------------------------------- #
# TD-01：超长文件名 400 + 可读 detail；正常文件名 200
# --------------------------------------------------------------------------- #


def test_overlong_filename_returns_400_and_normal_still_works(client):
    overlong = "a" * 125 + ".txt"
    assert len(overlong) == 129
    rejected = client.post(
        "/v1/ingest",
        files=[("files", (overlong, b"qa", "text/plain"))],
    )
    assert rejected.status_code == 400
    assert "文件名" in rejected.json()["detail"]

    accepted = client.post(
        "/v1/ingest",
        files=[("files", ("ok.txt", b"qa", "text/plain"))],
    )
    assert accepted.status_code == 200


# --------------------------------------------------------------------------- #
# TD-02：float 配置拒绝 nan / inf / 1e400，0.7 仍生效
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "1e400"])
def test_non_finite_float_config_is_rejected(monkeypatch, bad):
    monkeypatch.setenv("MAP_RETRIEVAL__DENSE_WEIGHT", bad)
    config.reset_settings_cache()
    with pytest.raises(ConfigError) as raised:
        config.get_settings()
    assert "dense_weight" in str(raised.value) or "有限" in str(raised.value)
    config.reset_settings_cache()


def test_valid_float_config_still_applies(monkeypatch):
    monkeypatch.setenv("MAP_RETRIEVAL__DENSE_WEIGHT", "0.7")
    config.reset_settings_cache()
    assert config.get_settings().retrieval.dense_weight == 0.7
    config.reset_settings_cache()


# --------------------------------------------------------------------------- #
# TD-07：sk- 词边界后普通词不被误吞，真实凭据脱敏强度不削弱
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "plain",
    [
        "task-list processed 10 items",
        "mask-value ok",
        "disk-space available",
        "ask-question flow",
    ],
)
def test_redact_text_does_not_swallow_plain_words(plain):
    assert redact_text(plain) == plain


@pytest.mark.parametrize(
    "credential",
    [
        "Authorization: Bearer abc.def",
        "Bearer\ttoken123",
        "SK-THISISALONGSECRETKEY",
        "sk-should-not-leak",
    ],
)
def test_redact_text_still_masks_real_credentials(credential):
    assert "***REDACTED***" in redact_text(credential)


# --------------------------------------------------------------------------- #
# TD-08/09：message 截断上限，traceback 单独放宽
# --------------------------------------------------------------------------- #


def test_redact_text_truncates_long_message():
    result = redact_text("x" * 600)
    assert len(result) <= 524
    assert result.endswith("…(truncated)")


# --------------------------------------------------------------------------- #
# TD-11：流式 replay 跳过损坏行，顺序/字段不变
# --------------------------------------------------------------------------- #


def test_replay_streaming_skips_corrupt_lines(ctx):
    path = ctx.paths.trace_path
    path.write_text(
        '{"trace_id":"tr_s","event":"step","node":"planner","steps":1,"status":"ok"}\n'
        "{BROKEN JSON\n"
        "\n"
        '{"trace_id":"tr_s","event":"done","node":"reflector","steps":3,"status":"ok"}\n',
        encoding="utf-8",
    )
    events = ctx.tracer.replay("tr_s")
    assert [item["event"] for item in events] == ["step", "done"]
    assert all({"event", "node", "steps", "status"} <= set(item) for item in events)


# --------------------------------------------------------------------------- #
# TD-12：lru_cache 后编码仍逐位确定
# --------------------------------------------------------------------------- #


def test_stub_encoder_is_bitwise_deterministic_across_instances():
    text = "混合检索与确定性编码 QA-TD12"
    first = StubEncoder().encode(text)
    second = StubEncoder().encode(text)
    third = StubEncoder().encode(text)
    assert first == second == third
    assert len(first) == 256
