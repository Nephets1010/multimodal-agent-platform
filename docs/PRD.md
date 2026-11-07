# 多模态通用智能体开发平台 · 产品需求文档（PRD）

| 项 | 值 |
| --- | --- |
| 文档类型 | 简单 PRD（增量交付，不含竞品／市场分析） |
| 版本 | v1.0 |
| 编写 | 产品经理 许清楚（Xu） |
| 语言 | 简体中文（与用户需求一致） |
| 行为契约 | `docs/reference/platform-spec-README.md`（主）、`docs/reference/design-project10.md`（辅）、`requirements.txt`、`samples/knowledge.txt`、`web/index.html` |
| 交付形态 | 本机从零实现完整项目源码；**不做远端推送** |

> 下游交接提示：架构师重点看 §1.2、§4；工程师重点看 §3、§4、§5；QA 重点看 §3 验收列、§4.5、§5-NF4、§7。

---

## 0. 项目信息

| 项 | 值 |
| --- | --- |
| Language | 简体中文 |
| Programming Language | Python 3.11 + FastAPI + Pydantic v2 + Uvicorn + httpx；前端原生 JS，**无构建工具**（用户锁定，不套用默认 Vite + React + MUI + Tailwind） |
| Project Name | `multimodal_agent_platform` |
| 核心依赖基线（不得新增必需依赖） | `fastapi>=0.110`、`uvicorn>=0.27`、`pydantic>=2.0`、`python-multipart>=0.0.9`、`numpy>=1.24`、`pillow>=10.0`、`PyYAML>=6.0`、`httpx>=0.27`、`pytest>=8.0`、`opencv-python-headless>=4.8` |
| 可选依赖（仅探测降级，不得写成必需） | `langgraph`、`chromadb`、`openai-whisper`、`transformers`(+`torch`)、`openai` |
| 探测方式 | 仅 `importlib.util.find_spec` + `try/except ImportError`，缺失走内置等价实现并标记 `fallback` |

**当前现状（已核实，非推测）**：本机仅存在 5 个文件——两份参考文档、`requirements.txt`、`samples/knowledge.txt`、`web/index.html`。**不存在** `app/` 源码、`config/settings.yaml`、`samples/eval.jsonl`、`Makefile`、`README.md`、`.env.example`、`scripts/demo.py`、`tests/`、`data/`。全部为本次需从零实现的交付物。

**原始需求复述**：用户要求对「多模态通用智能体开发平台」做企业级交付；经核实本机无任何项目源码，用户明确「没有源码，按照文档进行开发」，且明确「暂不推送」。因此本次以资料库文档为**唯一行为契约**从零实现完整项目，并把代码质量、模块结构可维护性、性能、安全性、错误处理、日志、测试覆盖、配置管理、文档一次性做到企业级标准。

---

## 1. 产品目标与范围边界

### 1.1 产品目标（3 个正交目标）

- **G1 契约零漂移**：对外接口、交互流程、数据格式、业务结果、配置兼容性 100% 对齐文档；现有 `web/index.html` 无需任何改动即可跑通全链路。
- **G2 零依赖可复现**：`DEMO_MODE=1` 下零 API Key、零 GPU、零联网、零权重下载端到端跑通；全链路确定性可复现、轨迹可回放、评测可量化。
- **G3 企业级工程基线**：在**不触碰契约**的前提下，一次性把异常处理、结构化日志与脱敏、配置分层、测试与边界覆盖、性能护栏、上传安全护栏、文档做到可交付标准。

### 1.2 「文档即契约」定义（红线总则）

**不得改变**（任一改变均视为违约，须回报主理人并经用户确认后方可进行）：

1. 对外接口：§4.1 的 7 组 REST 端点之路径、HTTP 方法、请求字段、响应字段集合。
2. 交互流程：入库 → 混合检索问答 → SSE 流式 → 轨迹回放 → 自动评测 的时序与前端交互。
3. 数据格式：`UnifiedResponse` 字段清单、`ModalityChunk` 五字段（`chunk_id` / `source_id` / `modality` / `content` / `metadata`）、SSE 帧格式与事件顺序、JSONL 轨迹格式。
4. 业务结果：DEMO 模板答案结构（结论 + 工具结果 + 引用证据 + 推理轨迹）、stub 确定性特征、混合检索回退策略、评测指标口径。
5. 配置兼容性：`DEMO_MODE` 优先级、§4.6 既有配置键名与取值、`.env` 覆盖规则。
6. 前端调用契约：`web/index.html` 调用的接口与消费的数据格式一字不改。
7. 已知限制：**无鉴权、无会话持久化、无并发写入锁**等须如实披露，不得偷偷补齐、也不得偷偷改变行为。

**允许且仅允许改变**（企业级增量，不得外溢为契约变更）：

