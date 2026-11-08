"""BUG1 回归：空白／空串环境变量不得让 ``get_settings()`` 抛 ``ConfigError``。

全部用例经 ``env_sandbox`` fixture 把 ``PROJECT_ROOT`` 隔离到 ``tmp_path``，
在沙箱内放 ``.env.example`` 的空占位符内容，**绝不在仓库根生成真实 ``.env``**。
对应 ``docs/TASKS-OPENSOURCE.md`` T-OS4 的 4 条回归用例与 M-3 判据。
"""

from __future__ import annotations

import json
from pathlib import Path

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


def test_demo_lock_with_api_key_and_no_secret_leak(
    env_sandbox, monkeypatch, capsys, caplog
):
    """④ 配 Key + ``LLM_BACKEND=api`` 且 DEMO_MODE=1 仍锁定三后端，Key 不进输出。

    QA-T07：原用例只用 ``capsys`` 断言 stdout，V1 负向验证证明结构化日志通道
    泄漏 ``sk-should-not-leak`` 时仍全绿（日志 handler 绑定配置时刻的 stdout）。
    这里显式 ``configure_logging`` 刷新 secrets + 绑定当前捕获流，主动发一条
    含假密钥的日志，再用 ``caplog`` + ``JsonFormatter`` 校验渲染后的真实输出，
    并断言确实捕获到了记录，避免「空集合上的 not in」恒真断言。
    """
    import json
    import logging

    from app.observability.logging import JsonFormatter, configure_logging, get_logger

    fake_key = "sk-should-not-leak"
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("LLM_API_KEY", fake_key)
    monkeypatch.setenv("ENCODER_BACKEND", "api")
    monkeypatch.setenv("VECTOR_BACKEND", "chroma")

    settings = _reload()
    assert (settings.llm.backend, settings.encoder.backend, settings.vector_store.backend) == (
        "template",
        "stub",
        "memory",
    )

    configure_logging(settings)
    caplog.set_level(logging.INFO, logger="multimodal_agent_platform")
    get_logger("qa.leak_probe").warning(
        "LLM_API_KEY=%s", fake_key, extra={"event": "qa_leak_probe"}
    )

    assert caplog.records, "必须捕获到至少一条结构化日志，否则断言是恒真的"
    formatter = JsonFormatter()
    for record in caplog.records:
        rendered = formatter.format(record)
        payload = json.loads(rendered)
        assert {"ts", "level", "event", "component", "trace_id", "message"} <= set(payload)
        assert fake_key not in rendered, rendered
    assert any(getattr(record, "event", None) == "qa_leak_probe" for record in caplog.records)

    # 直接钉住 JsonFormatter 出口：构造一条「尚未经过 RedactFilter」的原始记录，
    # 渲染后的 JSON 仍必须不含假密钥（避免只依赖 handler 侧 filter 的单一防线）。
    raw_record = logging.LogRecord(
        name="qa.leak_probe",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="LLM_API_KEY=%s",
        args=(fake_key,),
        exc_info=None,
    )
    rendered_raw = formatter.format(raw_record)
    assert fake_key not in rendered_raw, rendered_raw
    assert "***REDACTED***" in rendered_raw

    captured = capsys.readouterr()
    assert fake_key not in (captured.out + captured.err)
    config.reset_settings_cache()


# --------------------------------------------------------------------------- #
# QA-T13：配置启动期校验 / 类型转换 / dotenv 解析
# --------------------------------------------------------------------------- #


def test_map_prefixed_list_dict_bool_coercion(env_sandbox, monkeypatch):
    """MAP_ 长格式对 list / dict / bool 三类默认值都要能覆盖。"""
    monkeypatch.setenv("MAP_OBSERVABILITY__REDACT_KEYS", '["alpha","beta"]')
    monkeypatch.setenv("MAP_INGEST__ALLOWED_EXTENSIONS", '{"text":[".txt"]}')
    monkeypatch.setenv("MAP_AGENT__HUMAN_IN_LOOP", "yes")
    settings = _reload()
    assert settings.observability.redact_keys == ["alpha", "beta"]
    assert settings.ingest.allowed_extensions == {"text": [".txt"]}
    assert settings.agent.human_in_loop is True
    config.reset_settings_cache()


@pytest.mark.parametrize(
    ("env_key", "env_value", "expected_in_detail"),
    [
        ("MAP_CONFIG__VERSION", "2", "config_version"),
        ("MAP_AGENT__MAX_STEPS", "0", "agent.max_steps"),
        ("MAP_AGENT__TOOL_TIMEOUT_SECONDS", "-1", "agent.tool_timeout_seconds"),
        ("MAP_INGEST__CHUNK_OVERLAP", "400", "ingest.chunk_overlap"),
        ("MAP_LLM__BACKEND", "bogus", "llm.backend"),
        ("MAP_ENCODER__BACKEND", "bogus", "encoder.backend"),
        ("MAP_VECTOR_STORE__BACKEND", "bogus", "vector_store.backend"),
        ("MAP_INGEST__ALLOWED_EXTENSIONS", '{"text":["txt"]}', "."),
    ],
)
def test_invalid_config_branches_raise_readable_config_error(
    env_sandbox, monkeypatch, env_key, env_value, expected_in_detail
):
    # env_sandbox 的 .env 来自 .env.example，内含 LLM_BACKEND / ENCODER_BACKEND /
    # VECTOR_BACKEND 等历史短别名，优先级高于 MAP_ 长格式。枚举越界用例必须先
    # 去掉这些短别名，否则 MAP_LLM__BACKEND=bogus 会被短别名 template 覆盖。
    (env_sandbox / ".env").write_text("# no short aliases for this case\n", encoding="utf-8")
    for alias in ("LLM_BACKEND", "ENCODER_BACKEND", "VECTOR_BACKEND"):
        monkeypatch.delenv(alias, raising=False)
    monkeypatch.setenv(env_key, env_value)
    with pytest.raises(ConfigError) as raised:
        _reload()
    assert expected_in_detail in str(raised.value)
    config.reset_settings_cache()


