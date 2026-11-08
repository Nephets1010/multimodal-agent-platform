# 更新日志

本文件遵循 Keep a Changelog 1.1.0 风格，
版本号与 `app/__init__.py::__version__`／`pyproject.toml`／`CITATION.cff` 保持一致。
本项目面向求职作品集／实训，记录以「可运行／可复现／可维护」为准，不宣称生产可用。

## [Unreleased]

### 新增

- 评测样本护栏：新配置键 `eval.max_samples`（默认 `100`）。`POST /v1/eval` 显式 `samples` 超过上限时返回 `400`（`detail` 同时含当前样本数与上限）；`{}` / 缺省仍走内置 8 样本路径，行为不变。
- 工具执行护栏：新配置键 `agent.tool_orphan_max`（默认 `8`），超时孤儿 worker 硬上限。工具可在硬超时前协作式取消自行退出（不产生孤儿）；连续硬超时达到上限后线程池换代隔离、新调用立即饱和拒绝。对外契约零变化：`ToolResult` 恒 5 字段、超时文案 `tool timeout after {timeout}s` 逐字不变。

### 变更

- 上传白名单同源化：`ingest.allowed_extensions` 成为扩展名判定与「仅允许 ...」错误提示的**唯一运行时来源**，改配置即改行为（模态键仅允许 `text`/`image`/`audio`/`video`，跨模态扩展名冲突或空白名单在启动期抛 `ConfigError`）。默认取值与 v1.0 内置白名单逐字一致，默认行为零变化。
- `README.md` §4/§5 同步披露上述新配置键、`/v1/eval` 样本上限与工具超时行为。

### 基线

- `DEMO_MODE=1 python -m pytest -q tests` = **274 passed**（247 基线 + 27 新增：评测护栏 / 白名单同源化 / 配置校验 / 工具超时与孤儿上限 / 线程池换代），`python -m compileall -q app scripts tests` 退出码 0。

## [1.0.0] - 2026-11-07

### 新增 · 开源要素（9 项）

- `LICENSE`：Apache-2.0 完整原文（条款零改写，含 §3 专利授权／§6 商标／§7 免责／§8 责任限制 + APPENDIX）。
- `NOTICE`：版权占位符行 + 10 个核心依赖与 6 个可选依赖归属。
- `pyproject.toml`：PEP 621 静态元信息（11 类字段，`version=1.0.0`，`requires-python>=3.11`，
  仅列既有 6 个可选包，入口点 `multimodal-agent-demo = "scripts.demo:main"`）；按 D2 方案 A 不含 `[build-system]`。
- `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` / `SECURITY.md`：贡献流程、自写精简版行为准则、
  安全披露（明确「无鉴权属设计边界而非漏洞」与 `0.0.0.0` 暴露风险）。
- `CITATION.cff`：CFF 1.2.0，可被 PyYAML 解析。
- `.github/workflows/ci.yml`：Python 3.11、全局 `DEMO_MODE=1`，五步流水线
  `compileall` → `pytest` → `scripts/demo.py` → `DEMO_MODE=1 python3 -m app.observability.evaluator`
  → 内联契约冒烟，零联网零 Key、无 secrets／外部 lint／产物上传。
- `README.md` §8 开源与社区：徽章与许可证、克隆、能力边界、贡献、行为准则、安全披露、引用与变更、致谢。
- `.gitignore`：追加 `dist/`／`build/`／`.mypy_cache/`／`.ruff_cache/`／`.coverage`，既有忽略项零删减。
- `docs/REPO_METADATA.md`：11 个符号（含派生）与 12 个 RP 点的集中登记与替换后校验方式。

### 修复 · 2 个遗留缺陷

- **BUG1 空环境变量**：`cp .env.example .env` 后 `get_settings()` 曾抛
  `ConfigError: 配置项 server.port 的环境变量值 '' 无法转换为 int 类型`。
  修复落点仅在 `app/config.py` 的 `load_dotenv_simple()`（解析层跳过空值）与
  `env_override()`（短别名与 `MAP_` 长格式命中空串时视为未设置）；空值回落
  `config/settings.yaml` 默认值，非空覆盖、非法值报错与 DEMO 最后一步三后端锁定均不变。
  新增 `tests/test_config_env.py` 4 条回归用例与 `tests/conftest.py::env_sandbox`
  （`PROJECT_ROOT` 隔离到 `tmp_path`，绝不在仓库根留 `.env`）。
- **BUG2 不实声明**：统一为「本期未实现 `LLMClient.chat_stream`；原始规格 §8 曾提及该接口，
  本仓库未包含该类／方法；SSE `token` 恒由最终答案按 `agent.token_chunk_chars=24` 定长切片模拟；
  本期不新增该能力（原 PRD P2-4）」。修正 `README.md`、`docs/PRD.md`、`docs/ARCHITECTURE.md`
  共 4 处；`docs/reference/*`（上游原始规格）与 `web/index.html` 字节级零改动。

### 文档一致性

- `docs/ARCHITECTURE.md` §3.1／§3.6 补注 `configured_backends: dict[str,str] | None`
  仅生产模式附加、DEMO 下由 `exclude_none=True` 剔除；§7 质量守卫清单零改动。
- `docs/PRD.md` 增加 1 行指向 `docs/PRD-OPENSOURCE.md` 的交叉链接；§4 契约红线零改动。
- README §6 补注：`docs/reference/` 是目标态设计基线，实现状态以本 README 与 §6 为准。

### 基线

- `DEMO_MODE=1 python3 -m pytest -q tests` = **80 passed**（含边界用例），新增 BUG1 回归后仍全绿。
- `python3 -m compileall -q app scripts tests`、`DEMO_MODE=1 python3 scripts/demo.py`、
  `DEMO_MODE=1 python3 -m app.observability.evaluator`（8 条样例、指标可复现）退出码 0。
- 契约零漂移：7 组端点、`UnifiedResponse` 11 字段、SSE 帧格式与事件顺序、DEMO `/health`
  响应逐字段冻结均保持不变。

### 未变更（如实声明）

本期**未**新增鉴权／多租户／会话持久化／并发写入锁，**未**接入真实增量输出，
**未**宣称生产可用或模型准确率；DEMO stub 语义质量仍不等价于真实多模态大模型。

[Unreleased]: https://github.com/Nephets1010/multimodal-agent-platform/compare/v1.0.0...main
[1.0.0]: https://github.com/Nephets1010/multimodal-agent-platform/releases/tag/v1.0.0
