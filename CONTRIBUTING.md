# 贡献指南

感谢你愿意为「多模态通用智能体开发平台」贡献代码或文档。本项目面向求职作品集／实训，
核心诉求是**契约零漂移、DEMO 零依赖可复现**，因此贡献前请先读完本节。

## 1. 开发环境

- Python **3.11+**（本机验证环境为 3.13，代码须保持 3.11+ 兼容语法）。
- 只安装 `requirements.txt` 声明的核心依赖：

  ```bash
  git clone https://github.com/Nephets1010/multimodal-agent-platform
  cd multimodal-agent-platform
  python3 -m pip install -r requirements.txt
  ```

- **不需要**任何 API Key、GPU、模型权重或可选依赖；`DEMO_MODE=1` 下 httpx 外部请求数为 0。
- 本机 `make` 不可用时，直接执行下列等价命令（Makefile 四目标与规格 §2 逐字一致）：

  ```bash
  DEMO_MODE=1 python3 scripts/demo.py                                      # = make demo（不启动服务器）
  DEMO_MODE=1 python3 -m pytest -q tests                                  # = make test
  DEMO_MODE=1 python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000  # = make run
  DEMO_MODE=1 python3 -m app.observability.evaluator                      # = make eval
  ```

## 2. 代码风格与硬约束

- 标准库优先，**零新增必需依赖**；禁止引入 `python-dotenv`／`jsonschema`／`ruff`／`flake8`／`mypy` 等表外包。
- 可选依赖（`langgraph`／`chromadb`／`openai-whisper`／`transformers`／`torch`／`openai`）只允许
  `importlib.util.find_spec` 探测 + 局部 `try/except ImportError` 降级，**禁止顶层硬 import**。
- DEMO 分支**禁用 Python 内置 `hash()`**（会随 `PYTHONHASHSEED` 随机化），一律 `hashlib`；
  `calculator` 使用受限 AST，**禁止 `eval`／`exec`**。
- 环境变量覆盖：规格 §4.6 历史短别名（不带前缀、优先，如 `DEMO_MODE`／`HOST`／`PORT`／
  `LLM_BACKEND`）与项目前缀长格式 `MAP_<SECTION>__<KEY>`；**裸 `<SECTION>__<KEY>` 不得被读取**。
  空串／空白值一律视为「未设置」，回落 `config/settings.yaml` 默认值。
- 日志走 `app/observability/logging.py` 的 JSON 行 Formatter，三出口强制脱敏；异常统一
  `{"detail": "可读中文"}`，**禁止**把堆栈或密钥直出 HTTP 响应。
- 保持契约：7 组端点、`UnifiedResponse` 恰好 11 字段、SSE `event:` + 单行 `data:` + `\n\n`、
  `meta → step* → token* → [human_required] → done` 顺序、`done` 与非流式同源。

## 3. 字节级零改动清单

以下文件是既有契约基线，**提交中不得出现它们的 diff**：

- `web/index.html`（前端事实契约）
- `requirements.txt`（核心依赖基线）
- `samples/knowledge.txt`（内置检索知识）
- `docs/reference/*`（上游原始规格，目标态设计基线）
- `Makefile` 四目标命令
- `config/settings.yaml` 的键名／取值域／默认值
- `.env.example` 模板形态（空占位符是模板要求）

## 4. 测试要求

- 提交前必须 `DEMO_MODE=1 python3 -m pytest -q tests` 全绿，且 `python3 -m compileall -q app scripts tests` 退出码 0。
- 新增缺陷修复须附带回归用例；涉及 `.env`／配置读取的用例用 `tests/conftest.py::env_sandbox`
  把 `PROJECT_ROOT` 隔离到 `tmp_path`，**绝不在仓库根生成真实 `.env`**。
- 测试用 `tmp_path` 隔离运行期 `data/`，可重复运行、不污染工作树。
- 边界用例至少覆盖：空／超长 query、未知扩展名与畸形文件、非法 JSON、空索引与损坏索引、
  工具超时、超 `max_steps`、`trace_id` 不存在、SSE 客户端断连、可选依赖缺失、配置 Key 但仍 DEMO。
- CI（`.github/workflows/ci.yml`）五步：`compileall` → `pytest` → `scripts/demo.py` →
  `DEMO_MODE=1 python3 -m app.observability.evaluator` → 内联契约冒烟；不引入外部 lint、
  不安装可选依赖、不使用 secrets。

## 5. 提交与 Pull Request 流程

1. 从主分支建一个短命名分支，改动尽量聚焦单一问题。
2. 本地跑完上述四条等价命令 + `python3 -m compileall -q app scripts tests`。
3. 提交信息用简洁中文／英文描述**做了什么、为什么**，不要写 API Key、Token 或任何凭据。
4. PR 描述请注明：是否触碰零改动清单、是否改变对外契约、新增/修改了哪些测试、真跑的命令与输出结论。
5. 若改动涉及 `docs/PRD.md` §4 契约红线，须先回报维护者并经确认，**不得静默变更**。
6. 代码评审关注：契约零漂移、确定性、脱敏、降级可观测、跨文件 import 闭环。

## 6. Issue 规范

- Bug：给出可复现命令、`DEMO_MODE` 取值、Python 版本、真实输出与期望输出。
- 功能建议：说明是否影响 7 组端点／11 字段／SSE 顺序，以及是否需要新增依赖。
- **安全相关信息不要用公开 Issue 报告**，请走 `SECURITY.md` 的私密渠道。
- 请勿在 Issue／PR／日志／轨迹中粘贴 `LLM_API_KEY`、Authorization 头、Bearer Token 或上传文件正文。

## 7. 相关文档

- 快速开始与架构：`README.md`
- 增量 PRD：`docs/PRD-OPENSOURCE.md`；行为契约（最高优先级）：`docs/PRD.md` §4
- 架构与任务分解：`docs/ARCHITECTURE.md`／`docs/TASKS.md`、增量版 `docs/ARCHITECTURE-OPENSOURCE.md`／`docs/TASKS-OPENSOURCE.md`
- 占位符登记与替换后校验：`docs/REPO_METADATA.md`
- 社区链接：Issues／Pull Requests／CI 检查的完整 URL 见 `pyproject.toml` 的 `[project.urls]`
  与 `docs/REPO_METADATA.md` 的 S2 执行记录。