- 补齐文档已描述但当前缺失的全部交付物：`app/` 全量源码、`config/settings.yaml`、`samples/eval.jsonl`、`tests/`、`scripts/demo.py`、`Makefile`、`README.md`、`.env.example`、`data/`（运行期生成 `vector_index.json` / `traces.jsonl`）。
- 在**内部实现层**增加：统一异常处理、结构化日志与脱敏、配置分层校验、测试与边界覆盖、性能护栏、上传安全护栏、注释与文档。
- 内部模块划分与重构，只要 `platform-spec-README.md` §6 目录结构对外可见部分保持一致（不得增删顶层模块或改名）。

---

## 2. 用户故事

| 编号 | 角色 | 用户故事 | 对应契约 |
| --- | --- | --- | --- |
| US-1 | 答辩演示者 | 作为答辩演示者，我希望一次性上传文本／图像／音频／视频，或直接粘贴文本并按 `source_tag` 标记入库，以便展示「四模态统一接入」能力 | EP-2、§4.5 |
| US-2 | 终端用户 | 作为用户，我希望提问后系统用稠密余弦 + 简化 BM25 混合检索并给出带 `evidences[]` 的统一答案，以便答案可溯源、避免纯向量误召回 | EP-3、§4.3 |
| US-3 | 终端用户 | 作为用户，我希望提问中的算术／时间／统计／检索意图被自动规划并调用白名单工具，以便得到可校验的结构化结果（如 `12*8=96`） | EP-3、EP-5 |
| US-4 | 答辩演示者 | 作为演示者，我希望看到 `meta → step → token → done` 的实时事件流，以便直观展示 Planner／Worker／Reflector 推理过程与增量答案 | §4.4 |
| US-5 | 评审者 | 作为评审者，我希望凭 `trace_id` 回放完整 JSONL 轨迹，以便复盘每一步节点、状态快照、耗时与降级情况 | EP-4 |
| US-6 | 答辩者 | 作为答辩者，我希望一键运行自带样例集得到命中率／平均步数／平均延迟，以便量化复盘与回归验证 | EP-6 |
| US-7 | 运维／评审者 | 作为运维或评审者，我希望 `/health` 逐一报告每个可选依赖是 `native` 还是 `fallback` 及当前生效后端，以便在零依赖环境确认全链路降级不崩溃 | EP-1、§4.5 |

---

## 3. 需求池

优先级定义：**P0 = Must have（阻塞验收）**、**P1 = Should have**、**P2 = Nice to have／后续版本**。P0 逐条给出验收标准。

### 3.1 P0（Must have，逐条可验收）

