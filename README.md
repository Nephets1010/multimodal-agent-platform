# 多模态通用智能体开发平台

四模态统一接入 → 统一表征与多模态 RAG → Planner / Worker / Reflector 智能体编排
→ 工具调用 → SSE 流式统一应答 → 轨迹回放与自动评测。

**默认 `DEMO_MODE=1`：零 API Key、零 GPU、零联网、零模型权重下载，即可端到端跑通全部链路。**
Python 3.11+ / FastAPI / Pydantic v2 / Uvicorn / 原生 JS（无前端构建工具）。

---

## 1. 快速启动

```bash
# 核心依赖（本机已预装可跳过）
python3 -m pip install -r requirements.txt

make demo        # 一键端到端：四模态入库 + Agent 轨迹 + TestClient 冒烟全部端点（不启动服务器）
make test        # pytest 全量测试
make run         # 启动服务，浏览器打开 http://localhost:8000
make eval        # 自带 8 条样例评测报告
```

> **本机 `make` 不可用**：Makefile 仍完整提供上述四个目标，命令与规格 §2 逐字一致；请直接执行下方等价 `python3` 命令，效果完全相同。

```bash
DEMO_MODE=1 python3 scripts/demo.py                                      # = make demo（不启动服务器）
DEMO_MODE=1 python3 -m pytest -q tests                                  # = make test
DEMO_MODE=1 python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000  # = make run
DEMO_MODE=1 python3 -m app.observability.evaluator                      # = make eval
```

`make demo` 不启动服务器：直接调用组合根完成四模态入库与 Agent 运行，并用 `TestClient` 冒烟所有 API 端点。运行期产物写入 `data/`（自动创建）：`vector_index.json`（向量索引）、`traces.jsonl`（轨迹日志）、`eval_report.json`（评测报告）、`tmp/`（上传临时文件，请求后清理）。

浏览器打开 `http://localhost:8000`，可完成「多模态入库 → 提问（SSE）→ 统一应答／证据／工具结果 → 回放轨迹 → 工具清单 → 运行评测」全流程；`web/index.html` 零改动。`GET /docs` 由 FastAPI 自动提供（Q13），可查看全部接口定义。

---

## 2. 架构分层

```
                      ┌──────────── 接入层 app/modalities ────────────┐
 text/image/audio/video → BaseModalityProcessor → ModalityChunk（5 字段）
   Pillow+numpy 归一      wave 元信息    cv2 抽帧（复用同一图像链路）
                      └──────────────────┬───────────────────────────┘
                      ┌──────────── 表征检索层 app/rag ──────────────┐
 BaseEncoder(Stub/API/Transformers) → VectorStore(Memory/Chroma, JSON 持久化)
 HybridRetriever = 稠密余弦 + 简化 BM25 + 重排 + 纯关键词回退
                      └──────────────────┬───────────────────────────┘
                      ┌──────────── 编排层 app/agent ────────────────┐
 build_graph() → CompiledGraph.run() / stream_events() / resume()
   Planner ──has_tool──▶ Worker ──continue──▶ Reflector ──done──▶ END
     最大步数保护 / 工具白名单 / 单工具超时 / 人工介入断点 / 状态可序列化
                      └──────────────────┬───────────────────────────┘
                      ┌──────────── 生成与观测 ──────────────────────┐
 route_output + synthesize_answer(template | LLM API) → UnifiedResponse(11 字段)
 SSE: meta / step / token / human_required / done
 AgentTracer → data/traces.jsonl       Evaluator → 命中率/步数/延迟
                      └──────────────────┬───────────────────────────┘
 FastAPI: /health /v1/ingest /v1/chat /v1/trace/{id} /v1/eval /v1/tools
          app/runtime.py::build_context() 是唯一组合根（无 FastAPI 副作用）
```

**面试讲解要点**

