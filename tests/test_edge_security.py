"""QA 独立第二层验证 · 安全、脱敏与配置健壮性（NF-2 / NF-6 / P0-15 / DEMO 十条红线）。

覆盖：受限 AST 计算器拒绝集、工具白名单与超时、DEMO 锁定 + 禁止外部 socket、
可选依赖全缺失降级、假密钥三出口零泄漏、静态源码安全扫描、既有文件字节守护，
以及「仓库自带 ``.env.example`` 复制为 ``.env`` 后必须能启动」的 BUG1 回归。

注意：本文件只断言 PRD / ARCHITECTURE 规定的**行为**，不绑定具体实现细节。
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import socket
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.config as config
from app.agent.tools import BaseTool, safe_calculate
from app.runtime import build_context
from app.schemas import ConfigError

FAKE_KEY = "sk-should-not-leak"
_PROTECTED_SHA256 = {
    "requirements.txt": "e5cfccf8a56bef25938b6f8b4457c5e4b616b28cdf4741f5fe025cf25e281fca",
    "samples/knowledge.txt": "3f101b4d56354790d81aa64e5b8264c775601b1532dfe69b9dd5220ca80f5cd1",
    "web/index.html": "46d5c74a8d207efc948702caf6b09fb552781551a6463b56d9cf4626ec8ae135",
}


@pytest.fixture
def edge_ctx(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    config.reset_settings_cache()
    context = build_context()
    try:
        yield context
    finally:
        context.tools.shutdown()
        context.tracer.close()
        config.reset_settings_cache()


def _make_client(context) -> TestClient:
    from app.main import app

    app.state.ctx = context
    return TestClient(app)


# --------------------------------------------------------------------------- #
# 受限 AST 计算器（NF-6）
# --------------------------------------------------------------------------- #


class TestCalculatorAstGuard:
    @pytest.mark.parametrize(
        "expression",
        [
            "__import__('os')",
            "().__class__",
            "1/0",
            "1<<2",
            "1&2",
            "1|2",
            "1<2",
            "1==1",
            "[1,2][0]",
            "lambda: 1",
            "abs(-2)",
            "2**100",
            "1 if 1 else 2",
            "open('/etc/passwd')",
            "'x' * 3",
        ],
    )
    def test_dangerous_expression_is_rejected(self, expression):
        with pytest.raises(Exception) as caught:
            safe_calculate(expression)
        assert not isinstance(caught.value, (SystemExit, KeyboardInterrupt))

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("12*8", 96),
            ("100/4", 25.0),
            ("1 + 2 * 3", 7),
            ("2**8", 256),
            ("-3+5", 2),
            ("7//2", 3),
            ("7%3", 1),
        ],
    )
    def test_safe_arithmetic_is_correct(self, expression, expected):
        assert safe_calculate(expression) == expected

    def test_oversized_expression_is_rejected_without_crash(self):
        with pytest.raises(ValueError):
            safe_calculate("1+" * 200 + "1")

    @pytest.mark.parametrize(
        "expression", ["__import__('os')", "1/0", "().__class__", "1<<2", "1<2"]
    )
    def test_registry_turns_rejection_into_structured_failure(self, edge_ctx, expression):
        result = edge_ctx.tools.invoke("calculator", {"expression": expression})
        dumped = result.model_dump()
        assert set(dumped) == {"name", "ok", "elapsed_ms", "output", "error"}
        assert dumped["ok"] is False
        assert dumped["name"] == "calculator"
        assert dumped["output"] is None
        assert dumped["error"]

    def test_unregistered_tool_is_rejected(self, edge_ctx):
        result = edge_ctx.tools.invoke("not_in_whitelist", {"expression": "1+1"})
        assert result.ok is False
        assert "whitelist" in str(result.error)
        assert set(result.model_dump()) == {
            "name",
            "ok",
            "elapsed_ms",
            "output",
            "error",
        }

    def test_tool_timeout_returns_structured_failure_and_chain_continues(
        self, edge_ctx, monkeypatch
    ):
        """把超时压到 0.08s 保持测试快速；超时后线程池仍有可用 worker，链路继续。"""
        release = threading.Event()

        class SlowTool(BaseTool):
            name = "qa_slow_tool"
            description = "QA timeout probe"
            parameters: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

            def run(self, **_kwargs: Any) -> Any:
                release.wait(5)
                return "released"

        monkeypatch.setattr(edge_ctx.tools, "_timeout", 0.15)
        edge_ctx.tools.register(SlowTool())
        try:
            timed = edge_ctx.tools.invoke("qa_slow_tool", {})
            assert timed.ok is False
            assert "timeout" in str(timed.error)
            # 放宽下界以规避调度抖动，上界确保确实没等到 release.wait(5) 结束
            assert 80 <= timed.elapsed_ms < 4000
            following = edge_ctx.tools.invoke("calculator", {"expression": "12*8"})
            assert following.ok is True and following.output == 96
        finally:
            release.set()


# --------------------------------------------------------------------------- #
# DEMO 锁定 / 零联网
# --------------------------------------------------------------------------- #


class TestDemoLockAndNetworkIsolation:
    def test_demo_lock_with_api_key_and_no_external_socket(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """禁用所有非回环 socket 连接，并监视 httpx.post；DEMO 全链路必须 0 外部请求。"""
        monkeypatch.setenv("DEMO_MODE", "1")
        monkeypatch.setenv("LLM_API_KEY", FAKE_KEY)
        monkeypatch.setenv("LLM_BASE_URL", "https://evil.invalid/v1")
        monkeypatch.setenv("LLM_BACKEND", "api")
        monkeypatch.setenv("ENCODER_BACKEND", "api")
        monkeypatch.setenv("VECTOR_BACKEND", "chroma")
        monkeypatch.setitem(config._PATH_OVERRIDES, "data_dir", tmp_path / "data")
        monkeypatch.setitem(config._PATH_OVERRIDES, "tmp_dir", tmp_path / "data" / "tmp")
        config.reset_settings_cache()

        settings = config.get_settings()
        assert settings.demo.enabled is True
        assert (settings.llm.backend, settings.encoder.backend, settings.vector_store.backend) == (
            "template",
            "stub",
            "memory",
        )

        import httpx

        external_posts: list[Any] = []
        original_post = httpx.post

        def _spy_post(*args: Any, **kwargs: Any):
            external_posts.append(args)
            raise AssertionError("DEMO 下禁止 httpx.post 外部请求")

        def _is_loopback(address: Any) -> bool:
            try:
                host = str(address[0])
            except (TypeError, IndexError, KeyError):
                return True
            return host in ("127.0.0.1", "::1", "localhost") or host.startswith("127.")

        original_connect = socket.socket.connect

        def _guarded_connect(self, address, *args: Any, **kwargs: Any):
            # TestClient 的 anyio 事件循环会用本地 socketpair（127.0.0.1），必须放行。
            if not _is_loopback(address):
                raise AssertionError(f"DEMO 下禁止外部 socket 连接：{address!r}")
            return original_connect(self, address, *args, **kwargs)

        monkeypatch.setattr(httpx, "post", _spy_post)
        monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
        context = None
        try:
            context = build_context()
            assert context.graph_backend == "pure"
            assert context.effective_backends == {
                "llm": "template",
                "encoder": "stub",
                "vector": "memory",
                "graph": "pure",
            }
            test_client = _make_client(context)
            try:
                assert test_client.post(
                    "/v1/chat", json={"query": "计算 12*8 的结果", "stream": False}
                ).json()["answer"].find("96") >= 0
                assert test_client.post(
                    "/v1/chat", json={"query": "介绍一下平台", "stream": True}
                ).status_code == 200
                assert test_client.post("/v1/eval", json={}).json()["samples"] == 8
                assert test_client.post(
                    "/v1/ingest", files={"files": ("a.txt", b"hello", "text/plain")}
                ).status_code == 200
                assert "configured_backends" not in test_client.get("/health").json()
            finally:
                test_client.close()
            assert external_posts == []
        finally:
            if context is not None:
                context.tools.shutdown()
                context.tracer.close()
            config.reset_settings_cache()

    def test_all_optional_dependencies_missing_marks_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        monkeypatch.setattr(importlib.util, "find_spec", lambda *a, **k: None)
        monkeypatch.setitem(config._PATH_OVERRIDES, "data_dir", tmp_path / "data")
        monkeypatch.setitem(config._PATH_OVERRIDES, "tmp_dir", tmp_path / "data" / "tmp")
        config.reset_settings_cache()
        context = None
        try:
            context = build_context()
            test_client = _make_client(context)
            try:
                health = test_client.get("/health").json()
                for key in (
                    "langgraph",
                    "chromadb",
                    "whisper",
                    "cv2",
                    "transformers",
                    "openai",
                ):
                    assert health["components"][key] == "fallback", key
                assert health["components"]["graph"] == "pure"
                assert health["status"] == "degraded"
                chat = test_client.post(
                    "/v1/chat", json={"query": "计算 12*8 的结果", "stream": False}
                )
                assert chat.status_code == 200
                assert "96" in chat.json()["answer"]
                # 视频在 cv2 缺失时必须走确定性合成帧，仍可入库
                ingest = test_client.post(
                    "/v1/ingest",
                    files={"files": ("clip.mp4", b"not-decodable", "video/mp4")},
                )
                assert ingest.status_code == 200
                assert any(c["modality"] == "video" for c in ingest.json()["chunks"])
            finally:
                test_client.close()
        finally:
            if context is not None:
                context.tools.shutdown()
                context.tracer.close()
            config.reset_settings_cache()


# --------------------------------------------------------------------------- #
# 脱敏（NF-2）
# --------------------------------------------------------------------------- #


class TestRedaction:
    def test_fake_key_never_leaks_into_logs_traces_or_responses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
    ):
        monkeypatch.setenv("DEMO_MODE", "1")
        monkeypatch.setenv("LLM_API_KEY", FAKE_KEY)
        monkeypatch.setenv("LLM_BASE_URL", "https://evil.invalid/v1")
        monkeypatch.setenv("AUTHORIZATION", "Bearer " + FAKE_KEY)
        monkeypatch.setitem(config._PATH_OVERRIDES, "data_dir", tmp_path / "data")
        monkeypatch.setitem(config._PATH_OVERRIDES, "tmp_dir", tmp_path / "data" / "tmp")
        config.reset_settings_cache()

        from app.observability.logging import (
            configure_logging,
            redact_snapshot,
            redact_text,
        )

        configure_logging(config.get_settings())
        assert FAKE_KEY not in redact_text(f"key={FAKE_KEY}")
        snapshot = redact_snapshot(
            {"query": "hello", "answer": FAKE_KEY, "api_key": FAKE_KEY, "content": b"raw"}
        )
        assert FAKE_KEY not in json.dumps(snapshot, ensure_ascii=False)

        context = None
        responses: list[str] = []
        try:
            context = build_context()
            test_client = _make_client(context)
            try:
                for method, path, kwargs in [
                    ("get", "/health", {}),
                    ("get", "/v1/tools", {}),
                    ("post", "/v1/ingest", {"data": {"text": "脱敏文本"}}),
                    ("post", "/v1/chat", {"json": {"query": "计算 12*8", "stream": False}}),
                    ("post", "/v1/chat", {"json": {"query": "介绍一下平台", "stream": True}}),
                    ("post", "/v1/eval", {"json": {}}),
                    ("post", "/v1/chat", {"json": {"query": "", "stream": False}}),
                ]:
                    response = getattr(test_client, method)(path, **kwargs)
                    responses.append(response.text)
                trace_id = test_client.post(
                    "/v1/chat", json={"query": "脱敏回放", "stream": False}
                ).json()["trace_id"]
                responses.append(test_client.get("/v1/trace/" + trace_id).text)
            finally:
                test_client.close()

            captured = capsys.readouterr()
            stdout_and_stderr = captured.out + captured.err
            trace_text = (tmp_path / "data" / "traces.jsonl").read_text(encoding="utf-8")
            index_text = (tmp_path / "data" / "vector_index.json").read_text(encoding="utf-8")
            combined = "\n".join(responses) + stdout_and_stderr + trace_text + index_text
            assert FAKE_KEY not in combined
            assert "evil.invalid" not in combined
            for text in responses:
                assert "Traceback" not in text
        finally:
            if context is not None:
                context.tools.shutdown()
                context.tracer.close()
            config.reset_settings_cache()


# --------------------------------------------------------------------------- #
# 配置健壮性（BUG1 独立回归）
# --------------------------------------------------------------------------- #


class TestConfigRobustness:
    def test_env_example_blank_placeholders_do_not_break_startup(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """README §4 / .env.example 头部写明「复制为 .env 后按需填写」。

        模板里的 ``HOST=`` / ``PORT=`` / ``AGENT_MAX_STEPS=`` / ``HUMAN_IN_LOOP=``
        是空值占位符；空串必须被当作「未设置」，绝不能触发 ConfigError 或把
        ``server.host`` 静默设成空串。
        """
        root = config.PROJECT_ROOT
        fake_root = tmp_path / "isolated_project"
        (fake_root / "config").mkdir(parents=True)
        (fake_root / "config" / "settings.yaml").write_bytes(
            (root / "config" / "settings.yaml").read_bytes()
        )
        (fake_root / ".env").write_bytes((root / ".env.example").read_bytes())

        monkeypatch.setattr(config, "PROJECT_ROOT", fake_root)
        config.reset_settings_cache()
        try:
            settings = config.get_settings()
            assert settings.server.host == "0.0.0.0"
            assert settings.server.port == 8000
            assert settings.agent.max_steps == 8
            assert settings.agent.tool_timeout_seconds == 3.0
            assert settings.agent.human_in_loop is False
            assert settings.demo.enabled is True
        finally:
            config.reset_settings_cache()

    def test_blank_host_environment_variable_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("HOST", "")
        monkeypatch.setenv("PORT", "")
        config.reset_settings_cache()
        try:
            settings = config.get_settings()
            assert settings.server.host == "0.0.0.0"
            assert settings.server.port == 8000
        finally:
            config.reset_settings_cache()

    def test_map_prefixed_override_works_and_bare_section_vars_are_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("MAP_SERVER__HOST", "10.1.2.3")
        monkeypatch.setenv("MAP_RETRIEVAL__DENSE_WEIGHT", "0.7")
        config.reset_settings_cache()
        try:
            settings = config.get_settings()
            assert settings.server.host == "10.1.2.3"
            assert settings.retrieval.dense_weight == 0.7
            assert config.env_override("server", "host", {"SERVER__HOST": "9.9.9.9"}) is None
        finally:
            config.reset_settings_cache()

    def test_invalid_config_value_raises_readable_config_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("MAP_AGENT__MAX_STEPS", "not-an-int")
        config.reset_settings_cache()
        try:
            with pytest.raises(ConfigError) as caught:
                config.get_settings()
            assert "agent.max_steps" in str(caught.value)
        finally:
            config.reset_settings_cache()


# --------------------------------------------------------------------------- #
# 静态源码安全扫描 + 既有文件字节守护
# --------------------------------------------------------------------------- #


def _app_python_files() -> list[Path]:
    root = config.PROJECT_ROOT / "app"
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


class TestStaticSafety:
    def test_no_builtin_hash_eval_exec_calls(self):
        offenders: list[str] = []
        for path in _app_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in ("hash", "eval", "exec", "compile"):
                        offenders.append(f"{path}:{node.lineno}:{node.func.id}")
        assert offenders == []

    def test_no_top_level_hard_import_of_optional_dependencies(self):
        optional = {
            "langgraph",
            "chromadb",
            "whisper",
            "transformers",
            "openai",
            "cv2",
            "torch",
            "jsonschema",
            "dotenv",
            "python_dotenv",
        }
        offenders: list[str] = []
        for path in _app_python_files():
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module]
                for name in names:
                    if name.split(".")[0] in optional:
                        offenders.append(f"{path}:{node.lineno}:{name}")
        assert offenders == []

    def test_no_hardcoded_credentials_in_shipped_text_files(self):
        root = config.PROJECT_ROOT
        pattern = re.compile(r"sk-[A-Za-z0-9]{16,}|Bearer\s+[A-Za-z0-9_\-]{20,}")
        offenders: list[str] = []
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".yaml", ".yml", ".json", ".example", ".txt", ".md"}:
                continue
            if any(part in path.parts for part in ("data", "__pycache__", ".pytest_cache", ".git")):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in pattern.finditer(text):
                offenders.append(f"{path}: {match.group(0)[:40]}")
        assert offenders == []

    def test_protected_files_are_byte_identical(self):
        import hashlib

        root = config.PROJECT_ROOT
        for name, expected in _PROTECTED_SHA256.items():
            actual = hashlib.sha256((root / name).read_bytes()).hexdigest()
            assert actual == expected, f"{name} 被改动：{actual}"

    def test_gitignore_covers_required_entries(self):
        content = (config.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        lines = [line.strip() for line in content.splitlines()]
        for entry in (".env", "data/", "__pycache__/", ".pytest_cache/"):
            assert any(line == entry or line.startswith(entry) for line in lines), entry