| 编号 | 需求 | 验收标准 |
| --- | --- | --- |
| P0-1 | 四模态接入与入库：`BaseModalityProcessor` 统一产出 `ModalityChunk`；POST `/v1/ingest` 支持多 `files` + `text` + `source_tag`，按扩展名／MIME 识别模态，返回 `total` 与 `chunks[].modality` | `make demo` 自生成四种样例资源全部入库成功，`total > 0` 且 text／image／audio／video 各 ≥ 1 个切片；DEMO 下图像走 Pillow 归一 + numpy 颜色网格／感知指纹，音频走 `wave` 元信息 + 确定性占位 ASR，视频走 cv2 抽帧并复用图像链路 |
| P0-2 | 混合检索问答：稠密余弦 + 简化 BM25 + 重排（子串命中加权、同源去重）+ 文本回退；稠密无结果或全零时自动切纯关键词回退且 `last_debug.strategy` 可观测；空索引启动时自动灌入 `samples/knowledge.txt` | 检索「混合检索说明」类问题命中内置知识切片，`evidences[]` 非空；构造全零得分场景可观察到回退策略标记 |
| P0-3 | Agent 编排与工具调用：`build_graph()` 唯一入口、`CompiledGraph` 唯一接口；Planner → Worker → Reflector 条件边；4 个内置工具带 JSON Schema、参数校验、白名单、单工具超时；最大步数保护 | `POST /v1/chat` 发 `{"query":"计算 12*8 的结果","stream":false}` 返回 `answer` 含 96，`tool_results[]` 含 `calculator` 且 `ok=true`；`GET /v1/tools` 返回 4 个工具 |
| P0-4 | 统一应答与 SSE：`stream=false` 返回完整 `UnifiedResponse`；`stream=true` 返回 SSE，事件顺序与 §4.4 一致，`done` 携带完整 `UnifiedResponse` | 前端勾选 SSE 能实时显示 `step` 轨迹、`token` 增量、`done` 渲染；非流式响应与 `done` 事件的字段集合一致，无缺字段 |
| P0-5 | 轨迹落盘与回放：每步写 `data/traces.jsonl`（含 `trace_id`、节点名、状态快照、耗时）；`GET /v1/trace/{trace_id}` 返回 `events[]` 与 `count` | 一次 chat 后用其 `trace_id` 回放，`count` ≥ 该轮步数，`events[]` 顺序与执行顺序一致 |
| P0-6 | 自动评测：`POST /v1/eval` 不传 `samples` 时用 `samples/eval.jsonl`（8 条）；返回 `hit_rate` / `tool_hit_rate` / `avg_steps` / `avg_latency_ms` / `samples` / `details[]` | `make eval` 输出报告，`samples=8`，DEMO 下指标可复现（同输入多次运行一致） |
| P0-7 | 健康检查与降级观测：`GET /health` 返回 `demo_mode` 与 `components`（逐项 `native`／`fallback`、当前生效后端、`index_chunks`） | 不安装任何可选依赖时 `/health` 全部标记 `fallback`，服务不崩溃，前端健康面板正常渲染 |
| P0-8 | `DEMO_MODE=1` 零依赖红线：严格满足 §4.5 全部 10 条约束 | 断网 + 未配置任何 API Key + 未安装任何可选依赖下，`make demo`、`make test`、`make run`、`make eval` 全部通过；配置 `LLM_API_KEY` 后仍不发出任何网络请求 |
| P0-9 | UI 同源托管与前端契约不变：`GET /` 与 `GET /ui/index.html` 返回现有 `web/index.html` | 浏览器打开 `http://localhost:8000`，可完成入库 → 提问（SSE）→ 统一应答／证据／工具结果 → 回放轨迹 → 工具清单 → 运行评测全流程；`web/index.html` 文件零改动 |
| P0-10 | 配置分层与环境可控（NF-3）：`config/settings.yaml` + 环境变量覆盖 + `.env.example`，`DEMO_MODE` 优先级最高 | `DEMO_MODE=1` 下即使 `.env` 填了 `LLM_API_KEY`／`LLM_BACKEND=api`，生效后端仍为 `template`／`stub`／`memory` |
| P0-11 | 错误处理与异常反馈（NF-1）：所有端点对非法输入／单模态失败／工具超时／索引损坏返回明确结构化错误且不崩溃 | 注入畸形文件、非法 JSON、超长 query、工具超时、损坏索引文件，服务仍可用并给出可读错误；可选依赖 `ImportError` 自动降级并标记 `fallback` |
| P0-12 | 结构化日志与脱敏（NF-2）：JSON 行日志、`trace_id` 贯穿、API Key 等敏感信息不落日志／轨迹／响应 | 配置 `LLM_API_KEY` 后检索全部日志与 `data/traces.jsonl`，不出现 Key 明文；每条请求日志可按 `trace_id` 串联 |
| P0-13 | 测试覆盖与边界场景（NF-4）：`tests/` 四组 pytest（模态／RAG／Agent／API）+ 边界用例 | `DEMO_MODE=1 python3 -m pytest -q tests` 退出码 0；覆盖 §5-NF4 列出的关键路径与边界场景 |
| P0-14 | 性能护栏（NF-5）：暴力扫描软上限、单工具 `ThreadPoolExecutor` 超时、最大步数收敛、SSE 断连资源释放 | 超过软上限有明确告警且不改变检索结果口径；工具超时返回结构化失败且链路继续；`agent.max_steps` 超限时强制进入 Reflector 收敛 |
| P0-15 | 安全护栏（NF-6）：`calculator` 受限 AST、工具白名单、上传扩展名／MIME 白名单与大小／路径限制；**无鉴权限制如实披露** | 受限 AST 拒绝函数调用／属性访问／任意名称解析；未注册工具被拒；路径穿越文件名被净化；README 与启动日志明确披露「未实现鉴权，仅限本机／可信内网单机演示」 |

### 3.2 P1（Should have）

| 编号 | 需求 | 说明 |
| --- | --- | --- |
| P1-1 | 生产模式可选后端可用性 | `LLM_BACKEND=api`／`ENCODER_BACKEND=api\|transformers`／`VECTOR_BACKEND=chroma`／langgraph／whisper 在依赖齐备时启用，失败一律回退 `template`／`stub`／`memory` 且不崩溃；配置键与取值不得改变 |
| P1-2 | 可观测增强 | `last_debug.strategy`、`elapsed_ms` 分段、`/health` 中 `index_chunks` 实时刷新，便于答辩复盘 |
| P1-3 | 工程文档齐备 | `README.md`（快速启动、架构、已知限制、无鉴权披露）、`Makefile`（demo/test/run/eval）、`.env.example`、`/docs` 自动文档可用 |
| P1-4 | 评测报告可导出 | 评测结果结构化落盘／可复用，不改变 `/v1/eval` 响应字段集合 |

### 3.3 P2（Nice to have／后续版本，本期明确不做）

| 编号 | 需求 | 本期处置 |
| --- | --- | --- |
| P2-1 | 公开榜（MMBench／SEED）与 LLM-as-judge | 文档 §8 明确自建 8 条基准不含公开榜；本期不擅自扩充，避免改变评测口径 |
| P2-2 | CLIP／Milvus／多智能体／TTS／文生图扩展点 | 文档列为「答辩加分区」可扩展点；本期仅保证抽象层可插拔，不实现 |
| P2-3 | 鉴权／多租户／会话持久化／并发写入锁 | **文档明确未实现，本期不实现、不偷偷补**，仅如实披露；属后续版本候选 |
| P2-4 | 将 `LLMClient.chat_stream` 真实增量输出挂到主应答路径 | 本期未实现 `LLMClient.chat_stream`；原始规格 §8 曾提及该接口，本仓库未包含该类／方法；SSE `token` 恒由最终答案按 `agent.token_chunk_chars=24` 定长切片模拟；本期不新增该能力（原 PRD P2-4） |

