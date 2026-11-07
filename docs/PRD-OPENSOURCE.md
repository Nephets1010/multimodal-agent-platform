# 多模态通用智能体开发平台 · 开源化与企业级补齐增量 PRD

| 项 | 值 |
| --- | --- |
| 文档类型 | 简单增量 PRD（不含竞品／市场分析） |
| 版本 | v1.2（同步主理人裁决 + 架构设计 v1.1；契约未变） |
| 编写 | 产品经理 许清楚（Xu） |
| 语言 | 简体中文 |
| 上游依据 | `docs/PRD.md`（v1.0，行为契约）、`docs/ARCHITECTURE.md`、`docs/TASKS.md`、`README.md`、主理人实测现状与用户新指令 |
| 适用范围 | **仅**现有 `repos/multimodal-agent-platform/` 目录内；不新建独立项目 |
| 交付形态 | 本文件为需求文档；**不写任何代码或开源文件本身**，不执行任何 git 操作 |

> **⚠️ v1.2 覆盖声明（最高阅读优先级）**
> 本增量 PRD 中凡与**主理人裁决 / `docs/ARCHITECTURE-OPENSOURCE.md` v1.1 + `docs/TASKS-OPENSOURCE.md` v1.1** 冲突之处，**一律以后者为准**，本文件相应表述作废。
> **基线顺序**：`docs/PRD.md` §4 契约红线（**最高优先级、一字未动**） > 主理人裁决 > 架构设计 v1.1 + 任务分解 v1.1 > `docs/REPO_METADATA.md` > 本 PRD > 其它文档。
> 本次修订原因是**时间线错位（v1.1 成文早于裁决），不是契约变更**；六处差异索引见 §0.1，裁决记录见 §6。

> 下游交接提示：架构师（#6）重点看 §1.3 不可变契约、§2.4–§2.8、§4；工程师（#7）重点看 §2 需求池、§4 占位符冻结规则；QA（#8）重点看 §3 全部判据、§2 P0-QA；主理人（#9）重点看 §4.3 收尾流程与 §4.4 冻结规则。

---

## 0. 增量背景与已核实现状

**用户新指令要点**：以当前工作区中的多模态通用智能体开发平台为对象，**在不改变项目定位、不新建独立项目的前提下**推进至可交付的企业级标准——完善核心功能、项目结构与配置，规范错误处理、日志记录与输入校验，补齐必要文档、测试与开源说明，确保代码可运行、可复现、可维护，并具备清晰模块边界、合理的安全性与可扩展性；完成后提交并推送到用户 GitHub 仓库（使用当前已配置的远程仓库，若未配置先提示用户提供地址），将仓库设为公开并配置为开源项目，补充合适的开源许可与项目元信息，反馈推送结果、仓库可见性与开源配置状态。

**主理人实测现状（已核实，非推测）**：

| 项 | 现状 |
| --- | --- |
| 代码与测试 | 已落地 45 个源码／配置／测试文件 + QA 新增 `tests/test_edge_api.py`；`DEMO_MODE=1 python3 -m pytest -q tests` = **80 passed** |
| 既有文档 | `docs/PRD.md`、`docs/ARCHITECTURE.md`、`docs/TASKS.md`、`docs/reference/*` 齐备 |
| 既有根级文件 | `README.md`、`requirements.txt`、`samples/knowledge.txt`、`web/index.html`、`.env.example`、`.gitignore`、`Makefile`、`config/settings.yaml` 齐备 |
| 企业级能力 | 结构化 JSON 行日志 + 三出口脱敏、统一异常反馈、输入校验与上传护栏、配置分层与启动期校验、受限 AST 计算器、工具白名单与超时、四组 pytest + 边界用例**均已落地**（`README.md` §7、`docs/TASKS.md` S1–S20） |
| 开源要素 | 原 **9 个全部缺失**（`LICENSE`／`pyproject.toml`／`CONTRIBUTING.md`／`CODE_OF_CONDUCT.md`／`SECURITY.md`／`CHANGELOG.md`／`CITATION.cff`／`.github/workflows/ci.yml`／`NOTICE`）；主理人裁决**新增第 10 个** `docs/REPO_METADATA.md`（占位符唯一登记处，现已落盘）→ 共 **10 个** |
| 遗留缺陷 ① | `cp .env.example .env` 后 `get_settings()` 抛 `ConfigError: 配置项 server.port 的环境变量值 '' 无法转换为 int 类型`；根因已定位：`app/config.py` 的 `load_dotenv_simple()` 把空占位符解析为空串，`env_override()` 将其作为有效覆盖交给 `_coerce()`，数值／布尔键转换失败即抛错 |
| 遗留缺陷 ② | `README.md:154` 声称「`LLMClient.chat_stream` 真实增量输出已提供」，但全仓无该类／方法；系沿用原始规格 §8 的不实声明 |
| 仓库地址 | 项目目录无 `.git`、无 remote；GitHub 账号 `Nephets1010` 下无同名仓库（404）；工作区其它 24 个子仓库的 origin 属别的项目，**不得挪用**；已向用户索取地址，**尚未回复** |
| 环境 | 本机 Python 3.13（`docs/TASKS.md` §0、`__pycache__` 标记 cpython-313），代码保持 3.11+ 兼容语法；本机 `make` 不可用但 Makefile 四目标齐备 |

**本次增量定位**：企业级核心能力与测试**已由前序任务完成，本次不重复实现、不借「完善核心功能」之名重构已落地模块**。本次仅做三件事：① 补齐 9 个开源要素与 README 开源章节；② 修复 2 个已知遗留缺陷并补回归用例；③ 全量验证「可运行／可复现／可维护」并定义推送收尾流程。

**本 PRD 明确不做**：不写代码或开源文件本身；不 `git init` / `commit` / `push` / 配 remote；不新建同级项目目录；不改任何对外契约。

### 0.1 基线优先级与覆盖声明（v1.2，最高阅读优先级）

> **本 PRD v1.1 成文早于主理人对 Q-OS1～Q-OS12 的正式裁决。裁决后架构师已将 `docs/ARCHITECTURE-OPENSOURCE.md` 与 `docs/TASKS-OPENSOURCE.md` 覆盖落盘为 v1.1。凡本文件与裁决／架构 v1.1 冲突之处，一律以裁决 + 架构 v1.1 为准，本文件相应表述作废；这是时间线错位，**不构成契约变更**——`docs/PRD.md` §4 红线一字未动。**

**基线顺序**：`docs/PRD.md` §4（最高，行为契约）→ **主理人裁决** → `docs/ARCHITECTURE-OPENSOURCE.md` v1.1 + `docs/TASKS-OPENSOURCE.md` v1.1 → `docs/REPO_METADATA.md`（占位符唯一登记处）→ 本 PRD → 其它文档。

**六处差异索引（PRD v1.1 → 裁决／架构 v1.1）**：

