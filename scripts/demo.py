"""``make demo`` 入口：**不启动服务器**。

流程：组合根 ``build_context()`` → 自生成四种样例资源 → 四模态直接入库
→ ``graph.run()`` 打印轨迹 → ``TestClient`` 冒烟全部端点 → 打印汇总。
运行期产物写 ``data/vector_index.json`` / ``data/traces.jsonl``。
"""

from __future__ import annotations

import io
import sys
import wave
from pathlib import Path

# ``python3 scripts/demo.py`` 时 sys.path[0] 是 scripts/ 而非项目根，
# 这里显式把 PROJECT_ROOT 置入 sys.path（与 config.resolve_paths 同源，不依赖 cwd）。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from app.agent.state import AgentState, make_trace_id  # noqa: E402
from app.api.guards import cleanup_temporary, save_temporary  # noqa: E402
from app.modalities import PROCESSORS  # noqa: E402
from app.runtime import build_context  # noqa: E402
from app.schemas import ModalityError, RawInput  # noqa: E402

_DEMO_TEXT = (
    "多模态通用智能体开发平台把文本、图像、音频、视频统一解析为 ModalityChunk。"
    "混合检索结合稠密向量余弦相似度与简化 BM25 关键词打分，"
    "稠密无结果时自动回退纯关键词检索，避免误召回。"
)


def _make_png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), (58, 166, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


def _make_wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)
    return buffer.getvalue()


def _make_video_bytes() -> bytes:
    """尝试用 cv2 生成一个可解码的小 AVI；失败则返回不可解码字节走确定性降级帧。"""
    try:
        import tempfile

        import cv2  # type: ignore[import-not-found]

        path = Path(tempfile.gettempdir()) / "map_demo_video.avi"
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"MJPG"), 5.0, (64, 48)
        )
        if writer.isOpened():
            for index in range(6):
                frame = np.zeros((48, 64, 3), dtype=np.uint8)
                frame[:, :, index % 3] = 60 + index * 25
                writer.write(frame)
            writer.release()
            data = path.read_bytes()
            path.unlink(missing_ok=True)
            return data
        writer.release()
    except Exception:
        pass
    return b"MAP_DEMO_UNDECODABLE_VIDEO_BYTES_FOR_FALLBACK"


def _resources() -> dict[str, tuple[str, bytes, str]]:
    return {
        "text": ("demo.txt", _DEMO_TEXT.encode("utf-8"), "text/plain"),
        "image": ("demo.png", _make_png_bytes(), "image/png"),
        "audio": ("demo.wav", _make_wav_bytes(), "audio/wav"),
        "video": ("demo.avi", _make_video_bytes(), "video/avi"),
    }


def _ingest_all(ctx) -> tuple[dict[str, int], int]:
    """四模态直接经 processor + index 入库（组合根直调，不发 HTTP）。"""
    counts: dict[str, int] = {}
    all_chunks = []
    temp_paths: list[Path] = []
    try:
        for modality, (name, data, mime) in _resources().items():
            text_hint = _DEMO_TEXT if modality == "text" else None
            if modality == "video":
                temp_path = save_temporary(data, name, ctx.paths.tmp_dir)
                temp_paths.append(temp_path)
                text_hint = str(temp_path)
            raw = RawInput(
                name=name,
                content=data,
                mime=mime,
                source_tag="demo",
                text=text_hint,
            )
            try:
                produced = PROCESSORS[modality]().process(raw, ctx.settings)
            except ModalityError as exc:
                print(f"  [WARN] {modality} 解析失败，降级跳过：{exc.detail}")
                produced = []
            counts[modality] = len(produced)
            all_chunks.extend(produced)
        added = ctx.index.ingest_chunks(all_chunks)
        return counts, added
    finally:
        cleanup_temporary(temp_paths)


def _check(label: str, response, failures: list[str], expected: int = 200) -> None:
    ok = response.status_code == expected
    print(f"  [{'OK' if ok else 'FAIL'}] {label} → HTTP {response.status_code}")
    if not ok:
        failures.append(label)
        print(f"        body: {response.text[:300]}")


