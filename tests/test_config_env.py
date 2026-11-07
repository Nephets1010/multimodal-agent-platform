"""BUG1 回归：空白／空串环境变量不得让 ``get_settings()`` 抛 ``ConfigError``。

全部用例经 ``env_sandbox`` fixture 把 ``PROJECT_ROOT`` 隔离到 ``tmp_path``，
在沙箱内放 ``.env.example`` 的空占位符内容，**绝不在仓库根生成真实 ``.env``**。
对应 ``docs/TASKS-OPENSOURCE.md`` T-OS4 的 4 条回归用例与 M-3 判据。
"""

from __future__ import annotations

import pytest

import app.config as config
from app.schemas import ConfigError


def _reload():
    """清 ``lru_cache`` 后重新读取配置。"""
    config.reset_settings_cache()
    return config.get_settings()


def test_env_example_empty_placeholders_fall_back_to_yaml_defaults(
    env_sandbox, monkeypatch
):
    """① 全量空占位符 + 宿主空注入 → 正常返回，数值/布尔键取 YAML 默认。"""
    assert (env_sandbox / ".env").exists()
    assert (env_sandbox / "config" / "settings.yaml").exists()

    # 模拟宿主注入「存在但为空」的同名变量（os.environ 路径，非 .env 路径）
    monkeypatch.setenv("PORT", "")
    monkeypatch.setenv("HOST", "")
    monkeypatch.setenv("AGENT_MAX_STEPS", "")
    monkeypatch.setenv("AGENT_TOOL_TIMEOUT_SECONDS", "")
    monkeypatch.setenv("HUMAN_IN_LOOP", "   ")

    settings = _reload()
    assert settings.server.host == "0.0.0.0"
    assert settings.server.port == 8000
    assert settings.agent.max_steps == 8
    assert settings.agent.tool_timeout_seconds == 3.0
    assert settings.agent.human_in_loop is False
    assert settings.config_version == 1
    assert (settings.llm.backend, settings.encoder.backend, settings.vector_store.backend) == (
        "template",
        "stub",
        "memory",
    )
    config.reset_settings_cache()


def test_non_empty_overrides_still_apply(env_sandbox, monkeypatch):
    """② 非空覆盖仍生效：``MAP_`` 长格式、短别名优先、裸宿主长格式不被读取。"""
    monkeypatch.setenv("MAP_RETRIEVAL__DENSE_WEIGHT", "0.7")
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("SERVER__PORT", "9347")  # 宿主裸长格式，不得被读取
    monkeypatch.setenv("SERVER__HOST", "10.9.9.9")

    settings = _reload()
    assert settings.retrieval.dense_weight == 0.7
    assert settings.server.port == 8123
    assert settings.server.host == "127.0.0.1"

    # 短别名移除后，MAP_ 长格式单独覆盖 server.port
    monkeypatch.delenv("PORT")
    monkeypatch.setenv("MAP_SERVER__PORT", "8123")
    settings2 = _reload()
    assert settings2.server.port == 8123
    config.reset_settings_cache()


def test_invalid_non_empty_value_still_raises_readable_config_error(
    env_sandbox, monkeypatch
):
    """③ 非法非空值仍抛可读 ``ConfigError``（``_coerce()`` 不吞异常）。"""
    monkeypatch.setenv("PORT", "abc")
    with pytest.raises(ConfigError) as raised:
        _reload()
    message = str(raised.value)
    assert "server.port" in message
    assert "无法转换" in message
    config.reset_settings_cache()


def test_demo_lock_with_api_key_and_no_secret_leak(env_sandbox, monkeypatch, capsys):
    """④ 配 Key + ``LLM_BACKEND=api`` 且 DEMO_MODE=1 仍锁定三后端，Key 不进输出。"""
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("LLM_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("ENCODER_BACKEND", "api")
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")

    settings = _reload()
    assert (settings.llm.backend, settings.encoder.backend, settings.vector_store.backend) == (
        "template",
        "stub",
        "memory",
    )
    captured = capsys.readouterr()
    assert "sk-should-not-leak" not in (captured.out + captured.err)
    config.reset_settings_cache()