| # | 本 PRD v1.1 表述（作废） | 以裁决／架构 v1.1 为准 |
| --- | --- | --- |
| 1 | §4.1「占位符仅在本节集中登记一次」 | 新建 **`docs/REPO_METADATA.md` 为唯一登记处**（第 **10** 个开源／元信息文件，11 符号 + 12 RP 点 + 派生规则 + 6 列结构） |
| 2 | §6 Q-OS3「身份用占位符、禁止用账号名臆造」 | 作者／版权 holder = `Nephets1010`、年份 `2026`、邮箱 `Nephets1010@users.noreply.github.com`，登记为「默认取值，用户可替换」，**交付文件仍写占位符、S2 一次性替换**；⚠️ **URL 类一律不预填、仍禁止用账号拼装仓库 URL**（身份与 URL 严格区分） |
| 3 | §2.7／P0-OS5「CI 三步」 | **五步**：compileall / pytest / demo.py / `DEMO_MODE=1 python3 -m app.observability.evaluator` / 内联契约冒烟；加 `cache: "pip"` + `cache-dependency-path`、`timeout-minutes`、失败-fast |
| 4 | §2.5／Q-OS5「方案 A 默认、方案 B 待裁决」 | **已拍板不加 `[build-system]`**、不引入任何打包期依赖；补 `[tool.pytest.ini_options]`（仅 `testpaths`，不得破坏 80 用例）+ 可选 `[tool.coverage.*]` 纯配置（**不装 coverage 包**） |
| 5 | §2.8「BUG2 仅 4 处声明修正」 | 4 处不变，**另在 `README.md` §6 增加一句**「`docs/reference/` 为原始规格清洗副本，描述目标态设计基线；实现状态以本 README 与 §6 为准」；reference 仍字节级零改动 |
| 6 | §6「待确认问题、须主理人确认」+ §4.3 S1「或授权新建仓库」 | **Q-OS1～Q-OS12 已全部拍板，无待确认决策门**；Q-OS2 明确**不新建仓库**，只写 S1–S7 收尾流程；地址未到位时允许占位符版交付（可有 `__...__` 残留）但**不得推送** |

> 其余不变：`/health` DEMO 逐字段冻结（`version="1.0.0"` 必须保留、`configured_backends` 连键不输出）、BUG1 `env_sandbox` fixture 隔离、`logging.py` 零改动、12 RP 点禁臆造／禁挪用其它 24 个子仓库 origin、CoC 自写精简版、Apache-2.0、CI 仅 3.11、架构师／工程师／QA 均不执行 git 操作。

---

## 1. 增量范围与不变式

### 1.1 「不新建独立项目」

所有改动**只在现有 `repos/multimodal-agent-platform/` 内**：不建同级新目录、不复制／分叉项目、不改 `app/` 六个子包与顶层目录名（对齐 `docs/TASKS.md` §8）。新增文件一律落在现有目录树内：`LICENSE`／`NOTICE`／`pyproject.toml`／`CONTRIBUTING.md`／`CODE_OF_CONDUCT.md`／`SECURITY.md`／`CHANGELOG.md`／`CITATION.cff` 放仓库根，`.github/workflows/ci.yml` 放新建 `.github/workflows/`，`docs/PRD-OPENSOURCE.md` 放现有 `docs/`。

### 1.2 「不改变项目定位」

以下定位与红线**全部不变**：

- 链路定位：四模态统一接入 → 统一表征与多模态 RAG → Planner／Worker／Reflector 智能体编排 → 工具调用 → SSE 流式统一应答 → 轨迹回放与自动评测。
- 受众定位：面向**求职作品集／实训**的真实可运行项目；不得宣称生产级可用或具备企业级安全能力。
- `DEMO_MODE=1` 零依赖红线：零 API Key、零 GPU、零联网、零模型权重下载，`get_settings()` 最后一步无条件锁定 `template`／`stub`／`memory`，可选依赖仅 `find_spec` + `try/except ImportError` 降级（`docs/PRD.md` §4.5 十条逐条不变）。

### 1.3 不可变契约（逐条复述 `docs/PRD.md` §4）

> 以下四组为**最高优先级红线**。开源化过程中的任何文件新增、文档改写、缺陷修复都**不得增删、重命名或改变**其中任何一项；偏离须先回报主理人。

#### 1.3.1 7 组 REST 端点（路径／方法／请求字段／响应字段集合）

| 编号 | 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- | --- |
| EP-1 | GET | `/health` | 无 | JSON：`demo_mode` + `components` |
| EP-2 | POST | `/v1/ingest` | `multipart/form-data`：`files`（可多传）／`text`／`source_tag` | JSON：`total` + `chunks[]` |
| EP-3 | POST | `/v1/chat` | JSON：`query`／`session_id`／`stream`／`modalities` | JSON（`UnifiedResponse`）或 SSE |
| EP-4 | GET | `/v1/trace/{trace_id}` | 路径参数 | JSON：`events[]` + `count` |
| EP-5 | GET | `/v1/tools` | 无 | JSON：`tools[]` + 白名单等 |
| EP-6 | POST | `/v1/eval` | 可选 `{"samples":[...]}` | JSON：6 字段，响应 `samples` 为数量数字 |
| EP-7 | GET | `/`、`/ui/index.html` | 无 | `text/html`，同源托管 `web/index.html` |

`GET /docs` 为 FastAPI 自动文档（原 PRD Q13），不列入 7 组红线；所有端点同源、无跨域配置。

#### 1.3.2 `UnifiedResponse` 恰好 11 字段（不得删改／重命名）

`answer` ／ `evidences[]`（含 `chunk_id`／`modality`／`snippet`／`score`）／ `tool_calls[]` ／ `tool_results[]`（前端消费 `name`／`ok`／`elapsed_ms`／`output`／`error`）／ `trace_id` ／ `steps` ／ `elapsed_ms` ／ `status` ／ `output_modality` ／ `demo_mode` ／ `graph_backend`。

#### 1.3.3 SSE 帧格式与事件顺序

帧格式：`event: <name>\ndata: <单行 JSON>\n\n`（禁止多行／缩进 JSON，前端 `parseFrame()` 逐行 `JSON.parse` 会静默吞错），帧间 `\n\n` 分隔。
事件顺序：`meta`(1) → `step`(每个节点 1..n) → `token`(答案分片 1..n，由最终答案定长切片模拟) → `human_required`(仅 `HUMAN_IN_LOOP=1` 时额外产生，插在最后一个 `step` 之后、`done` 之前，且不替代 `done`) → `done`(1，恒为最后一帧、携带完整 11 字段 `UnifiedResponse`)。
各事件 `data` 字段：`meta`{`trace_id`,`backend`}／`step`{`steps`,`node`,`next_node`,`status`,`last_observation`}／`token`{`delta`}／`human_required`{`prompt`}／`done`{完整 `UnifiedResponse`}。
`done` 与非流式响应由同一个 `build_unified_response()` 产出；所有 `token.delta` 拼接后等于 `done.answer`；**本期不新增 REST 恢复端点**（Q10）。

#### 1.3.4 配置键兼容性

| 配置 | 取值／说明 |
| --- | --- |
| `DEMO_MODE` | 默认 `1`；`0` = 生产；优先级最高 |
| `LLM_BACKEND` | `api`／`template` |
| `ENCODER_BACKEND` | `api`／`transformers`／`stub` |
| `VECTOR_BACKEND` | `chroma`／`memory` |
| `HUMAN_IN_LOOP` | `1` 开启人工介入断点 |
| `LLM_API_KEY`／`LLM_BASE_URL`／`LLM_MODEL`／`LLM_VISION_MODEL` | OpenAI 兼容端点与凭据；`vision_model` 留空复用 `model` |
| `HOST`／`PORT`／`AGENT_MAX_STEPS`／`AGENT_TOOL_TIMEOUT_SECONDS` 等历史短别名 | 不带前缀，优先级不变 |
| `MAP_<SECTION>__<KEY>` | 项目前缀长格式，全部键可覆盖；裸 `<SECTION>__<KEY>` 不得被读取 |
| `config/settings.yaml` | 主配置，`config_version: 1`，键名／取值域／默认值不得改动 |
| `.env.example` → `.env` | 模板复制；模板仅含占位符、不含真实凭据 |

所有 LLM／Embedding 调用通过 `httpx` 直连 OpenAI 兼容端点，不依赖 `openai` SDK；未配置 Key 时自动保持 `template`／`stub`／`memory`。

