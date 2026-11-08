"""配置分层、DEMO 锁定、可选依赖探测与路径解析。

合并顺序（严格，docs/TASKS.md T01 实现要点 1）：
    ① ``config/settings.yaml``
    ② ``.env``（自写解析，**不覆盖已有 os.environ**）
    ③ ``os.environ`` 历史短别名 + ``MAP_<SECTION>__<KEY>`` 项目前缀通用兜底覆盖
    ④ 启动期校验
    ⑤ **最后一步**：``demo.enabled`` 为真时无条件覆写
      ``llm.backend=template`` / ``encoder.backend=stub`` / ``vector_store.backend=memory``

本模块只允许依赖 ``app.schemas``（异常类），不得 import 任何业务模块。
所有路径基于 ``PROJECT_ROOT = Path(__file__).resolve().parents[1]``，禁止依赖 cwd。
"""

from __future__ import annotations

import functools
import importlib.util
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.schemas import ConfigError

#: 项目根；所有相对路径都基于它解析，与当前工作目录无关。
PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

#: 测试隔离钩子：``tests/conftest.py`` 通过 monkeypatch 写入 ``data_dir`` / ``tmp_dir``，
#: 使运行期产物落到 ``tmp_path``，不污染仓库 ``data/``。
_PATH_OVERRIDES: dict[str, Path] = {}


# --------------------------------------------------------------------------- #
# 配置模型
# --------------------------------------------------------------------------- #