| 主题 | 要点 |
| --- | --- |
| 统一抽象层 | `ModalityChunk` 是唯一跨层契约；图像／视频帧被转成「颜色网格 + 感知指纹」描述性文本，音频转成 WAV 元信息 + 确定性占位转写，从而与文本共用同一个 `StubEncoder` 与向量库。新增模态只需实现 `BaseModalityProcessor.process()`；生产上换 CLIP / Milvus 的位置就是 `BaseEncoder` / `VectorStore`。 |
| LangGraph 等价降级 | `build_graph()` 是唯一入口、`CompiledGraph` 是唯一接口；`NODE_FUNCTIONS` / `EDGE_SPEC` / `CONDITIONAL_EDGES` 三份纯数据常量 + `nodes.py` 唯一一份节点函数被 `PureStateMachine` 与 `LangGraphCompiled` 共用；基类模板方法统一实现 `run` / `stream_events` / `resume`（含步数保护与 SSE 事件顺序），子类只实现 `_iterate()`。**不是两套实现。** |
| Agent 四道防线 | ① `agent.max_steps=8`，超限强制进 Reflector 收敛；② 工具白名单（仅 4 个）；③ `ThreadPoolExecutor` + `future.result(timeout=3.0)` 单工具超时；④ 人工介入断点 `resume(state, "approved")`（仅图层 API）。另加 `calculator` 受限 AST（禁 `eval`/`exec`）。 |
| 检索偏差治理 | 稠密余弦 + 简化 BM25 加权融合 → 重排（子串命中加权、同源去重限流）→ 稠密无结果或全零时自动切纯关键词回退；`last_debug.strategy ∈ {hybrid, keyword_fallback, empty}` 可观测；接近 `vector_store.soft_limit` 只告警不改检索口径。 |
| 确定性 | DEMO 分支禁用 Python 内置 `hash()`（会随 `PYTHONHASHSEED` 随机化），一律 `hashlib`；`chunk_id` / `StubEncoder` / 占位 ASR 全内容哈希；视频降级帧以 `sha256(content)[:8]` 作 `numpy.random.default_rng(seed)` 种子；排序有稳定次级键 `chunk_id`。`current_time` 是唯一非确定性来源，其输出与 `ts` / `elapsed_ms` 属观测元数据，不参与命中判定。 |

---

## 3. DEMO_MODE 与后端锁定

`get_settings()` 的合并顺序：`config/settings.yaml` → `.env`（自写解析，不覆盖已有 `os.environ`）→ `os.environ` 历史短别名 + `MAP_<SECTION>__<KEY>` 项目前缀长格式兜底覆盖 → 启动期校验 → **最后一步** `demo.enabled` 为真时无条件覆写 `llm.backend=template` / `encoder.backend=stub` / `vector_store.backend=memory`。锁定发生在配置层，不是各后端各自判断；**即使配置了 `LLM_API_KEY` / `LLM_BACKEND=api`，生效后端仍为 `template`/`stub`/`memory`，且 httpx 外部请求数为 0**。

| 配置项 | `DEMO_MODE=1` | `DEMO_MODE=0` |
| --- | --- | --- |
| `llm.backend` | 无条件锁定 `template` | `api` \| `template` |
| `encoder.backend` | 无条件锁定 `stub` | `api` \| `transformers` \| `stub` |
| `vector_store.backend` | 无条件锁定 `memory` | `chroma` \| `memory` |
| 图生效后端 | 强制 `pure` | langgraph 可用则 `langgraph`，否则 `pure` |
| `/health.components.{langgraph,...}` | 仍如实报 `native`/`fallback`（= 探测结果，**不代表启用**） | 同左 |

> `/health.components` 的 `graph` / `encoder` / `vector` / `llm` **一律报告实际生效后端**，不报配置声明值：生产模式下配置 `api`/`chroma` 但因依赖／Key 缺失降级到 `stub`/`memory`/`template` 时，组件项显示真实生效值，避免运维误判。配置声明值另放在**生产模式才附加**的顶层字段 `configured_backends`（对象），与 `fallback_flags` / `status=degraded` 一起构成降级可观测链。DEMO 下配置值==生效值，不输出 `configured_backends`，响应与前端既有消费路径完全一致。

**DEMO 十条红线**：① 零 API Key ② 零 GPU（不加载 torch/transformers 权重） ③ 零联网（httpx 0 请求） ④ 零权重下载（`local_files_only=True`） ⑤ 三后端无条件锁定 ⑥ 可选依赖只 `find_spec` 探测 + 局部 `try/except ImportError` 降级且不崩溃 ⑦ 确定性（`hashlib`） ⑧ 实现形态锁定（规则 Planner / 模板生成器 / PureStateMachine / InMemory+JSON / Pillow+numpy / wave / cv2） ⑨ `make demo` 不启动服务器、四条命令独立可跑 ⑩ 业务结果不变（模板答案四段式 / stub 特征 / 混合检索回退 / 评测口径）。