---

## 4. 契约红线章节（重点）

> 字段来源标注：**【规格】** = `platform-spec-README.md` / `samples/knowledge.txt` / `requirements.txt`；**【前端】** = `web/index.html` 实际读取或发送的字段（既成事实契约）；**【待确认】** = 文档与前端均未明确，列入 §7，实现时不得臆造。
> SSE 与响应体一律以 §4.3／§4.4 字段集合为准；**允许新增不影响现有消费方的内部字段，但不得删改、不得重命名既有字段**。

### 4.1 端点总表（7 组）

| 编号 | 方法 | 路径 | 请求 | 响应 | 说明 |
| --- | --- | --- | --- | --- | --- |
| EP-1 | GET | `/health` | 无 | JSON | 健康状态、组件降级情况、索引切片数 |
| EP-2 | POST | `/v1/ingest` | `multipart/form-data` | JSON | 四模态入库 |
| EP-3 | POST | `/v1/chat` | JSON | JSON 或 SSE | 问答（`stream=true` 返回 SSE） |
| EP-4 | GET | `/v1/trace/{trace_id}` | 路径参数 | JSON | 回放完整 JSONL 轨迹 |
| EP-5 | GET | `/v1/tools` | 无 | JSON | 工具 JSON Schema 与生效白名单 |
| EP-6 | POST | `/v1/eval` | 可选 JSON | JSON | 自动评测 |
| EP-7 | GET | `/`、`/ui/index.html` | 无 | `text/html` | 单页 Web UI，同源托管、无跨域 |

附注：`GET /docs` 由 FastAPI 自动提供【规格 §5】，是否纳入契约端点保护见 Q13。所有端点同源，无跨域配置。

### 4.2 逐端点请求／响应字段

**EP-1 GET /health**
- 请求：无参数。
- 响应 `demo_mode`（bool）【前端】：前端据此切换「DEMO_MODE=1 · 零依赖」／「生产模式」徽标。
- 响应 `components`（object）【规格 §4 + 前端】：
  - `graph` / `encoder` / `vector` / `llm`【前端】：当前生效的图后端／编码器／向量库／生成器。
  - `index_chunks`（number）【规格 + 前端】：索引切片数。
  - `langgraph` / `chromadb` / `whisper` / `cv2` / `transformers` / `openai`【规格 + 前端】：逐一报告 `native` 或 `fallback`。
- 顶层是否另有 `status`／`ok`／`version`：→ Q1。

**EP-2 POST /v1/ingest**
- 请求 `multipart/form-data`：`files`（可多传，按扩展名／MIME 识别模态）、`text`、`source_tag`【规格 §5】；前端实际发送 `files` / `text`（非空时）/ `source_tag`（默认 `webui`）【前端】。
- 响应 `total`（number，切片总数）【前端】；`chunks[]`（数组，元素至少含 `modality`）【前端】；错误时 `detail`【前端】。
- `chunks[]` 元素其余字段、错误响应结构：→ Q2。上传安全白名单与阈值：→ Q3。

**EP-3 POST /v1/chat**
- 请求 JSON：`query`（必填）、`session_id`、`stream`（bool）、`modalities`（数组，空 = 全部模态）【规格 §5 + 前端】。
  - 前端构造体：`{query, session_id (默认 "default"), stream (默认勾选 true), modalities ([] 或 [单选模态])}`【前端】。
  - 规格 curl 示例：`{"query":"计算 12*8 的结果","stream":false}`、`{"query":"介绍一下平台","stream":true}`【规格 §5】。
- 响应：`stream=false` → 完整 `UnifiedResponse`（`application/json`）；`stream=true` → `text/event-stream`，帧格式见 §4.4。
- `status`／`output_modality`／`graph_backend` 枚举取值、`modalities` 缺省与空数组是否等价、`session_id` 在无会话持久化下的语义：→ Q4。

**EP-4 GET /v1/trace/{trace_id}**
- 请求：路径参数 `trace_id`（前端 `encodeURIComponent` 后拼接）【前端】。
- 响应 `events[]`（元素含 `event`、`node`、`steps`、`status`）【前端】；`count`（number）【前端】；语义为「回放完整 JSONL 轨迹」【规格 §5】。
- `events[]` 元素其余字段、`trace_id` 不存在时的行为：→ Q7。

**EP-5 GET /v1/tools**
- 请求：无参数。
- 响应 `tools[]`（元素含 `name`、`description`、`parameters`）【前端】；语义为「工具 JSON Schema 与生效白名单」【规格 §5】。
- 内置 4 个工具【规格 `samples/knowledge.txt`】：`calculator`（受限 AST 安全四则运算）、`current_time`（UTC 与本地时间）、`knowledge_search`（调用混合检索器）、`text_stats`（字数统计与抽取式摘要）；全部带 JSON Schema 描述与参数校验。
- 「生效白名单」字段名与结构：→ Q8。