#### 1.3.5 DEMO 模式 `/health` 响应冻结（本期特别红线）

`DEMO_MODE=1` 下 `/health` 的响应结构**逐字段冻结：既有字段一个不删、新字段一个不增**。当前既有字段为：`demo_mode` + `components`（11 项，含生效后端、6 项 `native`／`fallback` 探测结果、实时 `index_chunks`）+ 顶层 `status`／`version`／`index_chunks` —— 其中 **`version="1.0.0"` 是既有字段，必须保留，且 §3 判据 R-1 明确要求其存在**，不得因「版本信息不该进 `/health`」而误删。`configured_backends` 为**生产模式专有**字段（`routes.py:102–110` 以 `exclude_none=True` 输出），DEMO 下**连键都不能出现**（输出 `null` 亦属违约）。**禁止新增**的是开源徽章、许可证、仓库 URL、topics 等**新字段**；这些信息只能出现在 README／pyproject／LICENSE 等文档与元信息文件中，不得借开源化之名增删任何既有字段。

### 1.4 零改动清单与允许增量清单

**字节级零改动**：`web/index.html`、`requirements.txt`、`samples/knowledge.txt`、`docs/reference/*`（原始规格文档）、`Makefile` 四目标命令、`config/settings.yaml` 键名与取值域。`docs/ARCHITECTURE.md` §7 质量守卫清单、`docs/TASKS.md` S1–S20 共享约定继续有效。

**允许增量（且仅限）**：① 新增 **10 个**开源／元信息文件（含 `docs/REPO_METADATA.md`）+ `.github/` 目录；② README 增补开源章节（现有 §1–§7 **零删减**）；③ 修正 2 个遗留缺陷（`app/config.py` 覆盖链、README 及自有文档的不实声明）并新增回归用例；④ `.gitignore` 补充构建产物忽略项；⑤ 文档间术语一致性修正。**不得**改动任何业务代码的对外行为，不得新增必需依赖，不得改技术栈（Python 3.11+／FastAPI／Pydantic v2／Uvicorn／原生 JS，无前端构建工具）。

---

## 2. 需求池

优先级：**P0 = Must have（阻塞交付）**、**P1 = Should have**、**P2 = Nice to have／后续版本**。共 **13 条**（P0 8 ／ P1 3 ／ P2 2），P0 逐条带可验收标准。

### 2.1 P0（8 条，逐条可验收）