> ⚠️ **探测结果 ≠ 启用状态**：`/health.components.langgraph == "native"` 只说明包装已安装；DEMO 下 `components.graph` 必须是 `pure`。二者是独立字段。

---

## 4. 配置

主配置 `config/settings.yaml`（`config_version: 1`）。环境变量覆盖有**两种写法**：

1. **规格 §4.6 历史短别名**（优先，**不带前缀**）：`DEMO_MODE` / `HOST` / `PORT` / `LLM_BACKEND` / `ENCODER_BACKEND` / `VECTOR_BACKEND` / `HUMAN_IN_LOOP` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_VISION_MODEL` 等，行为与优先级按规格保持不变。
2. **项目前缀长格式** `MAP_<SECTION>__<KEY>`（全大写双下划线）：例如 `MAP_RETRIEVAL__DENSE_WEIGHT=0.7`、`MAP_AGENT__MAX_STEPS=8`、`MAP_SERVER__HOST=127.0.0.1`，保证「所有键可覆盖」而无须逐一列举。

> ⚠️ **长格式必须带 `MAP_` 前缀**：宿主环境可能注入与本平台无关的 `SERVER__HOST` / `SERVER__PORT` 等同名变量，裸 `<SECTION>__<KEY>` 会把它们误读为 `server.host` / `server.port`，导致 `python3 -m app.main` 悄悄绑到非预期地址（甚至与宿主端口冲突）。加项目前缀后这类变量一律不被本平台读取；**短别名按规格保留、优先级不变**。类型按 YAML 默认值自动转换，失败抛可读 `ConfigError`。

| settings 路径 | 默认值 | 历史短别名（优先） | 项目前缀长格式（`MAP_`） |
| --- | --- | --- | --- |
| `demo.enabled` | `true` | `DEMO_MODE` | `MAP_DEMO__ENABLED` |
| `server.host` / `server.port` | `0.0.0.0` / `8000` | `HOST` / `PORT` | `MAP_SERVER__HOST` / `MAP_SERVER__PORT` |
| `llm.backend` / `api_key` / `base_url` / `model` / `vision_model` | `template` / 空 | `LLM_BACKEND` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_VISION_MODEL` | `MAP_LLM__BACKEND` 等 |
| `encoder.backend` / `dim` / `local_model_path` | `stub` / `256` / 空 | `ENCODER_BACKEND` / `ENCODER_LOCAL_MODEL_PATH` | `MAP_ENCODER__DIM` 等 |
| `vector_store.backend` / `soft_limit` / `top_k` | `memory` / `10000` / `5` | `VECTOR_BACKEND` / `VECTOR_STORE_SOFT_LIMIT` | `MAP_VECTOR_STORE__TOP_K` 等 |
| `retrieval.dense_weight` / `bm25_weight` / `dense_floor` / `snippet_chars` | `0.6` / `0.4` / `1e-9` / `160` | — | `MAP_RETRIEVAL__DENSE_WEIGHT` 等 |
| `ingest.chunk_size` / `chunk_overlap` | `320` / `64` | `INGEST_CHUNK_SIZE` / `INGEST_CHUNK_OVERLAP` | `MAP_INGEST__CHUNK_SIZE` 等 |
| `ingest.max_file_bytes` / `max_total_bytes` / `max_files` | `10 MiB` / `50 MiB` / `20` | `INGEST_MAX_FILE_BYTES` 等 | `MAP_INGEST__MAX_FILES` 等 |
| `agent.max_steps` / `tool_timeout_seconds` / `max_query_chars` / `token_chunk_chars` / `human_in_loop` | `8` / `3.0` / `2000` / `24` / `false` | `AGENT_MAX_STEPS` / `AGENT_TOOL_TIMEOUT_SECONDS` / `HUMAN_IN_LOOP` | `MAP_AGENT__MAX_STEPS` 等 |
| `observability.log_level` / `trace_path` / `eval_report_path` | `INFO` / `data/traces.jsonl` / `data/eval_report.json` | — | `MAP_OBSERVABILITY__LOG_LEVEL` 等 |
| `eval.samples_path` / `default_samples` | `samples/eval.jsonl` / `8` | — | `MAP_EVAL__SAMPLES_PATH` 等 |

`.env.example` 只含占位符，**不含任何真实凭据**；复制为 `.env` 后可覆盖。所有路径基于 `app/config.py::PROJECT_ROOT`，不依赖当前工作目录；`data/` 与 `data/tmp/` 自动创建。