@pytest.mark.parametrize("bad_float", ["nan", "inf", "-inf", "1e400"])
def test_non_finite_float_config_is_rejected(env_sandbox, monkeypatch, bad_float):
    """TD-02：float 配置不接受 nan/inf；0.7 仍生效。

    按「修复后行为」断言。当前源码若尚未落地，该用例应如实标注「待源码落地后回归」。
    """
    monkeypatch.setenv("MAP_RETRIEVAL__DENSE_WEIGHT", bad_float)
    with pytest.raises(ConfigError) as raised:
        _reload()
    assert "dense_weight" in str(raised.value) or "非有限" in str(raised.value)
    config.reset_settings_cache()

    monkeypatch.setenv("MAP_RETRIEVAL__DENSE_WEIGHT", "0.7")
    assert _reload().retrieval.dense_weight == 0.7
    config.reset_settings_cache()


def test_load_dotenv_simple_line_forms(tmp_path: Path):
    """6 种行形态：普通/双引号/单引号/注释/export/首个等号切分 + 缺失文件。"""
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "\n".join(
            [
                "# comment line",
                "",
                "A=1",
                'B="quoted value"',
                "C='single quoted'",
                "export D=4",
                "NO_EQUALS_SIGN",
                "E=with=equals",
                "  F  =  spaced  ",
            ]
        ),
        encoding="utf-8",
    )
    parsed = config.load_dotenv_simple(dotenv)
    assert parsed["A"] == "1"
    assert parsed["B"] == "quoted value"
    assert parsed["C"] == "single quoted"
    assert parsed["D"] == "4"
    assert parsed["E"] == "with=equals"
    assert parsed["F"] == "spaced"
    assert "NO_EQUALS_SIGN" not in parsed
    assert "# comment line" not in str(parsed)
    assert config.load_dotenv_simple(tmp_path / "absent.env") == {}


# --------------------------------------------------------------------------- #
# TD-16 / TD-21：新配置键 env 覆盖 + 正数校验 + 白名单三分支校验
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("env_key", "env_value", "attr_getter"),
    [
        ("MAP_EVAL__MAX_SAMPLES", "50", lambda s: s.eval.max_samples),
        ("MAP_AGENT__TOOL_ORPHAN_MAX", "4", lambda s: s.agent.tool_orphan_max),
    ],
)
def test_new_numeric_keys_env_override(env_sandbox, monkeypatch, env_key, env_value, attr_getter):
    """``MAP_EVAL__MAX_SAMPLES`` / ``MAP_AGENT__TOOL_ORPHAN_MAX`` 走通用兜底生效。"""
    monkeypatch.setenv(env_key, env_value)
    settings = _reload()
    assert attr_getter(settings) == int(env_value)
    config.reset_settings_cache()


@pytest.mark.parametrize(
    ("env_key", "env_value", "expected_in_detail"),
    [
        ("MAP_EVAL__MAX_SAMPLES", "0", "eval.max_samples"),
        ("MAP_EVAL__MAX_SAMPLES", "-1", "eval.max_samples"),
        ("MAP_EVAL__MAX_SAMPLES", "abc", "eval.max_samples"),
        ("MAP_AGENT__TOOL_ORPHAN_MAX", "0", "agent.tool_orphan_max"),
        ("MAP_AGENT__TOOL_ORPHAN_MAX", "-3", "agent.tool_orphan_max"),
    ],
)
def test_new_numeric_keys_invalid_values_raise(
    env_sandbox, monkeypatch, env_key, env_value, expected_in_detail
):
    """非法（非整数）/非正值 → ``ConfigError``，与既有正数键同风格。"""
    monkeypatch.setenv(env_key, env_value)
    with pytest.raises(ConfigError) as raised:
        _reload()
    assert expected_in_detail in str(raised.value)
    config.reset_settings_cache()


@pytest.mark.parametrize(
    ("extensions", "expected_in_detail"),
    [
        ({"bogus": [".txt"]}, "bogus"),  # ① 模态键 ∉ _VALID_MODALITIES
        ({"text": [".txt"], "image": [".txt"]}, ".txt"),  # ② 同一扩展名跨模态冲突
        ({"text": []}, "为空"),  # ③ 扁平化后映射为空
    ],
)
def test_allowed_extensions_invalid_config_branches(
    env_sandbox, monkeypatch, extensions, expected_in_detail
):
    """TD-16 · B3：三条新增白名单校验各自抛可读 ``ConfigError``。"""
    monkeypatch.setenv(
        "MAP_INGEST__ALLOWED_EXTENSIONS", json.dumps(extensions, ensure_ascii=False)
    )
    with pytest.raises(ConfigError) as raised:
        _reload()
    message = str(raised.value)
    assert expected_in_detail in message
    assert "allowed_extensions" in message
    config.reset_settings_cache()


def test_allowed_extensions_same_modality_duplicate_is_allowed(env_sandbox, monkeypatch):
    """同一模态组内重复声明同一扩展名不报错（去重语义）。"""
    monkeypatch.setenv(
        "MAP_INGEST__ALLOWED_EXTENSIONS", '{"text": [".txt", ".txt"], "audio": [".wav"]}'
    )
    settings = _reload()
    assert settings.ingest.allowed_extensions == {"text": [".txt", ".txt"], "audio": [".wav"]}
    config.reset_settings_cache()