| 编号 | 需求 | 验收标准 |
| --- | --- | --- |
| **P0-OS1** | 开源许可选型与 `LICENSE`／`NOTICE`：采用 **Apache-2.0**（选型理由见 §2.4），`LICENSE` 为完整原文、`NOTICE` 含版权声明与第三方依赖归属 | `LICENSE` 标题为 Apache License Version 2.0 且含 §3 专利授权／§6 商标／§7 免责／§8 责任限制，条款零改写；`NOTICE` 含版权行（用 §4.1 占位符）与 10 个核心依赖 + 6 个可选依赖归属；`pyproject.toml` license 字段与之完全一致；全仓无冲突许可声明 |
| **P0-OS2** | 项目元信息 `pyproject.toml`：字段清单见 §2.5；**不得引入 `requirements.txt` 之外的必需依赖、不得改技术栈** | 11 类字段齐备；`version=1.0.0` 与 `app/__init__.py::__version__` 一致；`requires-python=">=3.11"`；可选依赖分组只含 6 个既有可选包名；入口点指向已存在的 `scripts.demo:main`；`python3 -m pip install -r requirements.txt` + 四条 DEMO 命令仍全绿；无真实凭据、无臆造 URL；**主理人已裁决 Q-OS5：不加 `[build-system]`、不引入任何打包期依赖**，`[project.scripts]` 仅静态声明，验收以「指向真实存在的可调用对象 + 不改业务代码」为准，**不要求 `pip install -e .` 后生效**；补 `[tool.pytest.ini_options]`（仅 `testpaths`，不得破坏 80 用例）|
| **P0-OS3** | `README.md` 开源章节：徽章、许可证、快速开始（含克隆）、能力边界、贡献方式、安全披露、致谢、已知限制如实披露 | 8 类内容齐备；现有 §1–§7 零删减，尤其保留「未实现鉴权／勿暴露公网」与 `0.0.0.0` 暴露风险提示；无「生产级／企业级安全／90% 准确率／已实现鉴权／已提供 chat_stream」等过度声明；全部 URL 使用 §4.1 占位符 |
| **P0-OS4** | 贡献／行为准则／安全策略／变更日志／引用文件：`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、`SECURITY.md`、`CHANGELOG.md`、`CITATION.cff`（要点见 §2.6） | 5 份文件齐备且必备章节／字段齐全；`CITATION.cff` 可被 `PyYAML`（既有核心依赖）解析且 `cff-version`／`title`／`version`／`authors`／`url`／`license` 齐备；无真实凭据；占位符统一；与 README／pyproject 措辞一致 |
| **P0-OS5** | CI 工作流 `.github/workflows/ci.yml`：至少 lint／compile + pytest + demo 冒烟（要点见 §2.7），**必须 `DEMO_MODE=1` 零联网零 Key 可跑** | 文件存在；触发 `push`／`pull_request`；Python 3.11；仅 `pip install -r requirements.txt`（不装可选依赖）；全局 `DEMO_MODE=1`；**无任何 secrets／API Key／外部 API 调用／产物上传**；**CI 五步**全通过（compileall / pytest / demo.py / `DEMO_MODE=1 python3 -m app.observability.evaluator` / 内联契约冒烟），并具 `cache: "pip"` + `cache-dependency-path`、job 级 `timeout-minutes`、失败-fast；不改动任何零改动文件 |
| **P0-BUG1** | 空环境变量缺陷修复 + 回归用例：空串占位符视为「未覆盖」，回落 `config/settings.yaml` 默认值（要点见 §2.8） | `cp .env.example .env` 后 `get_settings()` 不抛 `ConfigError`；`server.port=8000`／`agent.max_steps=8`／`tool_timeout_seconds=3.0`／`human_in_loop=false` 取 YAML 默认；非空覆盖仍生效；非法非空值仍抛可读 `ConfigError`；`LLM_BACKEND=api` + `DEMO_MODE=1` 仍锁定 `template`／`stub`／`memory`；新增 pytest 回归用例并全绿（**自动化回归须用 `env_sandbox` fixture monkeypatch `PROJECT_ROOT` → tmp_path，禁止测试往仓库根写 `.env`**）；命令行手工复现后必须删除 `.env` 并确认仓库根无残留 |
| **P0-BUG2** | 不实声明修正：`README.md:154` 及全仓同类措辞改为「本期未实现」，清单见 §2.8 | 4 处待修正位置全部改毕；项目自有文件检索 `chat_stream` 后**无「已提供／已实现／已具备」类断言**；仅保留「本期未实现；SSE `token` 恒由定长切片模拟」口径；`docs/reference/*` 与 `web/index.html` 字节级零改动；`docs/TASKS.md` 与 `app/generation/router.py` 的「不得改挂」中性措辞可保留；**另在 `README.md` §6 增加一句**「`docs/reference/` 为原始规格清洗副本，描述目标态设计基线；实现状态以本 README 与 §6 为准」（消解规格与实现的表面矛盾，reference 仍字节级零改动）|
| **P0-QA** | 全量回归、真启动、边界／安全／性能验证，按 §3 全部判据逐条执行 | §3 的 R-1～R-3／C-1～C-3／M-1～M-4 **10 条判据全部通过**；`DEMO_MODE=1 python3 -m pytest -q tests` ≥ 80 passed 且退出码 0；零改动文件字节级核对通过；启动日志含无鉴权告警；`DEMO_MODE=1` 下 httpx 外部请求数为 0 |

### 2.2 P1（Should have）

| 编号 | 需求 | 验收／说明 |
| --- | --- | --- |
| P1-OS1 | `.gitignore` 补充构建产物忽略项（`dist/`／`build/`／`.mypy_cache/`／`.ruff_cache/`／`.coverage`），并确认 `LICENSE`／`NOTICE`／`pyproject.toml` 不被忽略 | 现有 4 类忽略项（`.env`、`data/` 运行期产物、`__pycache__`、`*.py[cod]`、`.pytest_cache/`、`*.egg-info/`、`.venv/`）零删减；新建 **10 个**开源／元信息文件均可被 git 追踪 |
| P1-OS2 | `.github` 下 Issue／PR 模板（可选） | 模板内容不得含真实仓库 URL（用 §4.1 占位符）；不影响 CI 工作流 |
| P1-OS3 | 文档交叉链接与术语一致性 | `README.md`／`docs/PRD.md`／`docs/ARCHITECTURE.md`／`docs/TASKS.md`／本文件互相引用无死链；「DEMO_MODE 十条红线」「11 字段」「7 组端点」表述一致 |

### 2.3 P2（Nice to have／后续版本，本期明确不做）

| 编号 | 需求 | 本期处置 |
| --- | --- | --- |
| P2-OS1 | CI 多版本矩阵（3.11／3.12／3.13） | 本期仅 3.11（对齐 `requires-python`）；本机为 3.13 但 `requirements.txt` 注释写 3.11，**Q-OS7 已裁决本期仅 3.11**，多版本矩阵维持 P2 |
| P2-OS2 | 发布到 PyPI／release 自动化 | 本期不做：会引入发布凭据与外部服务，超出「不新增必需依赖／DEMO 零联网」边界 |

### 2.4 P0-OS1 · 开源许可选型理由（Apache-2.0）

| 维度 | 理由 |
| --- | --- |
| 账号一致性 | 依据主理人核实的前提，同账号（`Nephets1010`）其它开源仓采用 Apache-2.0；沿用同一许可可降低读者与评审者的认知成本、保持作品集风格统一。**主理人已裁决采用 Apache-2.0（§6.1）；本项仅作选型背景，不得据此臆造具体仓库名或数量** |
| 专利条款 | Apache-2.0 §3 提供明确的专利授权与专利报复条款；MIT 无专利条款。对于包含 Agent 编排与多模态 RAG 实现的项目，可给贡献者与使用者更清晰的专利预期 |
| 商标条款 | §6 明确不授予商标许可，避免项目名／作品集标识被搭便车；MIT 无对应条款 |
| Copyleft 适配 | GPL-3.0 传染性强，会限制作品集代码被集成与引用；Apache-2.0 允许商用、修改、分发与再授权，仅要求保留版权／许可声明与变更说明，更适合求职作品集被阅读、复用与二次开发 |
| 免责与边界一致 | §7 免责声明与 §8 责任限制，与 README「DEMO 语义质量 ≠ 真实模型」「无鉴权、仅限本机／可信内网单机演示、勿暴露公网」的披露口径天然一致；不得在 README 中作出与免责相冲突的「生产可用」承诺 |
| 工程规范展示 | `LICENSE` + `NOTICE` + 变更说明要求，本身即是作品集可展示的开源工程规范项 |

**约束**：`LICENSE` 必须为 Apache-2.0 完整原文，不得改写条款；`NOTICE` 的版权年份／持有人使用 §4.1 占位符，**禁止臆造**；许可证选择不得影响 `DEMO_MODE=1` 运行链路与任何对外契约。

### 2.5 P0-OS2 · `pyproject.toml` 字段清单

| 字段 | 要求 |
| --- | --- |
| `name` | `multimodal-agent-platform`（与目录名一致） |
| `version` | `1.0.0`，与 `app/__init__.py::__version__` 一致（已核实） |
| `description` | 一句话定位，与 README 首段一致；不得夸大 |
| `readme` | `README.md` |
| `license` | `Apache-2.0`，并声明 `LICENSE`／`NOTICE` 许可文件 |
| `requires-python` | `>=3.11`（本机 3.13，代码保持 3.11+ 兼容语法） |
| `authors`／`maintainers` | 交付文件仍写 `__AUTHOR_NAME__`／`__AUTHOR_EMAIL__`；默认值由主理人裁决为 `Nephets1010` / `Nephets1010@users.noreply.github.com`，登记在 `docs/REPO_METADATA.md` 并注明「默认取值，用户可替换」，S2 一次性替换（**URL 类仍禁止用账号拼装**） |
| `keywords` | 与定位一致的关键词组（多模态、RAG、Agent、FastAPI、SSE、DEMO、作品集等） |
| `classifiers` | Python 3.11、Apache Software License、FastAPI、人工智能主题等；**Development Status 建议 Alpha／Beta，不得写 Production／Stable** |
| `urls` | Homepage／Repository／Issues／Changelog／Documentation 共 5 个子键，全部由 §4.1 占位符派生（RP-04） |
| `optional-dependencies` | 仅列 `requirements.txt` 已声明的 6 个可选包（`langgraph`／`chromadb`／`openai-whisper`／`transformers`＋`torch`／`openai`）分组；**不得出现任何新包名、不得设为必需** |
| `scripts`（入口点） | `multimodal-agent-demo = "scripts.demo:main"`（已核实 `scripts/demo.py:129` 存在 `main() -> int`），`scripts` 包须纳入包清单；`app/observability/evaluator.py` 无 `main()`，保持 `python3 -m app.observability.evaluator`，**不得为凑入口点而修改业务代码** |
| `build-system` | **主理人已裁决：不加 `[build-system]`、不引入任何打包期依赖**（原「方案 A／B」表述作废）。`pyproject.toml` 只承担「项目元信息 + 工具配置」：补 `[tool.pytest.ini_options]`（仅 `testpaths`，**不得破坏 80 用例**）+ 可选 `[tool.coverage.*]` 纯配置（**不装 coverage 包**）。`requirements.txt` 一字不改、仍是唯一依赖来源；CI／DEMO 一律 `pip install -r requirements.txt` + 四条 `python3` 命令，**不执行打包安装**。此时 `[project.scripts]` 与包清单仅静态声明、不构成可安装入口点，验收口径见 P0-OS2 |

**硬约束**：不新增 `requirements.txt` 之外的必需依赖（lint 工具 `ruff`／`flake8`／`mypy` 一律不得成为必需依赖，见 §2.7）；不改技术栈；不得因元信息文件改变 `DEMO_MODE=1` 下的 `/health` 响应（§1.3.5）。

### 2.6 P0-OS4 · 五份开源文件要点

| 文件 | 必备内容 | 红线 |
| --- | --- | --- |
| `CONTRIBUTING.md` | 开发环境（Python 3.11+、`pip install -r requirements.txt`）、四条 DEMO 等价命令、代码风格（标准库优先、零新增必需依赖、禁内置 `hash()`／`eval`）、提交与 PR 流程、测试要求（pytest 全绿 + 边界用例）、Issue 规范、克隆与链接地址 | 明确 `web/index.html`／`requirements.txt`／`samples/knowledge.txt`／`docs/reference/*` 零改动；全部 URL 用占位符 |
| `CODE_OF_CONDUCT.md` | 行为准则正文、适用范围、举报渠道 | **Q-OS6 已裁决：自写精简版**，不引入第三方原文（避免版权争议）；举报渠道用 `__SECURITY_CONTACT__` 占位符 |
| `SECURITY.md` | 支持版本（`1.0.0`）、报告渠道、响应预期、敏感信息不入 Issue | **必须**明确「未实现鉴权／多租户／会话持久化／并发写入锁，**属已知设计边界而非漏洞**，仅限本机或可信内网单机演示，勿暴露公网」；保留 `0.0.0.0` 暴露风险与 `HOST=127.0.0.1 python3 -m app.main` 收紧方式 |
| `CHANGELOG.md` | Keep a Changelog 风格；`[1.0.0]` 记录本次企业级补齐（**10 个**开源／元信息文件、两个缺陷修复、80 passed 基线） | 日期用占位符；底部版本比较链接用占位符（RP-11）；不得声称「新增鉴权／真实增量输出」 |
| `CITATION.cff` | CFF 1.2.0：`message`／`title`／`type: software`／`version: 1.0.0`／`abstract`／`keywords`／`authors`／`url`／`repository-code`／`license: Apache-2.0` | 作者与 URL 用占位符；`abstract` 与 README 定位一致，不得夸大 |

### 2.7 P0-OS5 · CI 工作流要点

| 项 | 要求 |
| --- | --- |
| 触发与运行时 | `push`／`pull_request`；Python **3.11**；`pip install -r requirements.txt` 为唯一安装步骤（构建期安装允许，**运行期零联网零 Key**）；job 级 `timeout-minutes: 15` |
| 缓存与失败-fast | `actions/setup-python@v5` 配 `cache: "pip"` + `cache-dependency-path: requirements.txt`（只缓存核心依赖 wheel）；每步独立 `run`，任一非 0 退出即终止；**禁用** `continue-on-error`／`|| true`／retry 循环 |
| 环境变量 | 全局 `DEMO_MODE=1`；**不配置任何 secrets、API Key、Token**；不安装可选依赖；不调用任何外部 API；不上传产物到第三方服务 |
| 第 1 步 lint／compile | `python3 -m compileall -q app scripts tests`（标准库）；**不引入 `ruff`／`flake8`／`mypy`／`coverage` 包**（Q-OS8 已裁决不允许） |
| 第 2 步 测试 | `DEMO_MODE=1 python3 -m pytest -q tests`（应 ≥ 80 passed） |
| 第 3 步 demo 冒烟 | `DEMO_MODE=1 python3 scripts/demo.py`（内含 `TestClient` 冒烟全部 7 组端点与 `/health` 全 fallback） |
| 第 4 步 评测 | `DEMO_MODE=1 python3 -m app.observability.evaluator`（退出码 0、`samples=8`、6 字段齐备） |
| 第 5 步 契约冒烟 | 内联 `python3 - <<'PY'`（**不新增文件／依赖**，仅用既有 `fastapi.testclient` + `app.schemas`）；断言 11 字段、非流式字段数 = 11、`/health` 无 `configured_backends` 且无新增字段、`answer` 含 `96`、SSE 序列 |
| 契约保护 | CI **不得**修改或校验时改动零改动文件；不得执行 `git` 写操作、不暴露端口；不得把 `configured_backends` 等生产模式字段写入 DEMO `/health` |

### 2.8 P0-BUG1／P0-BUG2 · 两个遗留缺陷修复清单

**BUG1（空环境变量）**：
- 根因：`load_dotenv_simple()` 将 `HOST=`／`PORT=`／`AGENT_MAX_STEPS=`／`AGENT_TOOL_TIMEOUT_SECONDS=`／`HUMAN_IN_LOOP=` 等空占位符解析为空串；`env_override()` 把空串当有效覆盖，`_coerce("", 8000, "server.port")` 转换失败抛 `ConfigError`。`.env.example` 中 `LLM_API_KEY=`／`LLM_BASE_URL=`／`LLM_MODEL=`／`LLM_VISION_MODEL=`／`ENCODER_LOCAL_MODEL_PATH=` 亦为空串（字符串键覆盖成空串虽不抛错，但语义同样应为「未覆盖」）。
- 修复口径（需求层面，不写代码）：**空串一律视为「未设置」，回落到 `config/settings.yaml` 默认值**；非空覆盖与类型转换逻辑不变，非法非空值仍抛可读 `ConfigError`；`DEMO_MODE=1` 最后一步无条件锁定三后端的行为不变；`.env.example` 模板形态不变（修复在解析／覆盖层，不在模板）。
- 回归用例（新增 pytest）：① 存在含空占位符的 `.env` 时 `get_settings()` 正常且数值／布尔键取 YAML 默认；② 非空覆盖生效；③ 非法非空值抛可读 `ConfigError`；④ 配置 `LLM_BACKEND=api`／`LLM_API_KEY` 且 `DEMO_MODE=1` 仍锁定 `template`／`stub`／`memory`。

**BUG2（不实声明）**：主理人实测「全仓无 `LLMClient.chat_stream` 类／方法」，但「已提供」类断言散落多处，**只改 README 一行会留下自相矛盾**。待修正清单：

| 位置 | 现状 | 处置 |
| --- | --- | --- |
| `README.md:154` | 「`LLMClient.chat_stream` 真实增量输出已提供但未挂主应答路径」 | **改为「本期未实现」口径**（主缺陷） |
| `docs/PRD.md:115`（P2-4）、`:263`（§4.7） | 「已提供但未挂主应答路径」 | 同步改为「本期未实现；原始规格 §8 曾提及该接口，本仓库未包含该类／方法」 |
| `docs/ARCHITECTURE.md:1389`（U8） | 「已提供但不挂主应答路径」 | 同上 |
| `docs/TASKS.md:256／276／454`、`app/generation/router.py:8` | 「不得改挂」中性措辞 | 可保留，建议统一术语 |
| **`docs/reference/platform-spec-README.md:648`** | 原始规格原文提及该接口 | 🔒 **字节级零改动**，属上游契约文档，**不得修正** |
| `web/index.html` | 无 | 🔒 零改动 |
| `README.md` §6（v1.2 新增） | — | **增加一句**：「`docs/reference/` 为原始规格清洗副本，描述目标态设计基线；实现状态以本 README 与 §6 为准」，用于消解「规格说已提供、实现说未实现」的表面矛盾；**不得改写 reference 原文** |

统一口径：「本期未实现 `LLMClient.chat_stream`；SSE `token` 恒由最终答案按 `agent.token_chunk_chars=24` 定长切片模拟；本期不新增该能力（原 PRD P2-4）」。

---

## 3. 「可运行／可复现／可维护」可验收判据（10 条）

> 全部使用 `docs/reference/platform-spec-README.md` §2 的等价 `python3` 命令（与 `README.md` §1、`docs/TASKS.md` §6 一致）。本机 `make` 不可用，但 **Makefile 四目标 `demo`／`test`／`run`／`eval` 必须存在且命令逐字一致**（M-4）。所有命令默认在项目根执行、`DEMO_MODE=1`。

**CI 工作流五步判据（对应 P0-OS5／§2.7；按主理人裁决由三步改为五步）**：五步须在同一个 `DEMO_MODE=1`、零联网零 Key 的 CI job 中依次执行，**每步退出码均为 0**。下表映射到本 §3 已有判据，不新增判据编号：

| 步 | CI 命令 | 对应判据 |
| --- | --- | --- |
| 1 | `python3 -m compileall -q app scripts tests` | M-2 |
| 2 | `DEMO_MODE=1 python3 -m pytest -q tests`（≥ 80 passed） | M-1 |
| 3 | `DEMO_MODE=1 python3 scripts/demo.py` | C-1 |
| 4 | `DEMO_MODE=1 python3 -m app.observability.evaluator`（`samples=8`、6 字段齐备） | C-2 |
| 5 | 内联 `python3 - <<'PY'` 契约冒烟（断言 11 字段、非流式字段数 = 11、`/health` 无 `configured_backends` 且无新增字段、`answer` 含 `96`、SSE 序列） | R-1／R-3 |

另须核对 `actions/setup-python` 的 `cache: "pip"` + `cache-dependency-path: requirements.txt`、job 级 `timeout-minutes` 与失败-fast（禁 `continue-on-error`／`|| true`／retry）。**§3 仍为 10 条判据（R-1～R-3／C-1～C-3／M-1～M-4），本表仅为五步映射，不改变判据编号与 P0-QA 验收口径。**

### 可运行

| 编号 | 命令 | 期望输出 |
| --- | --- | --- |
| R-1 | `DEMO_MODE=1 python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000`（真启动），另开终端 `curl -s http://localhost:8000/health` | 启动日志含「未实现鉴权…仅限本机或可信内网单机演示，勿暴露公网」；响应 `demo_mode=true`、`components.graph="pure"`、6 项可选依赖为 `fallback`（未安装时）、`components.index_chunks>0`、`version="1.0.0"`、顶层 `status`／`index_chunks` 存在；**DEMO 下不出现 `configured_backends`**，且无任何新增字段（§1.3.5） |
| R-2 | `curl -s http://localhost:8000/`、`curl -s http://localhost:8000/ui/index.html`、`curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs` | 前两者返回同一份 HTML 且含「多模态通用智能体开发平台」；`/docs` 返回 200 |
| R-3 | `curl -s -X POST http://localhost:8000/v1/chat -H 'Content-Type: application/json' -d '{"query":"计算 12*8 的结果","stream":false}'` | HTTP 200；响应**恰好 11 字段**；`answer` 含 `96`；`tool_results[]` 含 `calculator` 且 `ok=true`、`error` 字段存在 |

### 可复现

| 编号 | 命令 | 期望输出 |
| --- | --- | --- |
| C-1 | `DEMO_MODE=1 python3 scripts/demo.py` | 退出码 0；四模态各 ≥1 切片；`TestClient` 冒烟 7 组端点全通过；生成 `data/vector_index.json`／`data/traces.jsonl`（不启动服务器） |
| C-2 | 连续两次 `DEMO_MODE=1 python3 -m app.observability.evaluator` | 两次 `hit_rate`／`tool_hit_rate`／`avg_steps` **完全一致**、`samples=8`、6 字段齐备；落盘 `data/eval_report.json`。`avg_latency_ms`／`elapsed_ms`／`ts` 允许毫秒级波动（`README.md` §2 明确 `current_time` 与时间元数据不参与命中判定与确定性口径） |
| C-3 | `LLM_API_KEY=sk-should-not-leak DEMO_MODE=1 python3 scripts/demo.py 2>&1 \| grep -c "sk-should-not-leak"`（沿用 `docs/TASKS.md` §6 第 3 条） | 期望输出 **`0`**；且 `DEMO_MODE=1` 下 httpx 外部请求数为 0、生效后端仍为 `template`／`stub`／`memory` |

### 可维护

| 编号 | 命令 | 期望输出 |
| --- | --- | --- |
| M-1 | `DEMO_MODE=1 python3 -m pytest -q tests` | 退出码 0；基线 **80 passed**（含 `tests/test_edge_api.py`）+ BUG1 新增回归用例后仍全绿；测试用 `tmp_path` 隔离 `data/`，可重复运行、不污染仓库运行期文件 |
| M-2 | `python3 -m compileall -q app scripts tests` | 退出码 0，无语法错误（CI lint／compile 等价步骤，零外部依赖） |
| M-3 | `cp .env.example .env && DEMO_MODE=1 python3 -m pytest -q tests && DEMO_MODE=1 python3 scripts/demo.py` | **不抛 `ConfigError`**（BUG1 回归）；`server.port=8000`／`max_steps=8`／`tool_timeout_seconds=3.0` 取 YAML 默认；两步全绿。**自动化回归由 pytest 的 `env_sandbox` fixture 完成（monkeypatch `PROJECT_ROOT` → tmp_path，零落盘）；本条为命令行手工复现路径，`cp` 后必须删除 `.env` 并确认仓库根无残留**——`tests/conftest.py::_demo_env` 只重定向 `data_dir`／`tmp_dir`、**不重定向 `PROJECT_ROOT`**，而 `get_settings()` 读的是 `PROJECT_ROOT / ".env"`，直接在仓库根 cp 会留下真实 `.env` 污染后续验证 |
| M-4 | 文本核对 `Makefile` 四目标；全仓检索占位符与不实声明 | 四目标命令与规格 §2 逐字一致；**地址未到位（占位符版交付）时允许全仓存在 `__...__` 残留，但不得推送；S2 替换后交付文件中残留须为 0**（`docs/REPO_METADATA.md` 自身作为历史索引可保留符号说明）；项目自有文件中「`chat_stream` + 已提供／已实现」断言为 **0**；`docs/reference/*`、`web/index.html`、`requirements.txt`、`samples/knowledge.txt` 字节级零改动 |

---

## 4. 仓库地址依赖清单（重点）

### 4.1 统一占位符规范与集中登记

**背景**：用户要求「使用当前已配置的远程仓库，若未配置先提示提供地址」。主理人实测：项目目录**无 `.git`、无 remote**；GitHub 账号 `Nephets1010` 下无同名仓库（404）；工作区其它 24 个子仓库的 origin 属别的项目，**不得挪用**；已向用户索取地址，**尚未回复**。

**冻结规则（v1.2，按主理人裁决）**：地址缺失期间，全部 12 个 RP 点**只写占位符符号**，**禁止散落硬编码真实 URL、禁止臆造 owner／repo、禁止挪用工作区其它 24 个子仓库 origin**。

- **唯一登记处已改为 `docs/REPO_METADATA.md`**（第 10 个开源／元信息文件）：架构 v1.1 §5.1 口径为 11 个符号 + 12 个 RP 点 + 派生规则 + 6 列结构。本 PRD §4.1 表格降级为索引；完整符号清单／默认取值／替换后校验方式**以该登记表 §1 为准**，任何新增引用点须回填其 RP 表。
- **身份默认值（Q-OS3 裁决）**：作者／版权 holder = `Nephets1010`、年份 `2026`、邮箱 `Nephets1010@users.noreply.github.com`；登记为「默认取值，用户可替换」，**交付文件仍写占位符、S2 一次性替换**。
- ⚠️ **严格区分**：身份可用账号名；**URL 类一律不预填、仍禁止用账号 `Nephets1010` 拼装仓库 URL**（仓库名未确认、同名仓库 404）。`__SECURITY_CONTACT__` 待用户提供、`__RELEASE_DATE__` 待主理人填写，均禁止臆造。
- `__CI_BADGE_URL__` 由 `__REPO_URL__` 单向派生（`/actions/workflows/ci.yml/badge.svg`），不另设硬编码符号。

> **本表仅为索引**；权威清单（11 符号、默认取值、出现文件、替换后校验方式）见 `docs/REPO_METADATA.md` §1，派生规则见其 §3。

| 符号 | 含义 | 类别 |
| --- | --- | --- |
| `__REPO_URL__` | 完整仓库 URL（形如 `https://github.com/<OWNER>/<REPO>`；`<OWNER>/<REPO>` 须由用户提供） | URL |
| `__OWNER__` | 仓库 owner | URL |
| `__REPO_NAME__` | 仓库名（用于 `cd` 目录） | URL |
| `__CI_BADGE_URL__` | 由 `__REPO_URL__` 派生，不单独硬编码 | URL |
| `__AUTHOR_NAME__`／`__AUTHOR_EMAIL__` | 作者身份 | 身份 |
| `__COPYRIGHT_YEAR__`／`__COPYRIGHT_HOLDER__` | 版权年份与持有人 | 身份 |
| `__SECURITY_CONTACT__` | 安全／行为准则举报渠道（邮箱或私密报告入口） | 联系 |
| `__RELEASE_DATE__` | CHANGELOG／CITATION 发布日期 | 元信息 |

### 4.2 12 个地址／身份依赖点（必须填真实值才能最终定稿）

| 编号 | 位置 | 依赖内容 | 类别 |
| --- | --- | --- | --- |
| **RP-01** | `README.md` 顶部徽章行 | CI badge 的 img src + href（`__CI_BADGE_URL__`）、License badge 链接、Release／Stars badge（如启用） | URL |
| **RP-02** | `README.md` 快速开始 | `git clone __REPO_URL__` 与 `cd __REPO_NAME__` | URL |
| **RP-03** | `README.md` 开源章节 | Issues／Discussions／Pull Requests／Homepage 链接 | URL |
| **RP-04** | `pyproject.toml` `[project.urls]` | Homepage／Repository／Issues／Changelog／Documentation 共 5 个子键 | URL |
| **RP-05** | `pyproject.toml` `authors`／`maintainers` | `__AUTHOR_NAME__`／`__AUTHOR_EMAIL__` | 身份 |
| **RP-06** | `CITATION.cff` | `url`／`repository-code`／`identifiers`（如启用） | URL |
| **RP-07** | `CITATION.cff` `authors` | 姓名／邮箱／affiliation | 身份 |
| **RP-08** | `CONTRIBUTING.md` | 克隆命令、Issue／PR 链接、CI 检查链接 | URL |
| **RP-09** | `CODE_OF_CONDUCT.md` | 举报渠道（私密报告链接或 `__SECURITY_CONTACT__`） | URL／联系 |
| **RP-10** | `SECURITY.md` | 报告渠道（`/security/advisories/new` 或邮箱）、支持版本／公告链接 | URL／联系 |
| **RP-11** | `CHANGELOG.md` | 底部版本比较链接区（`[Unreleased]: __REPO_URL__/compare/...`） | URL |
| **RP-12** | `NOTICE` | `Copyright (c) __COPYRIGHT_YEAR__ __COPYRIGHT_HOLDER__` | 身份 |

**统计**：共 **12 个依赖点**，其中 **9 个需真实仓库 URL／联系渠道**（RP-01～04、06、08～11），**3 个需真实作者与版权身份信息**（RP-05、07、12）。此外 `__RELEASE_DATE__` 为元信息占位符，随同批替换。

### 4.3 地址到位后的收尾流程（S1–S7）

> ⚠️ **本 PRD 及工程师任务（#7）不得执行 S4–S6 中任何 git 操作**；主理人任务（#9）为「独立复核、本地提交并**停在推送前**」。推送须在用户提供地址并完成占位符替换后，由用户授权执行。

| 步骤 | 动作 | 完成判据 |
| --- | --- | --- |
| **S1** | 用户提供真实仓库 URL；主理人确认 owner／repo、目标可见性（public）。**Q-OS2 已裁决：不新建仓库**，本流程不含任何仓库创建动作 | 地址来源唯一、可核验；**不使用**工作区其它 24 个子仓库的 origin |
| **S2** | 一次性全量替换 §4.2 的 12 个依赖点占位符 | 全仓检索 `__REPO_URL__` 等全部符号 → **0 残留**；12 处 URL 完全一致；无臆造 owner／repo；无散落硬编码 |
| **S3** | 本地最终验证：§3 的 10 条判据 + P0-QA 全量回归 | 全部通过，退出码 0；零改动文件字节级核对通过 |
| **S4** | `git init`（当前无 `.git`）→ 配置 remote（**只用用户提供的地址**）→ 本地首次提交 | 提交包含 **10 个**开源／元信息文件（含 `docs/REPO_METADATA.md`）、`docs/PRD-OPENSOURCE.md`／`docs/ARCHITECTURE-OPENSOURCE.md`／`docs/TASKS-OPENSOURCE.md`、README 增补、两处缺陷修复与回归用例；`.gitignore` 已排除 `.env`、`data/` 运行期产物、`__pycache__`、`.pytest_cache`；**提交信息不含密钥** |
| **S5** | 用户授权后推送到远端 | 推送成功；反馈 commit hash、分支、文件数 |
| **S6** | 仓库设为 **public**；配置 description／homepage／topics／license | GitHub 自动识别 `LICENSE` 为 Apache-2.0；topics 与 keywords 一致；CI 首次运行通过、徽章生效 |
| **S7** | 向用户反馈 | 反馈三项：**推送结果**（hash／分支／文件数）、**仓库可见性**（public）、**开源配置状态**（license／topics／description／homepage／CI） |

**S4 与推送之间的关键约束**：若 S4 提交时地址仍未到位，提交内容必然含占位符；**推送前必须完成 S2 替换并追加一次提交**，严禁把占位符或臆造 URL 推入公开仓库。

### 4.4 地址缺失期间的冻结规则

1. 所有 12 个依赖点只写 `docs/REPO_METADATA.md` 登记的符号；**禁止**在任何文件硬编码真实或推测的仓库 URL。
2. 禁止依据账号 `Nephets1010` 或工作区其它子仓库 origin 拼装地址。
3. 地址未到位 → **交付占位符版**：全仓允许 `__...__` 残留（登记表自身作为历史索引可保留符号说明），但**不得推送**；本地提交可停在推送前（对齐 #9）。S2 替换后**交付文件**中占位符残留须为 0，公开仓库中不得出现占位符或臆造 URL。
4. 任何新增文件若需引用仓库地址，一律复用登记表符号并**回填 `docs/REPO_METADATA.md` 的 RP 表**，禁止新增未登记的硬编码位置。

---

## 5. 已知限制与如实披露（沿用原 PRD §4.7；🆕 标记为本期新增披露）

| 限制 | 本期处置 |
| --- | --- |
| **未实现鉴权、多租户、会话持久化与并发写入锁** | **如实披露，不偷偷补**。README、SECURITY.md、本 PRD、启动日志四方一致；明确「仅限本机／可信内网单机演示，勿暴露公网」；`/v1/chat` 流式与入库共享进程内索引，单机假设 |
| `0.0.0.0` 暴露风险 | Makefile `run` 与规格 §2 保持 `--host 0.0.0.0 --port 8000`；README 保留 `HOST=127.0.0.1 PORT=8000 DEMO_MODE=1 python3 -m app.main` 收紧方式；`SECURITY.md` 同步披露 |
| **DEMO stub 语义质量 ≠ 真实多模态大模型** | 命中率等指标仅用于链路正确性与回归验证，不代表业务准确率；README／CHANGELOG／CITATION 摘要均不得宣称模型效果或准确率 |
| **本期未实现 `LLMClient.chat_stream`** 🆕 | 统一口径见 §2.8：原始规格 §8 曾提及该接口，**本仓库未包含该类／方法**；SSE `token` 恒由定长切片模拟；本期不新增该能力（原 PRD P2-4） |
| SSE `token` 为定长切片模拟 | 同上；不得表述为「真实增量输出已提供」 |
| 图像／音频／视频 DEMO 仅产出描述性文本证据 | 不做真实图像生成／TTS／ASR；音频仅解析 PCM WAV；视频不可解码时降级确定性合成帧 |
| 内存向量库为暴力余弦扫描，适合万级以下切片 | `soft_limit=10000` 接近时只告警、不改检索口径；生产建议 Chroma／Milvus |
| `samples/eval.jsonl` 为自建 8 条小型基准 | 不含公开榜（MMBench／SEED），未使用 LLM-as-judge |
| Q7／Q9／Q10／Q15 既有裁决 | trace 不存在返回 200 空集；评测请求／响应 `samples` 同名不同义；`resume()` 仅图层 API、本期无 REST 恢复端点；无并发锁（见 `README.md` §6） |
| **开源化不改变上述任何限制** 🆕 | Apache-2.0 §7 免责声明与 §8 责任限制同向；**禁止**在 README／pyproject／CHANGELOG 出现「生产可用／企业级安全／90% 准确率／已实现鉴权」等过度声明 |
| **`.env` 与密钥边界** 🆕 | `.env.example` 仅占位符；`.gitignore` 忽略 `.env`；`SECURITY.md` 明确 API Key 不得进入 Issue／PR／日志／轨迹；`LICENSE`／`NOTICE` 不含真实凭据 |

---

## 6. 主理人裁决记录与剩余执行依赖

> **覆盖声明**：Q-OS1～Q-OS12 **已由主理人全部拍板，本 PRD v1.1 的「待确认问题／建议」整节作废，不再存在待确认决策门**。完整裁决索引以 `docs/ARCHITECTURE-OPENSOURCE.md` v1.1 §0.2 与 `docs/TASKS-OPENSOURCE.md` v1.1 §7 为准；冲突时以裁决 + 架构 v1.1 为准。`docs/PRD.md` §4 契约红线一字未动。

### 6.1 与本 PRD 直接相关的裁决要点

| 编号 | 裁决结论 | 本 PRD 修订位置 |
| --- | --- | --- |
| Q-OS1 | 统一占位符；新建 `docs/REPO_METADATA.md` 为唯一登记处；禁止臆造 owner／repo、禁止挪用其它 24 个子仓库 origin；推送前 S2 一次性全量替换，未替换不得推送 | §0.1、§4.1／§4.2／§4.4 |
| Q-OS2 | **不新建仓库**，只写地址到位后的 S1–S7 收尾流程 | §4.3 S1 |
| Q-OS3 | 作者／版权 holder = `Nephets1010`、年份 `2026`、邮箱 `Nephets1010@users.noreply.github.com`；登记为「默认取值，用户可替换」，交付文件仍写占位符、S2 替换；**URL 类仍禁止用账号拼装** | §4.1、§2.5 |
| Q-OS4／许可 | **Apache-2.0**（`LICENSE` 完整原文 + `NOTICE`），理由沿用 §2.4 | §2.4 |
| Q-OS5 | **不加 `[build-system]`**、不引入任何打包期依赖；补 `[tool.pytest.ini_options]`（仅 `testpaths`，不得破坏 80 用例）+ 可选 `[tool.coverage.*]` 纯配置（不装 coverage 包） | §2.5、P0-OS2 |
| Q-OS6 | CoC **自写精简版**，避免第三方原文版权争议 | §2.6 |
| Q-OS7 | CI 仅 **3.11**；多版本矩阵列 P2-OS1 | §2.7、P2-OS1 |
| Q-OS8 | **不允许**外部 lint（ruff／flake8／mypy／coverage 包）；CI 标准库五步 | §2.7 |
| Q-OS9／Q-OS10／Q-OS11 | 举报渠道 `__SECURITY_CONTACT__` 待用户提供；description／homepage／topics 与 pyproject 一致、S6 由主理人设定；发布日期 `__RELEASE_DATE__` 待主理人填写 | §4.1、§4.3 S6 |
| Q-OS12 | CI **不额外真启动**（`TestClient` 已冒烟全部端点）；真启动由 §3 R-1 本机验证 | §2.7、§3 |
| 版本号／BUG2 | `1.0.0` 五处一致、不得改业务代码凑入口点；BUG2 只修 4 处 + README §6 消解一句，reference 零改动 | §2.5、§2.8、P0-BUG2 |

### 6.2 剩余执行依赖（非决策门）

- **真实仓库 URL 仍待用户提供**（Q-OS1 裁决为「占位符版交付」）：地址到位后由主理人执行 S2 → S3 → S4 → 用户授权推送 → S5–S7。
- 地址未到位 → 按 §4.4 **不得推送**，全仓允许 `__...__` 残留；S1–S7 归主理人 #9，架构师／工程师／QA 均不执行 git 操作、不新建仓库。
- 用户／主理人后续若替换身份默认值、举报渠道或发布日期，只更新 `docs/REPO_METADATA.md` 一处并同步 S2，不改任何契约。

---

## 7. 文档状态与交接

- **状态**：已同步主理人裁决与 `docs/ARCHITECTURE-OPENSOURCE.md` v1.1 / `docs/TASKS-OPENSOURCE.md` v1.1；供 #7 工程师、#8 QA、#9 主理人按 §0.1 统一基线执行。
- **v1.2 修订记录（同步主理人 Q-OS1～Q-OS12 裁决 + 架构设计 v1.1，契约未变）**：新增 §0.1 基线优先级与覆盖声明（六处差异索引）；§6 由「待确认问题」改为「裁决记录与剩余执行依赖」；定点同步开源文件数 9→10（含 `docs/REPO_METADATA.md`）、P0-OS2 已裁决不加 `[build-system]`、P0-OS5／§2.7 CI 三步→五步、P0-BUG2／§2.8 增加 README §6 消解一句、§4.1 登记处与身份默认值、§4.3 S1 不新建仓库、§4.4 与 M-4 占位符版交付口径。已向 #7 工程师发出紧急基线更正，撤回 v1.1「与设计完全一致」的结论。**改动原因：v1.1 成文早于主理人 Q-OS1～Q-OS12 裁决，属时间线错位校准，非契约变更；`docs/PRD.md` §4 红线一字未动。** 另按主理人 v1.2 指令补充：文档开头醒目覆盖声明、§3 CI 五步判据映射表。
- **v1.1 修订记录（采纳 software-architect 核实结论，契约未变）**：① §1.3.5 澄清 `/health`「冻结 = 既有字段一个不删、新字段一个不增」——`version="1.0.0"` 必须保留且 R-1 要求存在，`configured_backends` 在 DEMO 下连键都不能输出；② P0-BUG1 与 §3 M-3 区分 pytest `env_sandbox` fixture（monkeypatch `PROJECT_ROOT` → tmp_path，零落盘）与命令行手工复现（`cp` 后必须删除 `.env`），并注明 `conftest.py::_demo_env` 不重定向 `PROJECT_ROOT`；③ P0-OS2／§2.5／Q-OS5 明确方案 A 下入口点为静态声明、不要求 `pip install -e .` 生效；④ Q-OS6 默认自写精简版 CoC。另确认：本轮唯一业务代码改动为 `app/config.py` 两处空串短路，`logging.py::collect_secrets` 已过滤空串无需改动；`MAP_` 前缀为既有契约而非本轮变更。
- **版本关系**：本文件是 `docs/PRD.md` v1.0 的**增量**，不替代原 PRD；冲突时以 `docs/PRD.md` §4 契约红线为最高优先级，本文件 §1.3 为其复述与冻结。
- **变更纪律**：§6 裁决项或 §4.2 依赖点若有增减，须以增量方式更新本文件并同步下游，**不得静默变更 §1.3 契约与 §4 占位符冻结规则**；任何变更须先核对 §0.1 基线顺序。
- **交付边界**：本 PRD 未写任何代码或开源文件、未执行任何 git 操作；推送动作须在用户提供仓库地址并完成 §4.3 流程后，由用户授权执行。
