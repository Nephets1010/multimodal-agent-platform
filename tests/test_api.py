"""T04/T05 API 契约与边界回归：7 组端点、SSE 帧、trace、eval、DEMO 锁定、脱敏、上传护栏。"""

from __future__ import annotations

import json

import pytest

import app.config as config
from app.agent.state import AgentState, make_trace_id
from app.observability.logging import redact_snapshot, redact_text


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """模拟前端 parseFrame：按 ``\\n\\n`` 切帧，逐行读 event:/data: 并 JSON.parse。"""
    frames: list[tuple[str, dict]] = []
    for part in text.split("\n\n"):
        if not part.strip():
            continue
        event = "message"
        payload = ""
        for line in part.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                payload += line[5:].strip()
        frames.append((event, json.loads(payload) if payload else {}))
    return frames


# --------------------------------------------------------------------------- #
# 7 组端点契约
# --------------------------------------------------------------------------- #


def test_health_contract(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["demo_mode"] is True
    assert len(body["components"]) == 11
    assert body["index_chunks"] == body["components"]["index_chunks"]
    assert body["status"] in ("ok", "degraded", "error")
    assert body["version"] == "1.0.0"
    components = body["components"]
    # DEMO 下生效后端锁定，探测结果如实（探测 ≠ 启用）
    assert (components["graph"], components["encoder"], components["vector"], components["llm"]) == (
        "pure",
        "stub",
        "memory",
        "template",
    )
    # DEMO 下配置值==生效值，不附加 configured_backends，响应与既有契约完全一致
    assert "configured_backends" not in body


def test_map_prefixed_env_override_and_namespace_isolation(monkeypatch):
    """长格式必须带 MAP_ 前缀；裸长格式与宿主同名变量一律不得被误读。"""
    # 模拟宿主注入的无关同名变量（裸 <SECTION>__<KEY>）
    monkeypatch.setenv("SERVER__HOST", "10.9.9.9")
    monkeypatch.setenv("SERVER__PORT", "9999")
    monkeypatch.setenv("RETRIEVAL__DENSE_WEIGHT", "0.11")
    for name in (
        "HOST", "PORT", "MAP_SERVER__HOST", "MAP_SERVER__PORT",
        "MAP_RETRIEVAL__DENSE_WEIGHT",
    ):
        monkeypatch.delenv(name, raising=False)
    config.reset_settings_cache()
    baseline = config.get_settings()
    assert (baseline.server.host, baseline.server.port) == ("0.0.0.0", 8000)
    assert baseline.retrieval.dense_weight == 0.6

    # 项目前缀长格式生效
    monkeypatch.setenv("MAP_SERVER__HOST", "127.0.0.1")
    monkeypatch.setenv("MAP_SERVER__PORT", "8123")
    monkeypatch.setenv("MAP_RETRIEVAL__DENSE_WEIGHT", "0.7")
    config.reset_settings_cache()
    overridden = config.get_settings()
    assert (overridden.server.host, overridden.server.port) == ("127.0.0.1", 8123)
    assert overridden.retrieval.dense_weight == 0.7

    # 规格 §4.6 历史短别名保留且优先于 MAP_ 长格式
    monkeypatch.setenv("HOST", "192.0.2.1")
    config.reset_settings_cache()
    assert config.get_settings().server.host == "192.0.2.1"
    config.reset_settings_cache()


def test_health_reports_effective_backends_in_production(monkeypatch):
    """生产模式配置 api/chroma 但因依赖/Key 缺失降级：components 报生效值，
    顶层 configured_backends 报配置声明值。"""
    monkeypatch.setenv("DEMO_MODE", "0")
    monkeypatch.setenv("ENCODER_BACKEND", "api")
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")
    monkeypatch.setenv("LLM_BACKEND", "api")
    config.reset_settings_cache()

    from fastapi.testclient import TestClient

    from app.main import app
    from app.runtime import build_context

    production_ctx = build_context()
    previous = getattr(app.state, "ctx", None)
    app.state.ctx = production_ctx
    try:
        body = TestClient(app).get("/health").json()
        components = body["components"]
        assert (components["encoder"], components["vector"], components["llm"]) == (
            "stub", "memory", "template"
        )
        assert components["graph"] == "pure"
        configured = body["configured_backends"]
        assert configured["encoder"] == "api"
        assert configured["vector"] == "chroma"
        assert configured["llm"] == "api"
        assert body["status"] == "degraded"
    finally:
        if previous is None:
            try:
                del app.state.ctx
            except AttributeError:
                pass
        else:
            app.state.ctx = previous
        production_ctx.tools.shutdown()
        production_ctx.tracer.close()
        config.reset_settings_cache()


def test_ingest_frontend_formdata_without_text(client):
    """Q3：前端只 append files + source_tag，不 append text，不得 422。"""
    response = client.post(
        "/v1/ingest",
        files=[("files", ("webui.txt", b"frontend formdata text", "text/plain"))],
        data={"source_tag": "webui"},
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"chunks", "total"}
    assert body["total"] >= 1
    assert set(body["chunks"][0]) >= {"chunk_id", "source_id", "modality", "snippet"}


def test_ingest_text_field_only(client):
    response = client.post(
        "/v1/ingest", data={"text": "直接粘贴的文本内容", "source_tag": "webui"}
    )
    assert response.status_code == 200
    assert response.json()["total"] >= 1


def test_chat_non_stream_contract(client):
    response = client.post(
        "/v1/chat", json={"query": "计算 12*8 的结果", "stream": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 11
    assert "96" in body["answer"]
    assert body["demo_mode"] is True
    assert body["graph_backend"] == "pure"
    assert body["output_modality"] == "text"
    assert any(
        result["name"] == "calculator" and result["ok"] and "error" in result
        for result in body["tool_results"]
    )


def test_sse_frame_sequence_and_done_fields(client):
    """SSE 逐字节契约：单行 data、事件顺序、done 11 字段、与非流式字段集合一致。"""
    query = "介绍一下平台"
    streamed = client.post("/v1/chat", json={"query": query, "stream": True})
    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("text/event-stream")
    assert streamed.headers.get("x-accel-buffering") == "no"

    # 所有 data: 行必须是单行 JSON（禁止 indent 多行）
    for line in streamed.text.splitlines():
        if line.startswith("data:"):
            json.loads(line[5:].strip())

    frames = _parse_sse(streamed.text)
    names = [event for event, _ in frames]
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert names.count("meta") == 1 and names.count("done") == 1
    assert "step" in names and "token" in names
    last_step = max(index for index, name in enumerate(names) if name == "step")
    first_token = min(index for index, name in enumerate(names) if name == "token")
    assert last_step < first_token

    done_data = frames[-1][1]
    assert len(done_data) == 11
    tokens = "".join(data["delta"] for event, data in frames if event == "token")
    assert tokens == done_data["answer"]

    non_stream = client.post(
        "/v1/chat", json={"query": query, "stream": False}
    ).json()
    assert set(done_data) == set(non_stream)
    assert set(frames[0][1]) == {"trace_id", "backend"}
    assert all(
        set(data) == {"steps", "node", "next_node", "status", "last_observation"}
        for event, data in frames
        if event == "step"
    )


def test_trace_not_found_returns_200_empty(client):
    assert client.get("/v1/trace/not-exist").json() == {"events": [], "count": 0}


def test_trace_replay_after_chat(client):
    body = client.post(
        "/v1/chat", json={"query": "计算 12*8 的结果", "stream": False}
    ).json()
    replay = client.get(f"/v1/trace/{body['trace_id']}").json()
    assert replay["count"] >= body["steps"]
    assert all(
        {"event", "node", "steps", "status"} <= set(event) for event in replay["events"]
    )


def test_tools_contract(client):
    body = client.get("/v1/tools").json()
    assert len(body["tools"]) == 4
    assert all({"name", "description", "parameters"} <= set(tool) for tool in body["tools"])
    assert len(body["whitelist"]) == 4
    assert body["max_steps"] == 8
    assert body["tool_timeout_seconds"] == 3.0


def test_eval_contract(client):
    body = client.post("/v1/eval", json={}).json()
    assert set(body) == {
        "hit_rate",
        "tool_hit_rate",
        "avg_steps",
        "avg_latency_ms",
        "samples",
        "details",
    }
    # QA-T06：原断言仅检查 0<=hit_rate<=1，NEG-6 把 hit_rate 恒置 0 后仍全绿。
    # DEMO 为确定性 stub，8 条样例集指标必须逐项钉住。
    assert body["samples"] == 8
    assert len(body["details"]) == 8
    assert body["hit_rate"] == 1.0
    assert body["tool_hit_rate"] == 1.0
    assert body["avg_steps"] == 2.875
    assert all(isinstance(detail["actual_tools"], list) for detail in body["details"])
    assert all(detail["hit"] is True for detail in body["details"])


def test_eval_negative_keyword_marks_hit_false(client):
    """QA-T06：expected_keywords 未命中时 hit 必须为 False（负向判定路径）。"""
    body = client.post(
        "/v1/eval",
        json={
            "samples": [
                {
                    "query": "计算 12*8 的结果",
                    "expected_keywords": ["不可能出现的字符串_QA_T06"],
                    "expected_tools": ["calculator"],
                    "expected_answer_contains": [],
                }
            ]
        },
    ).json()
    assert body["samples"] == 1
    assert body["details"][0]["hit"] is False
    assert body["hit_rate"] == 0.0
    assert body["details"][0]["actual_tools"] == ["calculator"]


def test_eval_request_samples_is_array(client):
    """Q9 同名不同义：请求 samples 是数组，响应 samples 是数量数字。"""
    body = client.post(
        "/v1/eval",
        json={
            "samples": [
                {
                    "query": "计算 12*8 的结果",
                    "expected_keywords": ["96"],
                    "expected_tools": ["calculator"],
                    "expected_answer_contains": [],
                }
            ]
        },
    ).json()
    assert body["samples"] == 1
    assert body["details"][0]["hit"] is True


def test_static_routes_and_docs(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "多模态通用智能体开发平台" in index.text
    assert client.get("/ui/index.html").status_code == 200
    assert client.get("/docs").status_code == 200


# --------------------------------------------------------------------------- #
# DEMO 锁定 / 脱敏 / 可选依赖
# --------------------------------------------------------------------------- #


def test_demo_lock_even_with_api_key_configured(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("LLM_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ENCODER_BACKEND", "transformers")
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")
    config.reset_settings_cache()
    settings = config.get_settings()
    assert (settings.llm.backend, settings.encoder.backend, settings.vector_store.backend) == (
        "template",
        "stub",
        "memory",
    )
    config.reset_settings_cache()


def test_redaction_functions_and_traces(client, ctx):
    assert "sk-abcdef" not in redact_text("LLM_API_KEY=sk-abcdef", {"sk-abcdef"})
    assert "Bearer" not in redact_text("Authorization: Bearer secret-token", set())
    snapshot = redact_snapshot(
        {
            "api_key": "sk-secret",
            "query": "完整问题原文",
            "content": "上传文件正文",
            "node": "planner",
            "steps": 1,
        },
        set(),
    )
    assert snapshot["api_key"] != "sk-secret"
    assert snapshot["content"] != "上传文件正文"
    assert "length" in snapshot["query"]
    assert snapshot["node"] == "planner"

    client.post("/v1/chat", json={"query": "计算 12*8 的结果", "stream": False})
    trace_text = ctx.paths.trace_path.read_text(encoding="utf-8")
    assert "sk-" not in trace_text
    assert all(json.loads(line) for line in trace_text.splitlines() if line.strip())


def test_optional_dependency_probe_is_safe(monkeypatch):
    probes = config.probe_optional_dependencies()
    assert set(probes) == {
        "langgraph",
        "chromadb",
        "whisper",
        "cv2",
        "transformers",
        "openai",
    }
    assert all(value in ("native", "fallback") for value in probes.values())

    # 可选依赖全部缺失：find_spec 返回 None → 6 项全 fallback，服务不崩溃
    monkeypatch.setattr(config.importlib.util, "find_spec", lambda name: None)
    missing = config.probe_optional_dependencies()
    assert len(missing) == 6
    assert all(value == "fallback" for value in missing.values())

    # 探测本身抛 ImportError 时也安全降级
    def _boom(name):
        raise ImportError("simulated missing package")

    monkeypatch.setattr(config.importlib.util, "find_spec", _boom)
    degraded = config.probe_optional_dependencies()
    assert all(value == "fallback" for value in degraded.values())


# --------------------------------------------------------------------------- #
# 上传护栏与边界
# --------------------------------------------------------------------------- #


def test_upload_guards(client, ctx):
    bad_extension = client.post(
        "/v1/ingest",
        files=[("files", ("x.exe", b"MZ", "application/octet-stream"))],
        data={"source_tag": "webui"},
    )
    assert bad_extension.status_code == 400
    assert "不支持的扩展名" in bad_extension.json()["detail"]

    oversized = client.post(
        "/v1/ingest",
        files=[("files", ("big.txt", b"a" * (11 * 1024 * 1024), "text/plain"))],
        data={"source_tag": "webui"},
    )
    assert oversized.status_code == 400

    too_many = client.post(
        "/v1/ingest",
        files=[("files", (f"f{i}.txt", b"x", "text/plain")) for i in range(21)],
        data={"source_tag": "webui"},
    )
    assert too_many.status_code == 400

    traversal = client.post(
        "/v1/ingest",
        files=[("files", ("../../etc/passwd", b"x", "text/plain"))],
        data={"source_tag": "webui"},
    )
    assert traversal.status_code == 400

    assert list(ctx.paths.tmp_dir.glob("*")) == []  # finally 清理


def test_empty_and_oversized_query(client, ctx):
    empty = client.post("/v1/chat", json={"query": "   ", "stream": False})
    assert empty.status_code == 400 and "detail" in empty.json()

    oversized = client.post(
        "/v1/chat",
        json={"query": "x" * (ctx.settings.agent.max_query_chars + 1), "stream": False},
    )
    assert oversized.status_code == 400 and "detail" in oversized.json()


def test_invalid_json_body(client):
    response = client.post(
        "/v1/chat",
        content=b"{not json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code in (400, 422)
    assert "detail" in response.json()


def test_modalities_filter_and_session_passthrough(client):
    body = client.post(
        "/v1/chat",
        json={
            "query": "介绍一下平台",
            "stream": False,
            "modalities": ["text"],
            "session_id": "session-x",
        },
    ).json()
    assert len(body) == 11
    assert all(evidence["modality"] == "text" for evidence in body["evidences"])


def test_sse_client_disconnect_releases_cleanly(ctx):
    """断连：生成器被 close 后不抛异常、不残留半帧。"""
    state = AgentState(
        trace_id=make_trace_id("disconnect", "pytest"),
        session_id="pytest",
        query="介绍一下平台",
        max_steps=8,
        last_debug={"modalities": []},
    )
    generator = ctx.graph.stream_events(state)
    assert next(generator)[0] == "meta"
    generator.close()


def test_corrupted_modality_file_is_skipped_without_breaking_ingest(client):
    """单模态失败隔离：坏 PNG 被跳过，同批正常文本仍入库。"""
    response = client.post(
        "/v1/ingest",
        files=[
            ("files", ("broken.png", b"not a png", "image/png")),
            ("files", ("good.txt", b"healthy text", "text/plain")),
        ],
        data={"source_tag": "webui"},
    )
    assert response.status_code == 200
    assert response.json()["total"] >= 1