**上传白名单与阈值**（`config/settings.yaml`）：`text: .txt/.md/.json/.csv/.text`；`image: .png/.jpg/.jpeg/.webp/.bmp`；`audio: .wav`；`video: .mp4/.avi/.mov/.mkv/.webm`（大小写不敏感）；单文件 ≤ 10 MiB、单次总 ≤ 50 MiB、≤ 20 文件；文件名经 `Path(name).name` + 正则净化，临时文件只写 `data/tmp/` 并在 `finally` 清理，绝不写用户指定路径。

---

## 5. 接口速查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | `demo_mode` + `components`（11 项，生效后端）+ 顶层 `status`/`version`/`index_chunks`；生产模式另附顶层 `configured_backends`（配置声明值），DEMO 下不输出 |
| POST | `/v1/ingest` | multipart `files` / `text` / `source_tag` → `{chunks:[{chunk_id,source_id,modality,snippet}], total}` |
| POST | `/v1/chat` | `{query, session_id, stream, modalities}`；`stream=false` → `UnifiedResponse` 11 字段，`stream=true` → SSE |
| GET | `/v1/trace/{trace_id}` | `{events:[{event,node,steps,status,...}], count}` |
| GET | `/v1/tools` | `{tools:[{name,description,parameters}], whitelist, max_steps, tool_timeout_seconds}` |
| POST | `/v1/eval` | 可选 `{"samples":[...]}`（数组）；响应 6 字段，其中 `samples` 是**数量数字** |
| GET | `/`、`/ui/index.html` | 同源托管 `web/index.html` |
| GET | `/docs` | FastAPI 自动文档（默认开启） |

SSE 帧逐字节约定：`event: <name>\ndata: <单行 JSON>\n\n`（**禁止缩进多行 JSON**，前端逐行 `JSON.parse` 会静默吞错）；顺序 `meta → step* → token* → [human_required] → done`；`done` 恒存在、恒为最后一帧，携带完整 11 字段 `UnifiedResponse`，且与非流式由同一个 `build_unified_response()` 产出；所有 `token.delta` 拼接后等于 `done.answer`。

`UnifiedResponse` **11 字段完整枚举**（不得删改／重命名；非流式响应与 SSE `done` 字段集合一致）：`answer` / `evidences[]`（`chunk_id`·`modality`·`snippet`·`score`） / `tool_calls[]`（`name`·`arguments`） / `tool_results[]`（`name`·`ok`·`elapsed_ms`·`output`·`error`，`error` 成功时仍存在取 `null`） / `trace_id` / `steps` / `elapsed_ms` / `status` / `output_modality` / `demo_mode` / `graph_backend`。

---

## 6. 已知限制（如实披露，本期不偷偷补齐）

> ### ⚠️ 安全与部署边界
> **未实现鉴权、多租户、会话持久化与并发写入锁。** 本平台**仅限本机或可信内网单机演示，勿暴露公网**。`/v1/chat` 的流式请求与入库请求共享进程内索引，无并发写入保护（Q15 单机假设）。启动日志会打印同样的告警。
>
> **`0.0.0.0` 暴露风险**：规格 §2 与 Makefile `run` 目标保持 `--host 0.0.0.0 --port 8000`，会监听所有网卡。若只在本机使用，请收紧监听：
> ```bash
> HOST=127.0.0.1 PORT=8000 DEMO_MODE=1 python3 -m app.main
> ```
> `HOST` / `PORT` 短别名由配置层读取，`app/main.py` 的 `__main__` 分支据此传给 `uvicorn.run`；长格式请用 `MAP_SERVER__HOST` / `MAP_SERVER__PORT`。
> 注意：**长格式已统一加 `MAP_` 项目前缀**，宿主环境注入的 `SERVER__HOST` / `SERVER__PORT` 等无关同名变量不会被本平台读取，因此 `python3 -m app.main` 默认仍绑到规格的 `0.0.0.0:8000`；Makefile `run` 更以命令行 `--host 0.0.0.0 --port 8000` 显式固定，优先级最高。