class _Cfg(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ServerCfg(_Cfg):
    host: str = "0.0.0.0"
    port: int = 8000


class DemoCfg(_Cfg):
    enabled: bool = True


class LLMCfg(_Cfg):
    backend: str = "template"
    api_key: str = ""
    base_url: str = ""
    model: str = ""
    vision_model: str = ""
    timeout_seconds: float = 10.0
    max_tokens: int = 512


class EncoderCfg(_Cfg):
    backend: str = "stub"
    dim: int = 256
    local_model_path: str = ""
    timeout_seconds: float = 10.0


class VectorStoreCfg(_Cfg):
    backend: str = "memory"
    soft_limit: int = 10000
    index_path: str = "data/vector_index.json"
    top_k: int = 5


class RetrievalCfg(_Cfg):
    dense_weight: float = 0.6
    bm25_weight: float = 0.4
    dense_floor: float = 1.0e-9
    substring_boost: float = 0.15
    snippet_chars: int = 160


class IngestCfg(_Cfg):
    chunk_size: int = 320
    chunk_overlap: int = 64
    allowed_extensions: dict[str, list[str]] = Field(default_factory=dict)
    max_file_bytes: int = 10485760
    max_total_bytes: int = 52428800
    max_files: int = 20
    tmp_dir: str = "data/tmp"


class AgentCfg(_Cfg):
    max_steps: int = 8
    tool_timeout_seconds: float = 3.0
    max_query_chars: int = 2000
    token_chunk_chars: int = 24
    human_in_loop: bool = False


class ObservabilityCfg(_Cfg):
    trace_path: str = "data/traces.jsonl"
    eval_report_path: str = "data/eval_report.json"
    log_level: str = "INFO"
    log_json: bool = True
    redact_keys: list[str] = Field(default_factory=list)


class EvalCfg(_Cfg):
    samples_path: str = "samples/eval.jsonl"
    default_samples: int = 8


class Settings(_Cfg):
    """完整配置契约；字段名与 ``config/settings.yaml`` 逐键对应。"""

    config_version: int = 1
    server: ServerCfg = Field(default_factory=ServerCfg)
    demo: DemoCfg = Field(default_factory=DemoCfg)
    llm: LLMCfg = Field(default_factory=LLMCfg)
    encoder: EncoderCfg = Field(default_factory=EncoderCfg)
    vector_store: VectorStoreCfg = Field(default_factory=VectorStoreCfg)
    retrieval: RetrievalCfg = Field(default_factory=RetrievalCfg)
    ingest: IngestCfg = Field(default_factory=IngestCfg)
    agent: AgentCfg = Field(default_factory=AgentCfg)
    observability: ObservabilityCfg = Field(default_factory=ObservabilityCfg)
    eval: EvalCfg = Field(default_factory=EvalCfg)


# --------------------------------------------------------------------------- #
# .env 解析（自写，禁止 python-dotenv）
# --------------------------------------------------------------------------- #


def load_dotenv_simple(path: Path) -> dict[str, str]:
    """极简 ``.env`` 解析：逐行、跳空行与 ``#``、按首个 ``=`` 切分、去成对引号。

    不插值、不执行、不 ``eval``、不写入 ``os.environ``；文件不存在返回 ``{}``。
    「不覆盖已有环境变量」由 :func:`get_settings` 的合并顺序保证（os.environ 优先）。
    **空白／空串值一律视为「未设置」不写入结果**（BUG1：``.env.example`` 的空占位符、
    宿主注入的空值变量都不得成为有效覆盖）；非空值行为不变。
    """
    result: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return result

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        # BUG1 修复点 1：空串／纯空白占位符不写入 result，视为「未设置」。
        if key and value.strip() != "":
            result[key] = value
    return result


# --------------------------------------------------------------------------- #
# 环境变量覆盖
# --------------------------------------------------------------------------- #

#: 历史短别名（优先于通用兜底）。docs/ARCHITECTURE.md §3.5-B。
SHORT_ALIASES: dict[tuple[str, str], tuple[str, ...]] = {
    ("demo", "enabled"): ("DEMO_MODE",),
    ("server", "host"): ("HOST",),
    ("server", "port"): ("PORT",),
    ("llm", "backend"): ("LLM_BACKEND",),
    ("llm", "api_key"): ("LLM_API_KEY",),
    ("llm", "base_url"): ("LLM_BASE_URL",),
    ("llm", "model"): ("LLM_MODEL",),
    ("llm", "vision_model"): ("LLM_VISION_MODEL",),
    ("encoder", "backend"): ("ENCODER_BACKEND",),
    ("encoder", "local_model_path"): ("ENCODER_LOCAL_MODEL_PATH",),
    ("vector_store", "backend"): ("VECTOR_BACKEND",),
    ("vector_store", "soft_limit"): ("VECTOR_STORE_SOFT_LIMIT", "VECTOR_SOFT_LIMIT"),
    ("vector_store", "top_k"): ("VECTOR_STORE_TOP_K",),
    ("agent", "max_steps"): ("AGENT_MAX_STEPS",),
    ("agent", "tool_timeout_seconds"): ("AGENT_TOOL_TIMEOUT_SECONDS",),
    ("agent", "human_in_loop"): ("HUMAN_IN_LOOP",),
    ("agent", "max_query_chars"): ("AGENT_MAX_QUERY_CHARS",),
    ("agent", "token_chunk_chars"): ("AGENT_TOKEN_CHUNK_CHARS",),
    ("ingest", "max_file_bytes"): ("INGEST_MAX_FILE_BYTES",),
    ("ingest", "max_total_bytes"): ("INGEST_MAX_TOTAL_BYTES",),
    ("ingest", "max_files"): ("INGEST_MAX_FILES",),
    ("ingest", "chunk_size"): ("INGEST_CHUNK_SIZE",),
    ("ingest", "chunk_overlap"): ("INGEST_CHUNK_OVERLAP",),
}


#: 长格式环境变量的**项目前缀**。
#: 宿主环境可能注入与本平台无关的 ``SERVER__HOST`` / ``SERVER__PORT`` 等变量；
#: 裸 ``<SECTION>__<KEY>`` 会误读它们并悄悄改变监听地址，因此统一加 ``MAP_``。
#: 规格 §4.6 明确的历史短别名（``DEMO_MODE`` / ``HOST`` / ``PORT`` /
#: ``LLM_BACKEND`` / ``ENCODER_BACKEND`` / ``VECTOR_BACKEND`` / ``HUMAN_IN_LOOP`` 等）
#: **不带前缀**，行为与优先级保持不变。
ENV_PREFIX = "MAP_"


def env_override(section: str, key: str, env: Mapping[str, str] | None = None) -> str | None:
    """返回该配置键的环境变量覆盖值；先查历史短别名，再查 ``MAP_<SECTION>__<KEY>`` 兜底。

    长格式必须带 :data:`ENV_PREFIX` 项目前缀以避免与宿主环境同名变量冲突；
    该规则保证「所有键支持环境变量覆盖」而无须逐一列举。
    **空白／空串值视为「未设置」返回 ``None``**（BUG1 修复点 2）：同时覆盖
    ``.env`` 解析结果、规格短别名与 ``MAP_`` 长格式三条来源，也同时覆盖
    :func:`get_settings` 主合并循环与 ``config_version`` 单独覆盖两条调用路径。
    """
    source: Mapping[str, str] = env if env is not None else os.environ
    for alias in SHORT_ALIASES.get((section, key), ()):
        if alias in source:
            raw = str(source[alias])
            if raw.strip() == "":
                # 空值不作为有效覆盖，继续查下一个候选；非空候选优先级不变。
                continue
            return raw
    generic = f"{ENV_PREFIX}{section.upper()}__{key.upper()}"
    if generic in source:
        raw = str(source[generic])
        if raw.strip() == "":
            return None
        return raw
    return None


def _coerce(raw: str, default: Any, path: str) -> Any:
    """按 YAML 默认值的类型转换环境变量字符串；失败抛可读 ``ConfigError``。"""
    try:
        if isinstance(default, bool):
            low = raw.strip().lower()
            if low in ("1", "true", "yes", "on"):
                return True
            if low in ("0", "false", "no", "off"):
                return False
            raise ValueError(f"布尔值只能是 1/0/true/false/yes/no/on/off，收到 {raw!r}")
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError(f"必须是有限数值，收到 {raw!r}")
            return value
        if isinstance(default, list):
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError("期望 JSON 数组")
            return parsed
        if isinstance(default, dict):
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("期望 JSON 对象")
            return parsed
        return raw
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ConfigError(
            f"配置项 {path} 的环境变量值 {raw!r} 无法转换为 "
            f"{type(default).__name__} 类型：{exc}"
        ) from exc


# --------------------------------------------------------------------------- #
# 启动期校验
# --------------------------------------------------------------------------- #


def _validate_settings(settings: Settings) -> None:
    """校验版本、枚举取值域、正数、overlap<size、白名单扩展名以 ``.`` 开头。"""
    if settings.config_version != 1:
        raise ConfigError(f"config_version 必须为 1，当前为 {settings.config_version}")
    if settings.llm.backend not in ("api", "template"):
        raise ConfigError(f"llm.backend 取值非法：{settings.llm.backend!r}，仅允许 api / template")
    if settings.encoder.backend not in ("api", "transformers", "stub"):
        raise ConfigError(
            f"encoder.backend 取值非法：{settings.encoder.backend!r}，"
            "仅允许 api / transformers / stub"
        )
    if settings.vector_store.backend not in ("chroma", "memory"):
        raise ConfigError(
            f"vector_store.backend 取值非法：{settings.vector_store.backend!r}，"
            "仅允许 chroma / memory"
        )

    positive: list[tuple[str, float]] = [
        ("server.port", settings.server.port),
        ("llm.timeout_seconds", settings.llm.timeout_seconds),
        ("llm.max_tokens", settings.llm.max_tokens),
        ("encoder.dim", settings.encoder.dim),
        ("encoder.timeout_seconds", settings.encoder.timeout_seconds),
        ("vector_store.soft_limit", settings.vector_store.soft_limit),
        ("vector_store.top_k", settings.vector_store.top_k),
        ("retrieval.dense_weight", settings.retrieval.dense_weight),
        ("retrieval.bm25_weight", settings.retrieval.bm25_weight),
        ("retrieval.dense_floor", settings.retrieval.dense_floor),
        ("retrieval.substring_boost", settings.retrieval.substring_boost),
        ("retrieval.snippet_chars", settings.retrieval.snippet_chars),
        ("ingest.chunk_size", settings.ingest.chunk_size),
        ("ingest.chunk_overlap", settings.ingest.chunk_overlap),
        ("ingest.max_file_bytes", settings.ingest.max_file_bytes),
        ("ingest.max_total_bytes", settings.ingest.max_total_bytes),
        ("ingest.max_files", settings.ingest.max_files),
        ("agent.max_steps", settings.agent.max_steps),
        ("agent.tool_timeout_seconds", settings.agent.tool_timeout_seconds),
        ("agent.max_query_chars", settings.agent.max_query_chars),
        ("agent.token_chunk_chars", settings.agent.token_chunk_chars),
        ("eval.default_samples", settings.eval.default_samples),
    ]
    for name, value in positive:
        if value <= 0:
            raise ConfigError(f"配置项 {name} 必须为正数，当前为 {value}")

    if settings.ingest.chunk_overlap >= settings.ingest.chunk_size:
        raise ConfigError(
            "ingest.chunk_overlap 必须小于 ingest.chunk_size（"
            f"{settings.ingest.chunk_overlap} >= {settings.ingest.chunk_size}）"
        )

    for modality, exts in settings.ingest.allowed_extensions.items():
        for ext in exts:
            if not str(ext).startswith("."):
                raise ConfigError(
                    f"ingest.allowed_extensions.{modality} 的扩展名 {ext!r} 必须以 '.' 开头"
                )


# --------------------------------------------------------------------------- #
# 唯一配置入口
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """三层合并 + 启动期校验 + **最后一步 DEMO 无条件锁定**。"""
    yaml_path = PROJECT_ROOT / "config" / "settings.yaml"
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigError(f"无法读取或解析配置文件 {yaml_path}：{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件 {yaml_path} 顶层必须是映射（mapping）")

    # ② .env（不覆盖 os.environ）→ ③ os.environ 优先
    env: dict[str, str] = load_dotenv_simple(PROJECT_ROOT / ".env")
    env.update(dict(os.environ))

    data: dict[str, Any] = dict(raw)
    for section, cfg in list(data.items()):
        if not isinstance(cfg, dict):
            continue
        merged_section = dict(cfg)
        for key, default in cfg.items():
            override = env_override(section, key, env)
            if override is not None:
                merged_section[key] = _coerce(override, default, f"{section}.{key}")
        data[section] = merged_section

    cv_override = env_override("config", "version", env)
    if cv_override is not None:
        data["config_version"] = _coerce(
            cv_override, data.get("config_version", 1), "config_version"
        )

    try:
        settings = Settings.model_validate(data)
    except Exception as exc:  # Pydantic ValidationError → 可读中文
        raise ConfigError(f"配置模型校验失败：{exc}") from exc

    _validate_settings(settings)

    # ⑤ 最后一步：DEMO 无条件锁定（覆盖写回，发生在配置层而非各后端各自判断）
    if settings.demo.enabled:
        settings.llm.backend = "template"
        settings.encoder.backend = "stub"
        settings.vector_store.backend = "memory"
    return settings


def reset_settings_cache() -> None:
    """清除 ``get_settings`` 的 lru_cache，供测试在 DEMO/生产切换时调用。"""
    get_settings.cache_clear()


# --------------------------------------------------------------------------- #
# 可选依赖探测（只用 find_spec，绝不顶层硬 import）
# --------------------------------------------------------------------------- #

_OPTIONAL_MODULES: dict[str, str] = {
    "langgraph": "langgraph",
    "chromadb": "chromadb",
    "whisper": "whisper",
    "cv2": "cv2",
    "transformers": "transformers",
    "openai": "openai",
}


def probe_optional_dependencies() -> dict[str, str]:
    """返回 6 项 ``native`` / ``fallback`` 探测结果。

    探测结果只说明「包是否已安装」，**不代表启用状态**；DEMO 下即使
    ``langgraph == "native"``，生效后端仍强制为 ``pure``（ARCH §5.6）。
    """
    result: dict[str, str] = {}
    for key, module_name in _OPTIONAL_MODULES.items():
        try:
            result[key] = (
                "native" if importlib.util.find_spec(module_name) is not None else "fallback"
            )
        except (ImportError, ValueError, ModuleNotFoundError, AttributeError):
            result[key] = "fallback"
    return result


# --------------------------------------------------------------------------- #
# 路径解析（唯一入口）
# --------------------------------------------------------------------------- #


@dataclass
class Paths:
    """全部运行期路径，均基于 :data:`PROJECT_ROOT`（或从测试覆盖钩子注入）。"""

    project_root: Path
    config_dir: Path
    app_dir: Path
    web_dir: Path
    samples_dir: Path
    data_dir: Path
    tmp_dir: Path
    settings_path: Path
    knowledge_path: Path
    eval_samples_path: Path
    index_path: Path
    trace_path: Path
    eval_report_path: Path
    web_index_path: Path


def resolve_paths() -> Paths:
    """解析全部路径并自动创建 ``data/`` 与 ``data/tmp/``；不可写抛 ``ConfigError``。"""
    settings = get_settings()
    root = PROJECT_ROOT
    config_dir = root / "config"
    app_dir = root / "app"
    web_dir = root / "web"
    samples_dir = root / "samples"

    data_dir = Path(_PATH_OVERRIDES.get("data_dir") or (root / "data"))
    tmp_dir = Path(
        _PATH_OVERRIDES.get("tmp_dir") or (data_dir / Path(settings.ingest.tmp_dir).name)
    )
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigError(f"无法创建运行期目录 {data_dir} / {tmp_dir}：{exc}") from exc
    if not os.access(data_dir, os.W_OK):
        raise ConfigError(f"运行期目录不可写：{data_dir}")

    return Paths(
        project_root=root,
        config_dir=config_dir,
        app_dir=app_dir,
        web_dir=web_dir,
        samples_dir=samples_dir,
        data_dir=data_dir,
        tmp_dir=tmp_dir,
        settings_path=config_dir / "settings.yaml",
        knowledge_path=samples_dir / "knowledge.txt",
        eval_samples_path=root / settings.eval.samples_path,
        index_path=data_dir / Path(settings.vector_store.index_path).name,
        trace_path=data_dir / Path(settings.observability.trace_path).name,
        eval_report_path=data_dir / Path(settings.observability.eval_report_path).name,
        web_index_path=web_dir / "index.html",
    )


__all__ = [
    "PROJECT_ROOT",
    "Paths",
    "Settings",
    "ServerCfg",
    "DemoCfg",
    "LLMCfg",
    "EncoderCfg",
    "VectorStoreCfg",
    "RetrievalCfg",
    "IngestCfg",
    "AgentCfg",
    "ObservabilityCfg",
    "EvalCfg",
    "SHORT_ALIASES",
    "ENV_PREFIX",
    "load_dotenv_simple",
    "env_override",
    "get_settings",
    "reset_settings_cache",
    "probe_optional_dependencies",
    "resolve_paths",
]