def main() -> int:
    print("=== 多模态通用智能体开发平台 · make demo（不启动服务器） ===")
    ctx = build_context()
    print(f"[1] 组合根就绪：graph_backend={ctx.graph_backend} index_chunks={ctx.index.count()}")

    counts, added = _ingest_all(ctx)
    print(
        f"[2] 四模态入库：{counts}，本轮产出切片 {sum(counts.values())}"
        f"（按 chunk_id 去重后新增 {added}），索引总数 {ctx.index.count()}"
    )
    for modality, count in counts.items():
        if count < 1:
            print(f"  [FAIL] {modality} 未产出切片")
            return 1

    query = "请检索多模态平台的混合检索说明，并计算 12*8 的结果"
    state = AgentState(
        trace_id=make_trace_id(query, "demo"),
        session_id="demo",
        query=query,
        max_steps=int(ctx.settings.agent.max_steps),
        last_debug={"modalities": []},
    )
    final = ctx.graph.run(state)
    print(
        f"[3] Agent 轨迹：steps={final.steps} tools={[c.name for c in final.tool_calls]} "
        f"strategy={final.last_debug.get('strategy')} answer_has_96={'96' in final.answer}"
    )

    # Q10 演示：resume(state, "approved") 仅为图层 API，本期无 REST 恢复端点。
    paused = AgentState(
        trace_id=make_trace_id("resume-demo", "demo"),
        session_id="demo",
        query="介绍一下平台",
        max_steps=int(ctx.settings.agent.max_steps),
        last_debug={"modalities": []},
        human_required=True,
        pending_step="reflector",
    )
    resumed = ctx.graph.resume(paused, "approved")
    print(
        f"[3b] resume() 图层 API 演示：human_required={resumed.human_required} "
        f"answer_len={len(resumed.answer)}（本期无 REST 恢复端点）"
    )

    failures: list[str] = []
    from app.main import app

    app.state.ctx = ctx  # 复用同一个 build_context()，lifespan 不重复装配
    with TestClient(app) as client:
        print("[4] TestClient 冒烟全部端点：")
        health = client.get("/health")
        _check("GET /health", health, failures)
        if health.status_code == 200:
            body = health.json()
            print(
                f"        demo_mode={body['demo_mode']} components={len(body['components'])} "
                f"index_chunks={body['components']['index_chunks']}"
            )
            if len(body["components"]) != 11:
                failures.append("health components != 11")

        # 前端同款 FormData：只 append files + source_tag，不 append text（Q3）
        ingest = client.post(
            "/v1/ingest",
            files=[("files", ("webui.txt", b"frontend formdata smoke", "text/plain"))],
            data={"source_tag": "webui"},
        )
        _check("POST /v1/ingest (无 text 字段)", ingest, failures)
        if ingest.status_code == 200:
            print(f"        total={ingest.json()['total']}")

        non_stream = client.post(
            "/v1/chat", json={"query": "计算 12*8 的结果", "stream": False}
        )
        _check("POST /v1/chat stream=false", non_stream, failures)
        trace_id = ""
        if non_stream.status_code == 200:
            body = non_stream.json()
            trace_id = body.get("trace_id", "")
            print(
                f"        fields={len(body)} has_96={'96' in body['answer']} "
                f"status={body['status']} backend={body['graph_backend']}"
            )
            if len(body) != 11 or "96" not in body["answer"]:
                failures.append("unified response contract")

        sse = client.post("/v1/chat", json={"query": "介绍一下平台", "stream": True})
        _check("POST /v1/chat stream=true (SSE)", sse, failures)
        if sse.status_code == 200:
            frames = [part for part in sse.text.split("\n\n") if part.strip()]
            names = [
                line.split(":", 1)[1].strip()
                for part in frames
                for line in part.splitlines()
                if line.startswith("event:")
            ]
            print(f"        frames={len(frames)} order_head={names[:4]} last={names[-1] if names else '-'}")
            if not names or names[0] != "meta" or names[-1] != "done":
                failures.append("sse frame order")

        _check(f"GET /v1/trace/{trace_id or 'not-exist'}", client.get(f"/v1/trace/{trace_id or 'not-exist'}"), failures)
        _check("GET /v1/trace/not-exist", client.get("/v1/trace/not-exist"), failures)

        tools = client.get("/v1/tools")
        _check("GET /v1/tools", tools, failures)
        if tools.status_code == 200:
            print(f"        tools={len(tools.json()['tools'])}")

        evaluation = client.post("/v1/eval", json={})
        _check("POST /v1/eval {}", evaluation, failures)
        if evaluation.status_code == 200:
            body = evaluation.json()
            print(
                f"        samples={body['samples']} hit_rate={body['hit_rate']} "
                f"tool_hit_rate={body['tool_hit_rate']} avg_steps={body['avg_steps']}"
            )
            if body["samples"] != 8 or not isinstance(body["details"][0]["actual_tools"], list):
                failures.append("eval contract")

        _check("GET /", client.get("/"), failures)
        _check("GET /ui/index.html", client.get("/ui/index.html"), failures)
        _check("GET /docs", client.get("/docs"), failures)

    print("[5] 运行期产物：")
    print(f"        {ctx.paths.index_path}  exists={ctx.paths.index_path.exists()}")
    print(f"        {ctx.paths.trace_path}  exists={ctx.paths.trace_path.exists()}")

    if failures:
        print(f"=== demo FAILED：{len(failures)} 项未通过 → {failures} ===")
        return 1
    print("=== demo OK：四模态入库 / Agent 轨迹 / 全部端点冒烟通过 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