* **DEMO 语义质量 ≠ 真实多模态大模型**：DEMO 使用确定性 stub 特征与模板答案，命中率等指标**只用于链路正确性与回归验证，不代表业务准确率**，不得据此对外宣称模型效果。
* **SSE `token` 为定长切片模拟**：本期未实现 `LLMClient.chat_stream`；原始规格 §8 曾提及该接口，本仓库未包含该类／方法；SSE `token` 恒由最终答案按 `agent.token_chunk_chars=24` 定长切片模拟；本期不新增该能力（原 PRD P2-4）。
* **图像／音频／视频仅产出描述性文本证据**：不做真实图像生成、TTS 或 ASR；音频仅解析 PCM WAV 容器；视频容器不可解码时降级为确定性合成帧。
* **内存向量库为暴力余弦扫描**：适合万级以下切片；`soft_limit=10000` 接近时只告警不改口径，生产建议切换 Chroma / Milvus。
* **`samples/eval.jsonl` 为自建 8 条小型基准**：不含公开榜（MMBench / SEED）评测，也未使用 LLM-as-judge。
* **评测口径（Q9）**：`hit = expected_keywords 全部出现在 answer 且 expected_tools ⊆ actual_tools`；`expected_answer_contains` 是 schema 字段但**不参与判定**；请求 `samples` 是数组、响应 `samples` 是数量数字（同名不同义按现状保持）；`details[].actual_tools` 必须是数组。
* **Q7 · trace 不存在返回 200 空集**：`GET /v1/trace/{id}` 查不到时返回 HTTP **200** `{"events":[],"count":0}` 并写 warning 日志，**不是 404**。
* **Q10 · human_required 与 resume()**：`human_required` 帧（仅 `HUMAN_IN_LOOP=1`）插在最后一个 `step`/`token` 之后、`done` 之前，且不替代 `done`；**本期不提供 REST 恢复端点**，`resume(state, "approved")` 仅为图层 API，由 `scripts/demo.py` 演示，浏览器无法通过 HTTP 恢复。
* **Q15 · 无并发锁**：只读环境或多进程写入下 `data/` 可能不可写，此时抛可读 `ConfigError`；不提供多进程一致性保证。
* **无输入鉴权与配额**：所有端点对外开放，请勿在公网或不可信网络暴露（见上方安全边界）。
* **`docs/reference/` 是目标态设计基线**：该目录为上游原始规格原文，字节级零改动，描述的是目标态设计而非本期实现状态；实际实现状态以本 README（尤其 §6 已知限制）与 `docs/PRD.md` §4 契约红线为准，两者口径不一致处以本节的如实披露为准。

---

## 7. 测试与工程基线

```bash
DEMO_MODE=1 python3 -m pytest -q tests
```

八组 pytest（四组基础：`test_modalities.py` / `test_rag.py` / `test_agent.py` / `test_api.py`；四组增量边界／配置回归：`test_edge_api.py` / `test_edge_security.py` / `test_edge_agent_rag.py` / `test_config_env.py`）+ `conftest.py` 隔离 fixture，`DEMO_MODE=1 python3 -m pytest -q tests` 实测 **139 passed**（0 failed，1 条无害的 `StarletteDeprecationWarning`），覆盖四模态入库、混合检索命中与全零回退、三节点与 4 工具、受限 AST 与白名单、工具超时、超 `max_steps`、SSE 帧序列与 `done` 11 字段、trace 回放、8 条评测样例、`/health` 组件探测与降级标记；边界覆盖空／超长 query、未知扩展名与畸形文件、非法 JSON、空索引与损坏索引、`trace_id` 不存在、SSE 客户端断连、可选依赖缺失（monkeypatch `find_spec` 返回 None／抛异常时全 fallback 不崩溃）、配置 Key 但仍 DEMO。测试用 `tmp_path` 隔离 `data/`，**不污染仓库运行期文件，可重复运行**。

工程基线：结构化 JSON 行日志（stdout，含 `ts`/`level`/`event`/`component`/`trace_id`/`message`）+ 三出口强制脱敏（日志 Formatter、轨迹落盘前、HTTP 异常响应）；异常统一 `{"detail": "可读中文"}`，堆栈只以 `exc_info` 进脱敏日志、绝不直出响应；配置版本化与启动期校验；`calculator` 受限 AST + 工具白名单 + 上传护栏；`ThreadPoolExecutor` 单工具超时、最大步数收敛、SSE 断连资源释放。

## 8. 开源与社区

### 8.1 徽章与许可证

| 徽章 | 说明 |
| --- | --- |
| CI | `![CI](__CI_BADGE_URL__)`，链接到 `__REPO_URL__/actions/workflows/ci.yml`；`__CI_BADGE_URL__` 由 `__REPO_URL__` 单向派生 |
| License | **Apache-2.0**，见 `LICENSE`（完整原文）与 `NOTICE`（版权与依赖归属） |

