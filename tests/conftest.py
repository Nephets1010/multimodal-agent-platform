"""pytest 公共 fixture。

* 固定 ``DEMO_MODE=1`` 并清配置缓存，避免 DEMO/生产切换污染。
* 用 ``monkeypatch`` 把 ``resolve_paths()`` 的 data/tmp 指到 ``tmp_path``，
  **测试绝不污染仓库 ``data/``**，且可重复运行。
* ``ctx`` / ``client`` 都复用同一个 ``build_context()``（不各自 new 依赖）。
* 四模态样例资源生成器（Pillow PNG / wave WAV / 不可解码视频字节走确定性降级）。
"""

from __future__ import annotations

import io
import os
import wave
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.config as config
from app.runtime import build_context
from app.schemas import RawInput


@pytest.fixture(autouse=True)
def _demo_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """每个 test 独立的 DEMO 环境 + 隔离运行期目录。

    QA-T08：先用 ``monkeypatch.delenv`` 清掉所有会影响 ``get_settings()`` 的
    宿主环境变量（历史短别名 + ``MAP_`` 项目前缀键），再固定 ``DEMO_MODE=1``。
    实测未清理时宿主注入 ``AGENT_MAX_STEPS=3`` / ``HUMAN_IN_LOOP=1`` /
    ``HOST+PORT`` 分别导致 3 / 3 / 2 条用例失败，属测试脆弱性而非源码缺陷。
    """
    for aliases in config.SHORT_ALIASES.values():
        for alias in aliases:
            monkeypatch.delenv(alias, raising=False)
    for key in list(os.environ):
        if key.startswith(config.ENV_PREFIX):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DEMO_MODE", "1")
    config.reset_settings_cache()
    config._PATH_OVERRIDES.clear()
    monkeypatch.setitem(config._PATH_OVERRIDES, "data_dir", tmp_path / "data")
    monkeypatch.setitem(config._PATH_OVERRIDES, "tmp_dir", tmp_path / "data" / "tmp")
    yield
    config.reset_settings_cache()


@pytest.fixture
def settings(_demo_env):
    return config.get_settings()


@pytest.fixture
def paths(_demo_env):
    return config.resolve_paths()


@pytest.fixture
def ctx(_demo_env):
    """每个 test 一个独立组合根，退出时释放线程池与轨迹句柄。"""
    context = build_context()
    try:
        yield context
    finally:
        context.tools.shutdown()
        context.tracer.close()


@pytest.fixture
def client(ctx):
    """复用 ``ctx`` 组合根（预置到 app.state），不重复装配。"""
    from app.main import app

    app.state.ctx = ctx
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()


@pytest.fixture
def sample_resources() -> dict[str, RawInput]:
    """四模态样例资源；视频使用不可解码字节，走内容哈希确定性合成帧。"""
    image_buffer = io.BytesIO()
    Image.new("RGB", (40, 32), (88, 166, 255)).save(image_buffer, format="PNG")

    audio_buffer = io.BytesIO()
    with wave.open(audio_buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x01\x02" * 400)

    text = (
        "多模态平台把文本、图像、音频、视频统一解析为 ModalityChunk，"
        "再用混合检索与 Agent 编排生成可溯源应答。\n\n"
        "第二段说明稠密余弦与 BM25 加权融合，以及全零时的关键词回退。"
    )
    return {
        "text": RawInput(
            name="sample.txt",
            content=text.encode("utf-8"),
            mime="text/plain",
            source_tag="pytest",
            text=text,
        ),
        "image": RawInput(
            name="sample.png",
            content=image_buffer.getvalue(),
            mime="image/png",
            source_tag="pytest",
        ),
        "audio": RawInput(
            name="sample.wav",
            content=audio_buffer.getvalue(),
            mime="audio/wav",
            source_tag="pytest",
        ),
        "video": RawInput(
            name="sample.mp4",
            content=b"UNDECODABLE_VIDEO_BYTES_FOR_DETERMINISTIC_FALLBACK",
            mime="video/mp4",
            source_tag="pytest",
        ),
    }


@pytest.fixture
def corrupt_resources() -> dict[str, RawInput]:
    """畸形文件（用于单模态失败隔离与降级）。"""
    return {
        "image": RawInput(
            name="broken.png", content=b"not a png", mime="image/png", source_tag="pytest"
        ),
        "audio": RawInput(
            name="broken.wav", content=b"not a wav", mime="audio/wav", source_tag="pytest"
        ),
        "video": RawInput(
            name="broken.mp4", content=b"", mime="video/mp4", source_tag="pytest"
        ),
    }


def make_state(query: str, max_steps: int = 8) -> Any:
    """构造初始 AgentState（供四组测试复用）。"""
    from app.agent.state import AgentState, make_trace_id

    return AgentState(
        trace_id=make_trace_id(query, "pytest"),
        session_id="pytest",
        query=query,
        max_steps=max_steps,
        last_debug={"modalities": []},
    )


@pytest.fixture
def env_sandbox(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, _demo_env):
    """BUG1 回归专用：把 ``config.PROJECT_ROOT`` 隔离到 ``tmp_path``。

    ``get_settings()`` 读取 ``PROJECT_ROOT / ".env"`` 与
    ``PROJECT_ROOT / "config/settings.yaml"``；现有 ``_demo_env`` 只重定向
    ``data_dir`` / ``tmp_dir``，不重定向 ``PROJECT_ROOT``。本 fixture：

    ① 复制真实 ``config/settings.yaml`` 到沙箱；
    ② 把 ``.env.example`` 的空占位符内容写到沙箱 ``.env``；
    ③ monkeypatch ``config.PROJECT_ROOT`` 并清 ``get_settings`` 的 lru_cache；
    ④ 退出时再次清缓存（``monkeypatch`` 自动恢复 ``PROJECT_ROOT``）。

    **绝不在仓库根生成真实 ``.env``**，也不污染 ``data/``。
    """
    import shutil

    real_root = Path(__file__).resolve().parents[1]
    sandbox = tmp_path / "project_root"
    (sandbox / "config").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        real_root / "config" / "settings.yaml",
        sandbox / "config" / "settings.yaml",
    )
    shutil.copyfile(real_root / ".env.example", sandbox / ".env")

    monkeypatch.setattr(config, "PROJECT_ROOT", sandbox)
    config.reset_settings_cache()
    try:
        yield sandbox
    finally:
        config.reset_settings_cache()