**EP-6 POST /v1/eval**
- 请求：可选 `{"samples":[...]}`；不传则用 `samples/eval.jsonl`（自建 8 条）【规格 §5／§8】；前端发送 `{}`【前端】。
- 响应 `hit_rate` / `tool_hit_rate` / `avg_steps` / `avg_latency_ms` / `samples`（数量）/ `details[]`【前端】；`details[]` 元素含 `hit`、`query`、`actual_tools[]`、`steps`、`latency_ms`【前端】；指标口径为「命中率／平均步数／平均延迟」【规格 §1／§5】。
- 注意：请求体 `samples` 为**数组**，响应 `samples` 为**数量数字**，同名不同义，须按现状保持：→ Q9。

**EP-7 GET / 与 GET /ui/index.html**
- 请求：无参数。
- 响应：`text/html`，内容为现有 `web/index.html`，同源托管、无跨域【规格 §1／§5】。
- 前端已实现 `esc()` 转义、SSE 分帧、健康降级面板，后端须满足其既有假设，见 §6。

### 4.3 UnifiedResponse 字段清单（11 项，不得删改／重命名）

| 字段 | 结构／含义 | 来源 | 前端消费 |
| --- | --- | --- | --- |
| `answer` | string；模板式「结论 + 工具结果 + 引用证据 + 推理轨迹」 | 【规格】 | ✓ |
| `evidences[]` | 证据块，至少含 `chunk_id` / `modality` / `snippet` / `score` | 【规格】 | ✓ |
| `tool_calls[]` | 工具调用记录 | 【规格】 | 未消费 |
| `tool_results[]` | 工具结果；前端读取 `name` / `ok` / `elapsed_ms` / `output` / `error` | 【规格 + 前端】 | ✓ |
| `trace_id` | string | 【规格】 | ✓ |
| `steps` | number | 【规格】 | ✓ |
| `elapsed_ms` | number | 【规格】 | ✓ |
| `status` | string（枚举取值待确认 → Q4） | 【规格】 | ✓ |
| `output_modality` | string（枚举取值待确认 → Q4） | 【规格】 | ✓ |
| `demo_mode` | bool | 【规格】 | 未消费（`/health` 中消费同名 bool） |
| `graph_backend` | string | 【规格】 | ✓ |

`evidences[]` 是否含 `source_id`／`content`，`tool_calls[]`／`tool_results[]` 元素完整字段：→ Q5、Q6。

### 4.4 SSE 事件类型与顺序

**帧格式（前端既成事实，不得改变）**【前端】：每帧形如 `event: <name>` 行 + `data: <单行 JSON>` 行，帧间以空行 `\n\n` 分隔；前端 `parseFrame()` 按 `\n\n` 切帧、逐行解析 `event:`／`data:` 并 `JSON.parse`。

**事件顺序**：

```
meta (1 次)
  → step (每个节点 1 次，共 1..n)
  → token (答案分片 1..n，由最终答案按定长切片模拟)
  → [ human_required (仅 HUMAN_IN_LOOP=1 时额外产生) ]
  → done (1 次，携带完整 UnifiedResponse)
```

【规格 §5】原文：`meta → step（每个节点）→ token（答案分片）→ done（完整 UnifiedResponse）；开启 HUMAN_IN_LOOP 时额外产生 human_required，可用 graph.resume(state, "approved") 继续`。

**各事件 `data` 字段**【前端】：

| 事件 | data 字段 | 前端行为 |
| --- | --- | --- |
| `meta` | `trace_id`、`backend` | 记录 `trace_id=... backend=...` |
| `step` | `steps`、`node`、`next_node`、`status`、`last_observation` | 追加到实时轨迹面板 |
| `token` | `delta` | 追加到答案区 |
| `human_required` | `prompt` | 提示「需要人工确认」 |
| `done` | 完整 `UnifiedResponse` | 直接传给 `renderResult()` 渲染全部元数据／证据／工具结果 |

`human_required` 确切插入位置、以及 `HUMAN_IN_LOOP=1` 时 `resume(state, "approved")` 的 REST 触发方式：→ Q10。规格未给出恢复端点，本期不得擅自新增改变交互流程的端点。

### 4.5 DEMO_MODE=1 强制约束（10 条，逐条为验收红线）