本项目采用 **Apache License 2.0**；`pyproject.toml` 的 `license`、`CITATION.cff` 的 `license`、
`NOTICE` 与本节措辞完全一致。`LICENSE` 为完整原文、条款零改写；再分发时请保留版权与许可声明，
并按 Apache-2.0 要求标注变更（见 `CHANGELOG.md`）。

### 8.2 克隆与快速开始

```bash
git clone __REPO_URL__
cd __REPO_NAME__
python3 -m pip install -r requirements.txt
```

克隆后直接按 §1 的四条等价命令运行（本机 `make` 不可用时请用 `python3` 命令）；
`DEMO_MODE=1` 下零 API Key、零 GPU、零联网、零权重下载。仓库地址与目录名均为占位符，
登记与替换方式见 `docs/REPO_METADATA.md`。

### 8.3 能力边界与定位

本项目面向**求职作品集／实训**，是可运行、可复现、可维护的全链路演示：
四模态统一接入 → 统一表征与多模态 RAG → Planner／Worker／Reflector 编排 → 工具调用 →
SSE 统一应答 → 轨迹回放与自动评测。

- **DEMO stub 语义质量不等价于真实多模态大模型**；命中率等指标只用于链路正确性与回归验证，
  不代表业务准确率。
- 图像／音频／视频 DEMO 仅产出描述性文本证据；SSE `token` 为定长切片模拟；
  本期未实现 `LLMClient.chat_stream`（见 §6）。
- 本项目是教学演示用途：未实现鉴权／多租户／会话持久化／并发写入锁，
  仅限本机或可信内网单机演示，勿暴露公网。

### 8.4 贡献方式

贡献流程、代码风格、零改动清单与测试要求见 `CONTRIBUTING.md`；
四条 DEMO 等价命令见 §1。Issue／Pull Request／CI 检查链接由 `__REPO_URL__` 派生，
统一登记在 `docs/REPO_METADATA.md`。提交前请确保
`DEMO_MODE=1 python3 -m pytest -q tests` 与 `python3 -m compileall -q app scripts tests` 全绿。

### 8.5 行为准则

社区行为准则见 `CODE_OF_CONDUCT.md`（自写精简版：适用范围／行为准则／举报渠道）。
举报请走私密渠道 `__SECURITY_CONTACT__`，不要在公开 Issue 中讨论具体举报内容。

### 8.6 安全披露

安全报告渠道、响应预期与已知设计边界见 `SECURITY.md`。此处复述最重要的部署边界：

> **未实现鉴权、多租户、会话持久化与并发写入锁，属已知设计边界而非漏洞；
> 仅限本机或可信内网单机演示，勿暴露公网。**

Makefile `run` 目标保持 `--host 0.0.0.0 --port 8000`，会监听所有网卡；
若只在本机使用，请收紧监听：

```bash
HOST=127.0.0.1 PORT=8000 DEMO_MODE=1 python3 -m app.main
```

`LLM_API_KEY`／Bearer Token／上传文件正文一律不得进入 Issue、PR、日志或轨迹（见 §6 与 `SECURITY.md`）。

### 8.7 引用与变更

- 引用本软件：见 `CITATION.cff`（CFF 1.2.0，可用 PyYAML 解析）。
- 变更记录：见 `CHANGELOG.md`（Keep a Changelog 风格，`[1.0.0]` 记录本期补齐）。
- 版本比较与 Release 链接由 `__REPO_URL__` 派生，发布日期用 `__RELEASE_DATE__` 占位符，
  均登记在 `docs/REPO_METADATA.md`。

### 8.8 致谢

感谢 `requirements.txt` 中 10 个核心依赖与 6 个可选依赖的上游维护者，
完整归属清单见 `NOTICE`。本项目在 `DEMO_MODE=1` 下不安装可选依赖、不加载任何模型权重，
也不依赖第三方 API；DEMO 链路的能力来自这些基础库与自建的确定性 stub 实现，
不夸大效果、不宣称模型准确率。

> 本节全部 URL 与身份字段使用 `docs/REPO_METADATA.md` 登记的占位符；
> 地址到位后由维护者执行 S2 一次性全量替换，**替换完成前不得推送**。

---

> 目录结构、端点路径／字段、`web/index.html` / `requirements.txt` / `samples/knowledge.txt` 均按原始规格保持零改动。
