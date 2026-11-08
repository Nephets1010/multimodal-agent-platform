"""QA 独立第二层验证 · API 边界与异常场景（NF-4 / P0-11 / P0-15）。

与既有 ``tests/test_api.py`` 不重复：本文件聚焦**真实契约边界**——空／超长／非法
JSON 输入、``modalities`` 缺省语义、trace 穿越字符、上传四类阈值与临时文件清理、
DEMO ``/health`` 响应形状、以及未预期异常绝不直出堆栈。

所有断言都以 PRD §4 / ARCHITECTURE §3.6、§5.4、§5.7 为判据，不依赖实现细节。
运行期产物由 ``conftest._demo_env`` 隔离到 ``tmp_path``，不污染仓库 ``data/``。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.config as config
from app.runtime import build_context

CHAT = "/v1/chat"
INGEST = "/v1/ingest"

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


@pytest.fixture
def edge_ctx(monkeypatch: pytest.MonkeyPatch):
    """独立组合根；与 conftest.ctx 分开，便于在装配前注入自定义环境变量。"""
    monkeypatch.setenv("DEMO_MODE", "1")
    config.reset_settings_cache()
    context = build_context()
    try:
        yield context
    finally:
        context.tools.shutdown()
        context.tracer.close()
        config.reset_settings_cache()


@pytest.fixture
def edge_client(edge_ctx):
    """复用同一个组合根；不带 ``with``，避免 lifespan 重复 shutdown。"""
    from app.main import app

    app.state.ctx = edge_ctx
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        if getattr(app.state, "ctx", None) is edge_ctx:
            del app.state.ctx


@pytest.fixture
def eval_cap_ctx(monkeypatch: pytest.MonkeyPatch):
    """TD-16 · A2 专用：``MAP_EVAL__MAX_SAMPLES=10`` 下装配独立组合根。"""
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("MAP_EVAL__MAX_SAMPLES", "10")
    config.reset_settings_cache()
    context = build_context()
    try:
        yield context
    finally:
        context.tools.shutdown()
        context.tracer.close()
        config.reset_settings_cache()


@pytest.fixture
def eval_cap_client(eval_cap_ctx):
    from app.main import app

    app.state.ctx = eval_cap_ctx
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        if getattr(app.state, "ctx", None) is eval_cap_ctx:
            del app.state.ctx


# --------------------------------------------------------------------------- #
# 输入边界
# --------------------------------------------------------------------------- #


class TestChatInputBoundary:
    def test_empty_query_returns_400_with_readable_detail(self, edge_client):
        response = edge_client.post(CHAT, json={"query": "   ", "stream": False})
        assert response.status_code == 400
        assert response.json() == {"detail": "query 不能为空"}

    def test_oversized_query_returns_400(self, edge_client, edge_ctx):
        limit = int(edge_ctx.settings.agent.max_query_chars)
        response = edge_client.post(CHAT, json={"query": "x" * (limit + 1), "stream": False})
        assert response.status_code == 400
        assert "长度超过上限" in response.json()["detail"]

    def test_query_at_exact_limit_is_accepted(self, edge_client, edge_ctx):
        limit = int(edge_ctx.settings.agent.max_query_chars)
        response = edge_client.post(CHAT, json={"query": "x" * limit, "stream": False})
        assert response.status_code == 200
        assert set(response.json()) == _UNIFIED_FIELDS

    def test_invalid_json_returns_422_without_stack(self, edge_client):
        response = edge_client.post(
            CHAT, content="{invalid", headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422
        body = response.json()
        assert set(body) == {"detail"}
        assert "请求参数不合法" in body["detail"]
        assert "Traceback" not in response.text
        assert "File \"" not in response.text

    def test_modalities_omitted_is_equivalent_to_empty_array(self, edge_client):
        omitted = edge_client.post(
            CHAT, json={"query": "介绍一下平台", "stream": False}
        ).json()
        empty = edge_client.post(
            CHAT, json={"query": "介绍一下平台", "stream": False, "modalities": []}
        ).json()
        assert [item["chunk_id"] for item in omitted["evidences"]] == [
            item["chunk_id"] for item in empty["evidences"]
        ]
        assert set(omitted) == _UNIFIED_FIELDS == set(empty)

    def test_unknown_modality_is_filtered_without_crashing(self, edge_client):
        response = edge_client.post(
            CHAT,
            json={
                "query": "介绍一下平台",
                "stream": False,
                "modalities": ["not_a_modality"],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body) == _UNIFIED_FIELDS
        assert body["evidences"] == []
        assert body["answer"]


# --------------------------------------------------------------------------- #
# 轨迹回放边界
# --------------------------------------------------------------------------- #


class TestTraceBoundary:
    def test_missing_trace_returns_http_200_empty_set(self, edge_client):
        response = edge_client.get("/v1/trace/definitely-not-exist")
        assert response.status_code == 200
        assert response.json() == {"events": [], "count": 0}

    @pytest.mark.parametrize(
        "trace_id",
        [
            "..%2F..%2Fetc%2Fpasswd",
            "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
            "....//....//evil",
            "..%5c..%5cwindows%5csystem32",
        ],
    )
    def test_path_traversal_like_trace_id_never_leaks_files(self, edge_client, trace_id):
        """含路径穿越字符的 trace_id：不得读取任意文件、不得 500、不得回显路径内容。"""
        response = edge_client.get("/v1/trace/" + trace_id)
        assert response.status_code in (200, 404)
        text = response.text
        assert "root:" not in text
        assert "system32" not in text
        assert "Traceback" not in text
        if response.status_code == 200:
            assert response.json() == {"events": [], "count": 0}

    def test_replay_after_chat_is_ordered_and_counted(self, edge_client):
        created = edge_client.post(
            CHAT, json={"query": "计算 12*8 的结果", "stream": False}
        ).json()
        response = edge_client.get("/v1/trace/" + created["trace_id"])
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == len(body["events"]) >= created["steps"]
        steps = [event["steps"] for event in body["events"]]
        assert steps == sorted(steps)
        for event in body["events"]:
            assert {"event", "node", "steps", "status"} <= set(event)


# --------------------------------------------------------------------------- #
# 上传护栏（Q3 / NF-6）
# --------------------------------------------------------------------------- #


class TestUploadBoundary:
    def test_unsupported_extension_returns_400(self, edge_client):
        response = edge_client.post(
            INGEST, files={"files": ("evil.exe", b"MZ", "application/octet-stream")}
        )
        assert response.status_code == 400
        assert "不支持的扩展名" in response.json()["detail"]

    def test_single_file_over_10mib_is_rejected(self, edge_client, edge_ctx):
        cap = int(edge_ctx.settings.ingest.max_file_bytes)
        assert cap == 10 * 1024 * 1024
        response = edge_client.post(
            INGEST, files={"files": ("big.txt", b"x" * (cap + 1), "text/plain")}
        )
        assert response.status_code == 400
        assert "单文件上限" in response.json()["detail"]

    def test_more_than_20_files_is_rejected(self, edge_client, edge_ctx):
        cap = int(edge_ctx.settings.ingest.max_files)
        assert cap == 20
        files = [
            ("files", (f"f{i}.txt", b"hi", "text/plain")) for i in range(cap + 1)
        ]
        response = edge_client.post(INGEST, files=files)
        assert response.status_code == 400
        assert "最多上传" in response.json()["detail"]

    def test_total_over_cap_is_rejected_and_default_is_50mib(self, edge_client, edge_ctx):
        """默认阈值 50 MiB 由配置读取；用缩小阈值快速验证累计判定逻辑不漏判。"""
        assert int(edge_ctx.settings.ingest.max_total_bytes) == 50 * 1024 * 1024
        edge_ctx.settings.ingest.max_total_bytes = 100
        try:
            files = [
                ("files", (f"f{i}.txt", b"x" * 60, "text/plain")) for i in range(3)
            ]
            response = edge_client.post(INGEST, files=files)
            assert response.status_code == 400
            assert "总量超过上限" in response.json()["detail"]
        finally:
            edge_ctx.settings.ingest.max_total_bytes = 50 * 1024 * 1024

    def test_path_traversal_filename_is_sanitized(self, edge_client):
        response = edge_client.post(
            INGEST, files={"files": ("../../evil.txt", b"qa sanitize", "text/plain")}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        source_id = body["chunks"][0]["source_id"]
        assert ".." not in source_id
        assert "/" not in source_id
        assert source_id.endswith("evil.txt")

    @pytest.mark.parametrize("name", ["..%2f..%2fevil.txt", ".hidden.txt", ".."])
    def test_unsafe_names_are_rejected(self, edge_client, name):
        response = edge_client.post(
            INGEST, files={"files": (name, b"qa", "text/plain")}
        )
        assert response.status_code == 400
        assert "detail" in response.json()

    def test_tmp_dir_has_no_residue_after_success_and_after_failure(
        self, edge_client, edge_ctx
    ):
        tmp_dir = config.resolve_paths().tmp_dir
        edge_client.post(INGEST, files={"files": ("ok.txt", b"hello", "text/plain")})
        edge_client.post(INGEST, files={"files": ("bad.exe", b"MZ", "application/octet-stream")})
        edge_client.post(
            INGEST, files={"files": ("broken.png", b"not a png", "image/png")}
        )
        leftovers = [path for path in tmp_dir.iterdir() if path.is_file()]
        assert leftovers == [], f"临时文件未清理：{leftovers}"

    def test_frontend_formdata_without_text_field_still_works(self, edge_client):
        """前端仅在 text 非空时 append；缺省不得 422。"""
        response = edge_client.post(
            INGEST, files={"files": ("a.txt", b"frontend", "text/plain")}
        )
        assert response.status_code == 200
        assert response.json()["total"] >= 1


# --------------------------------------------------------------------------- #
# 健康 / 异常出口
# --------------------------------------------------------------------------- #


class TestHealthAndExceptionBoundary:
    def test_demo_health_shape_is_stable(self, edge_client):
        body = edge_client.get("/health").json()
        assert body["demo_mode"] is True
        assert "configured_backends" not in body
        assert body["index_chunks"] == body["components"]["index_chunks"]
        assert len(body["components"]) == 11
        assert body["components"]["graph"] == "pure"
        assert body["components"]["encoder"] == "stub"
        assert body["components"]["vector"] == "memory"
        assert body["components"]["llm"] == "template"

    def test_unhandled_exception_response_has_no_stack_or_secret(self, edge_ctx, monkeypatch):
        """强制触发 500，验证全局异常处理器只回可读短消息。"""
        from app.main import app

        def _boom(*_args: Any, **_kwargs: Any):
            raise RuntimeError("secret-internal-detail sk-should-not-leak")

        monkeypatch.setattr(edge_ctx.graph, "run", _boom)
        app.state.ctx = edge_ctx
        client = TestClient(app, raise_server_exceptions=False)
        try:
            response = client.post(CHAT, json={"query": "触发异常", "stream": False})
            assert response.status_code == 500
            body = response.json()
            assert set(body) == {"detail"}
            assert body["detail"] == "内部错误，请查看服务端日志"
            for marker in ("Traceback", "RuntimeError", "secret-internal-detail", "sk-should-not-leak"):
                assert marker not in response.text
        finally:
            client.close()
            if getattr(app.state, "ctx", None) is edge_ctx:
                del app.state.ctx

    def test_sse_done_carries_exact_11_fields_and_tokens_match(self, edge_client):
        response = edge_client.post(CHAT, json={"query": "介绍一下平台", "stream": True})
        assert response.status_code == 200
        frames = [frame for frame in response.text.split("\n\n") if frame.strip()]
        assert response.text.endswith("\n\n")
        parsed: list[tuple[str, dict[str, Any]]] = []
        for frame in frames:
            lines = frame.split("\n")
            assert len(lines) == 2
            assert lines[0].startswith("event: ")
            assert lines[1].startswith("data: ")
            payload = lines[1][6:]
            assert "\n" not in payload
            parsed.append((lines[0][7:], json.loads(payload)))
        names = [name for name, _ in parsed]
        assert names[0] == "meta" and names[-1] == "done"
        assert names.count("done") == 1
        assert names.count("meta") == 1
        phases = [name for index, name in enumerate(names) if index == 0 or names[index - 1] != name]
        assert phases == ["meta", "step", "token", "done"]
        done = parsed[-1][1]
        assert set(done) == _UNIFIED_FIELDS
        tokens = "".join(data["delta"] for name, data in parsed if name == "token")
        assert tokens == done["answer"]
        assert parsed[0][1]["trace_id"] == done["trace_id"]

    def test_sse_disconnect_via_streaming_response(self, edge_client, caplog):
        """QA-T02：routes 级 SSE 断连保护必须有回归守护。

        NEG-2 证明把 ``routes._generate()`` 的 try/except/finally 整段换成裸
        ``for...yield`` 后 139 条仍全绿（既有断连用例只 close 了 graph 层生成器）。
        这里用真实 ``StreamingResponse`` 读到第一帧就断开，断言断连/收尾日志出现，
        且不抛异常、不残留半帧；不断言异常路径日志条数（工程师补了 exc_info）。
        """
        caplog.set_level(logging.INFO, logger="multimodal_agent_platform")
        with edge_client.stream(
            "POST", CHAT, json={"query": "介绍一下平台", "stream": True}
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            lines = response.iter_lines()
            assert next(lines) == "event: meta"
            # 不读完就退出 with：触发 GeneratorExit → routes._generate 断连分支

        # 退出 with 只完成「客户端侧」关闭；生成器的 finally 在工作线程中异步执行，
        # 全量套件负载下可能晚于断言。这里做有界轮询（上限 2s），判据不变：
        # 收尾日志必须出现，只是不再假定它与 with 退出处于同一时刻。
        deadline = time.monotonic() + 2.0
        events: list[Any] = []
        while time.monotonic() < deadline:
            events = [getattr(record, "event", None) for record in caplog.records]
            if "sse_client_disconnected" in events or "sse_completed" in events:
                break
            time.sleep(0.01)
        assert "sse_client_disconnected" in events or "sse_completed" in events, (
            f"断连后未出现收尾日志：{events}"
        )


class TestIdempotency:
    """QA-T17：重复调用不得改变业务结果或索引状态。"""

    def test_duplicate_ingest_does_not_grow_index(self, edge_client, edge_ctx):
        payload = {"files": ("same.txt", b"idempotent content", "text/plain")}
        first = edge_client.post(INGEST, files=payload)
        count_after_first = edge_ctx.index.count()
        second = edge_client.post(INGEST, files=payload)
        assert first.status_code == second.status_code == 200
        assert first.json()["total"] == second.json()["total"]
        assert [c["chunk_id"] for c in first.json()["chunks"]] == [
            c["chunk_id"] for c in second.json()["chunks"]
        ]
        assert edge_ctx.index.count() == count_after_first

    def test_repeated_chat_has_stable_contract(self, edge_client):
        body = {"query": "计算 12*8 的结果", "stream": False}
        first = edge_client.post(CHAT, json=body)
        second = edge_client.post(CHAT, json=body)
        assert first.status_code == second.status_code == 200
        assert set(first.json()) == _UNIFIED_FIELDS == set(second.json())
        assert first.json()["steps"] == second.json()["steps"]
        assert "96" in first.json()["answer"] and "96" in second.json()["answer"]

    def test_repeated_eval_is_deterministic(self, edge_client):
        first = edge_client.post("/v1/eval", json={}).json()
        second = edge_client.post("/v1/eval", json={}).json()
        assert set(first) == set(second)
        assert first["samples"] == second["samples"] == 8
        assert first["hit_rate"] == second["hit_rate"]
        assert first["tool_hit_rate"] == second["tool_hit_rate"]
        assert first["avg_steps"] == second["avg_steps"]


# --------------------------------------------------------------------------- #
# TD-16 · A1/A2/A3：/v1/eval 显式样本数护栏
# --------------------------------------------------------------------------- #


def _eval_payload(count: int) -> dict[str, Any]:
    """构造 ``count`` 条显式样本；关键词留空以聚焦护栏行为而非命中判定。"""
    return {
        "samples": [
            {"query": f"介绍一下平台 {index}", "expected_keywords": []}
            for index in range(count)
        ]
    }


class TestEvalSampleGuard:
    def test_default_over_limit_returns_400_with_counts(self, edge_client, edge_ctx):
        """A1：默认上限 100，101 样本 → 400 且 detail 同时含当前数与上限。"""
        limit = int(edge_ctx.settings.eval.max_samples)
        assert limit == 100
        response = edge_client.post("/v1/eval", json=_eval_payload(limit + 1))
        assert response.status_code == 400
        body = response.json()
        assert set(body) == {"detail"}
        assert str(limit + 1) in body["detail"]
        assert str(limit) in body["detail"]

    def test_at_exact_limit_returns_200(self, edge_client):
        """A1：恰好 100 样本 → 200，响应 samples 为数量数字。"""
        response = edge_client.post("/v1/eval", json=_eval_payload(100))
        assert response.status_code == 200
        body = response.json()
        assert body["samples"] == 100
        assert len(body["details"]) == 100

    def test_env_override_lower_limit(self, eval_cap_client):
        """A2：``MAP_EVAL__MAX_SAMPLES=10`` 下 11 样本 → 400、10 样本 → 200。"""
        response = eval_cap_client.post("/v1/eval", json=_eval_payload(11))
        assert response.status_code == 400
        body = response.json()
        assert "11" in body["detail"] and "10" in body["detail"]

        ok = eval_cap_client.post("/v1/eval", json=_eval_payload(10))
        assert ok.status_code == 200
        assert ok.json()["samples"] == 10

    def test_empty_body_uses_builtin_samples(self, edge_client):
        """A3：``POST /v1/eval {}`` → 200 且内置 8 样本 hit_rate=1.0 不回归。"""
        response = edge_client.post("/v1/eval", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["samples"] == 8
        assert body["hit_rate"] == 1.0