1. **零 API Key**：即使配置了 `LLM_API_KEY`，也不读取、不发起任何网络请求。
2. **零 GPU**：不加载 `torch`／`transformers` 权重，不调用 CUDA。
3. **零联网**：LLM／Embedding／图像描述／ASR 全部走内置实现；`httpx` 不得发出外部请求。
4. **零权重下载**：`transformers` 编码器仅从 `config/settings.yaml` 的 `encoder.local_model_path` 本地目录加载（`local_files_only=True`），DEMO 下不启用。
5. **后端无条件锁定**：`get_settings()` 无条件把 `llm_backend`／`encoder_backend`／`vector_backend` 锁定为 `template`／`stub`／`memory`，任何配置覆盖均不生效。
6. **可选依赖只探测不硬依赖**：`langgraph`／`chromadb`／`whisper`／`openai`／`transformers` 启动时仅 `importlib.util.find_spec` 探测 + `try/except ImportError` 降级；缺失走内置等价实现并在 `/health` 标记 `fallback`，**程序绝不崩溃**。
7. **确定性可复现**：编码器 `StubEncoder` = `hashlib` 哈希词频 + 字符分布 + L2 归一化；**禁用 Python 内置 `hash()`**（会随机化），一律 `hashlib`；视频降级帧用内容哈希做 numpy RNG 种子。
8. **实现形态锁定**：Planner 规则式（算术／时间／统计／检索关键字识别）；生成器模板式；图编排 `PureStateMachine`；向量库 `InMemoryVectorStore` + JSON 持久化；图像 Pillow 归一 + numpy 颜色网格／感知指纹；音频 `wave` 元信息 + 确定性占位 ASR；视频 cv2 抽帧、不可解码时内容哈希合成帧。
9. **端到端可跑通**：`make demo` / `make test` / `make run` / `make eval` 四条命令均可独立运行；其中 **`make demo` 不需要启动服务器**，直接调用组合根完成四模态入库 + Agent 运行，并用 `TestClient` 冒烟所有 API 端点；`make run` 启动服务供浏览器访问；运行期产物写 `data/vector_index.json`、`data/traces.jsonl`。
10. **业务结果不变**：模板答案结构、stub 特征、混合检索回退策略、评测指标口径均须保持；指标仅用于链路正确性与回归验证，不代表业务准确率。

### 4.6 配置键兼容性（不得改名／改取值域）

| 配置 | 取值／说明 | 来源 |
| --- | --- | --- |
| `DEMO_MODE` | 默认 `1`；`0` = 生产；优先级最高 | 【规格】 |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` | OpenAI 兼容端点与凭据 | 【规格 §4】 |
| `LLM_BACKEND` | `api` \| `template` | 【规格 §4】 |
| `ENCODER_BACKEND` | `api` \| `transformers` \| `stub` | 【规格 §4】 |
| `VECTOR_BACKEND` | `chroma` \| `memory` | 【规格 §4】 |
| `HUMAN_IN_LOOP` | `1` 开启人工介入断点 | 【规格 §4／§5】 |
| `LLM_VISION_MODEL` | 图像 VLM 描述，留空复用 `LLM_MODEL` | 【规格 §4】 |
| `config/settings.yaml` | 主配置；已提及 `agent.max_steps`、`encoder.local_model_path` | 【规格 §6】 |
| `.env.example` → `.env` | 模板复制 | 【规格 §4】 |

所有 LLM／Embedding 调用通过 `httpx` 直连 OpenAI 兼容端点，**不依赖 `openai` SDK**；未配置 Key 时自动保持 `template`／`stub`／`memory`，链路依旧可用。配置需版本化以支持答辩复盘。完整键集合与默认值：→ Q14。

### 4.7 已知限制与如实披露（不得偷偷改变）

| 限制 | 本期处置 |
| --- | --- |
| **未实现多租户、鉴权、会话持久化与并发写入锁** | **如实披露，不偷偷补鉴权**。须在 README、本 PRD、启动日志中明确；提示「仅限本机／可信内网单机演示，勿暴露公网」。`/v1/chat` 流式与入库共享进程内索引，适合单机演示 |
| DEMO 使用确定性 stub 特征与模板答案，语义质量 ≠ 真实多模态大模型；指标只用于链路正确性与回归验证 | 写入 README 评测说明，不夸大准确率 |
| SSE `token` 事件由最终答案按定长切片模拟 | 本期未实现 `LLMClient.chat_stream`；原始规格 §8 曾提及该接口，本仓库未包含该类／方法；SSE `token` 恒由最终答案按 `agent.token_chunk_chars=24` 定长切片模拟；本期不新增该能力（原 PRD P2-4） |
| 图像／音频／视频 DEMO 仅产出描述性文本证据，不做真实图像生成／TTS／ASR；音频仅解析 PCM WAV 容器；视频不可解码时降级确定性合成帧 | 如实说明 |
| 内存向量库为暴力余弦扫描，适合万级以下切片 | 设软上限告警，不改变检索口径（NF-5） |
| `samples/eval.jsonl` 为自建 8 条小型基准，不含公开榜（MMBench／SEED） | 如实说明 |

---

## 5. 非功能需求

> 全部为**内部实现层增量**，不得外溢为 §1.2 所列契约变更。

### NF-1 错误处理与异常反馈
- 统一异常处理：参数校验失败、单模态解析失败、工具超时／异常、索引文件损坏、可选依赖 `ImportError` 均须返回明确、可读、结构化的错误（沿用前端已消费的 `detail` 形态），**绝不因单个失败导致进程崩溃或全链路中断**。
- 降级必须可观测：任何 `fallback` 都写入日志并在 `/health.components` 反映。
- 验收：见 P0-11。

### NF-2 结构化日志与敏感信息脱敏
- 结构化 JSON 行日志，字段至少含时间、级别、`trace_id`、端点／节点、耗时、结果／`fallback` 标记；`trace_id` 贯穿请求 → Agent 节点 → 轨迹 → 响应。
- **脱敏红线**：`LLM_API_KEY`／`Authorization`／`Bearer` 凭据、请求中的原始文件内容正文、轨迹状态快照中的敏感原文，均不得明文进入日志、`data/traces.jsonl` 或任何 API 响应。
- 日志格式／落盘位置／脱敏字段清单文档未给基线：→ Q12。

### NF-3 配置分层与环境可控
- 三层：`config/settings.yaml`（默认） < `.env`／环境变量（覆盖） < `DEMO_MODE=1` 强制锁定（最高优先级）。配置版本化。
- 启动期校验：键名、取值域、路径可解析性；非法配置给出可读错误而非静默失败。
- 路径解析统一收敛到 `app/config.py`，`data/` 自动创建。
- 验收：见 P0-10。

### NF-4 关键路径与边界场景测试
- `tests/` 四组 pytest：模态／RAG／Agent／API（对齐规格 §6）。
- 关键路径覆盖：四模态入库 → 混合检索命中与全零回退 → Planner 规则式识别 → 4 工具各自成功与失败 → SSE 事件序列与 `done` 字段完整性 → `trace_id` 回放 → 8 条评测样例 → `/health` 全 `fallback`。
- 边界场景覆盖：空／超长 query、未知扩展名与畸形文件、非法 JSON、空索引与损坏索引、工具超时、超 `max_steps`、`trace_id` 不存在、SSE 客户端断连、可选依赖缺失、配置了 Key 但仍为 DEMO。
- 验收：见 P0-13。

### NF-5 性能
- 内存向量库为暴力余弦扫描，文档明确「适合万级以下切片」；本期设**可配置软上限**并在接近时告警／降级提示，**不得改变检索结果口径**；具体阈值 → Q11。
- 单工具 `ThreadPoolExecutor` 超时（Agent 四道防线之一），超时返回结构化失败并继续链路，不阻塞、不崩溃；秒数可配置 → Q11。
- 最大步数 `agent.max_steps` 超限强制进入 Reflector 收敛。
- SSE 流在客户端断连时及时释放资源；`elapsed_ms` 如实反映端到端耗时。

### NF-6 安全
- `calculator` 采用**受限 AST**：仅允许数字字面量与四则运算节点，拒绝函数调用、属性访问、任意名称解析、导入等；不得用 `eval`。
- **工具白名单**：仅 4 个内置工具可执行，未注册工具一律拒绝；所有工具带 JSON Schema 与参数校验。
- **上传护栏（企业级增量）**：扩展名／MIME 白名单、单文件与总大小上限、文件名净化（防路径穿越）、写入隔离目录、不落盘到任意用户指定路径、临时文件及时清理；**不得拒绝现有 `web/index.html` 的正常上传流程**；具体白名单与阈值 → Q3。
- **无鉴权**：文档明确未实现鉴权／多租户／会话持久化／并发写入锁。本期**不得偷偷新增鉴权**（会改变契约与前端流程），仅如实披露并提示部署边界。
- 验收：见 P0-15。

---

## 6. UI 说明

- **原样复用** `web/index.html`，同源托管于 `/` 与 `/ui/index.html`；**不做任何功能性改动**。如需修复，仅限不触碰接口与字段集合的缺陷修复，且须回归验证；默认不改。
- 前端调用的接口（不得改）：`GET /health`、`POST /v1/ingest`、`POST /v1/chat`（含 SSE）、`GET /v1/trace/{trace_id}`、`GET /v1/tools`、`POST /v1/eval`。
- 前端消费的数据格式（不得改）：§4.2 各响应字段、`UnifiedResponse` 11 字段、`meta`／`step`／`token`／`human_required`／`done` 五种 SSE 事件及其 `data` 字段、`\n\n` 分帧格式。
- 前端既有假设后端必须满足：健康徽标读 `demo_mode`；入库读 `total`／`chunks[].modality`；`renderMeta()` 读 `trace_id`／`steps`／`elapsed_ms`／`status`／`output_modality`／`graph_backend`；`renderResult()` 读 `answer`／`evidences[]`／`tool_results[]`；评测读 `hit_rate`／`tool_hit_rate`／`avg_steps`／`avg_latency_ms`／`samples`／`details[]`；回放读 `events[]`／`count`。
- 交互链路：① 多模态资源入库 → ② 提问（可切 SSE）→ 统一应答／引用证据／工具调用与结果／实时 step 轨迹 → 回放轨迹 → 工具清单 → 运行评测；右上角健康徽标与「运行信息」面板展示降级状态。

---

## 7. 待确认问题

> 以下均为「文档与前端均未明确」的事实空缺。实现时**不得臆造**；建议默认值仅为提案，须经主理人／用户确认后方可落地。所有提案均不得改变 §1.2 契约。

| 编号 | 问题 | 文档现状 | 影响 | 建议（待确认） |
| --- | --- | --- | --- | --- |
| Q1 | `/health` 顶层是否另含 `status`／`ok`／`version` 等字段？ | 规格仅描述「健康状态、组件降级情况、索引切片数」；前端仅消费 `demo_mode` + `components` | EP-1 响应结构 | 保留最小集合 `demo_mode` + `components`，不擅自加顶层字段 |
| Q2 | `/v1/ingest` 响应 `chunks[]` 元素除 `modality` 外还含哪些字段？错误响应结构？ | 前端仅读 `c.modality` 与错误时 `data.detail` | EP-2、UI 入库提示 | 至少含 `chunk_id`／`modality`；错误沿用 `{"detail": ...}` |
| Q3 | 上传扩展名／MIME 白名单、单文件与总大小上限、临时目录与清理策略的具体值？ | 规格未给任何数值；NF-6 需要可执行阈值 | P0-15 验收 | 由 `config/settings.yaml` 配置、给出保守默认值，须主理人确认数值 |
| Q4 | `status`／`output_modality`／`graph_backend` 的枚举取值集合？`modalities` 空数组与缺省是否等价？`session_id` 在无会话持久化下是否仅透传记录？ | 仅列字段名，未给取值域 | EP-3、UI 元数据渲染 | 由实现内部固定枚举并在 README 说明，不新增字段 |
| Q5 | `evidences[]` 元素除 `chunk_id`／`modality`／`snippet`／`score` 外是否含 `source_id`／`content`？ | 规格明确 4 项，前端消费 4 项 | 证据溯源展示 | 保持 4 项为必需，其他作为可选内部字段 |
| Q6 | `tool_calls[]`／`tool_results[]` 元素的完整字段？ | 规格仅列数组名；前端消费 `tool_results` 的 `name`／`ok`／`elapsed_ms`／`output`／`error` | EP-3、UI 工具面板 | 保证前端 5 字段必需，其余按需扩展 |
| Q7 | `/v1/trace/{trace_id}` 的 `events[]` 元素完整字段？`trace_id` 不存在时返回 404 还是 `{"events":[],"count":0}`？ | 前端消费 `event`／`node`／`steps`／`status`／`count`；规格未定错误行为 | EP-4、NF-4 边界用例 | 明确一种行为并写入 README，须主理人确认 |
| Q8 | `/v1/tools` 响应中「生效白名单」的字段名与结构？ | 规格说「工具 JSON Schema 与生效白名单」，前端仅消费 `tools[].{name,description,parameters}` | EP-5 | 不删改 `tools[]`，白名单作为新增字段（不影响前端） |
| Q9 | `/v1/eval` 请求 `samples[]` 元素结构（是否含 `expected_tools`／期望答案）？`hit` 判定标准？请求 `samples`（数组）与响应 `samples`（数量数字）同名不同义是否按现状保持？ | 规格仅说「可选 `{"samples":[...]}`，不传用 `samples/eval.jsonl`」；前端消费响应为数量、`details` 用 `actual_tools` | EP-6、P0-6 验收 | 按现状保持同名不同义；`samples/eval.jsonl` 需本期创建，其 schema 须主理人确认 |
| Q10 | `human_required` 在事件流中的确切插入位置？`HUMAN_IN_LOOP=1` 时 `resume(state,"approved")` 的 HTTP 触发方式？ | 规格给了图接口与「额外产生」，未给 REST 恢复端点 | §4.4、US-4 | 本期不擅自新增端点；建议仅在图层支持 `resume()`，REST 通道列为后续版本，须主理人确认 |
| Q11 | `agent.max_steps` 默认值、单工具超时秒数、暴力扫描软上限阈值的具体值？ | 规格仅提机制与「万级以下」定性描述 | NF-5、P0-14 验收 | 全部收敛到 `config/settings.yaml` 并给保守默认值，数值须主理人确认 |
| Q12 | 结构化日志格式、落盘位置、脱敏字段清单的基线？ | 文档未定义（本次企业级增量新增） | NF-2、P0-12 验收 | 建议 JSON 行 + `trace_id`，Key／凭据／文件正文／轨迹快照敏感原文强制脱敏，须主理人确认 |
| Q13 | `GET /docs` 是否纳入契约端点清单保护？FastAPI 自动文档是否默认开启？ | 规格 §5 列出 `/docs`，主理人指定的 7 组端点未含 | §4.1 端点清单 | 建议保留 FastAPI 默认开启，但不列入 7 组红线 |
| Q14 | `config/settings.yaml` 的完整键集合与默认值？ | 规格仅提及 `agent.max_steps`、`encoder.local_model_path` | NF-3、P0-10 | 由架构师按 §4.6 键表补齐并版本化，须主理人确认 |
| Q15 | 运行期 `data/` 在只读环境／多进程下的行为？ | 规格明确「无并发写入锁」「单机演示」 | 部署边界 | 本期维持单机假设并如实披露，不做并发锁（P2-3） |

---

**文档状态**：待主理人评审 → 交付架构师作为设计输入。§7 待确认项若获答复，须以增量方式更新本 PRD 并同步下游，不得静默变更 §4 契约红线。

**增量 PRD**：开源化与企业级补齐的需求见 `docs/PRD-OPENSOURCE.md`（本文件 §4 契约红线仍为最高优先级）。
