# 技术债与优化空间审计清单

> 审计日期：2026-11-08 · 基线：`8fcf22b` · 代码规模：41 个 Python 文件 / 7319 行 / 139 条用例
> 排查方式：四路并行只读审计（业务流程与一致性 / 架构与性能 / 代码级技术债 / 测试覆盖与稳定性），
> 全部条目须附「文件:行号 + 可复现证据」；主理人对 P0 项独立复现后汇编分级。
>
> **分级口径**：
> - **可立即修复** = 根因明确 + 局部最小改动 + 有可执行验证判据 + 不改变对外契约/业务行为 + 无需用户决策。
> - **需进一步确认** = 涉及对外行为/数据格式/并发模型/评测口径变化，或改动面大、信息不足、需产品决策。
> - 风险等级（高/中/低）指**问题本身的影响**，与「修复动作的风险」分开评估。

---

## 1. 问题清单总览

| 来源 | 条目数 | 可立即修复 | 需进一步确认 |
| --- | --- | --- | --- |
| 业务流程与功能一致性（PM） | 9 | 8 | 1 |
| 架构 / 性能 / 稳定性（架构师） | 9 | 4 | 5 |
| 代码级技术债（工程师） | 21 | 13 | 8 |
| 测试覆盖与稳定性（QA） | 20 | 17 | 3 |
| **合计（未去重）** | **59** | **42** | **17** |
| **去重合并后** | **52** | **37** | **15** |

去重说明：`A-02 ≈ TD-19`（原子写，合并）、`B-01 ≈ TD-15`（event loop 阻塞，合并）、
`B-02 ≈ TD-10`（检索热点，合并）、`B-04 ≈ TD-21`（超时线程，合并）、
`BF-02 ≈ TD-18`（SSE 兜底 done，合并）、`BF-01` 与 `TD-14` 为不同问题不合并。

---

## 2. 已实施优化（可立即修复，本期落地）

### 2.1 稳定性 / 数据正确性

| ID | 问题 | 影响范围 | 风险 | 优先级 | 修复 |
| --- | --- | --- | --- | --- | --- |
| A-01 | 并发 `ingest` 与检索触发 `RuntimeError: dictionary changed size during iteration`（`store.py:77` 无快照） | 单 worker 内上传同时提问 → 检索线程崩溃 | 高 | P0 | `search()` 改 `list(...)` 只读快照，跳过无向量项；`all_chunks()` 同步；不引入写入锁 |
| A-02 | `vector_index.json` 非原子写，中断留下截断 JSON，下次启动清空全部切片 | 进程被 kill / 磁盘满 → 用户上传数据丢失 | 中 | P1 | `persist()` 改同目录 tmp + `replace` 原子写，异常清理 tmp；payload 格式不变 |
| A-03 | `_ctx()` 懒装配「检查-赋值」无保护，并发可创建多个组合根 | 数据视图不一致（不崩溃） | 低 | P2 | 模块级 `threading.Lock` + 双重检查，仅保护 once 初始化 |
| A-04 | `main.py` lifespan 用 import 期 settings 快照，与懒装配路径配置来源不一致 | 同进程运行时改配置时两条路径取值不同 | 低 | P2 | lifespan 改 `build_context()`；import 期 settings 保留供日志/校验 |
| BF-01 | SSE `done` 轨迹落盘晚于帧下发，收到 done 立即回放缺 `done` 事件 | 轨迹回放链路完整性 | 中 | P1 | `graph.py` 把 `_emit_trace(..., "done")` 移到 `yield done` 之前；帧顺序/字段不变 |

### 2.2 输入校验 / 错误反馈

| ID | 问题 | 影响范围 | 风险 | 优先级 | 修复 |
| --- | --- | --- | --- | --- | --- |
| TD-01 | 文件名无长度上限，`save_temporary` 抛 `FileNotFoundError` 未被捕获 → HTTP 500 | `/v1/ingest` 错误分层与可读反馈 | 高 | P0 | `sanitize_filename` 加 128 字符上限；`routes.py` 补 `except OSError` → 400 |
| TD-02 | float 型配置接受 `nan`/`inf`，绕过正数校验 | 检索得分、工具超时、排序确定性 | 高 | P0 | `_coerce` 对 float 加 `math.isfinite` 判断，非有限值抛可读 `ConfigError` |
| B-03（局部） | 配置漂移时扩展名错误提示与实际判定来源不一致（提示撒谎） | 上传排障可解释性 | 中 | P1 | `detect_modality` 错误提示统一用 `MODALITY_BY_EXT`；准入行为零变化 |

### 2.3 可观测性（日志 / 脱敏 / 诊断）

| ID | 问题 | 影响范围 | 风险 | 优先级 | 修复 |
| --- | --- | --- | --- | --- | --- |
| TD-07 | `_SECRET_PATTERN` 的 `sk-` 无词边界，普通词（`task-list`/`mask-value`/`disk-space`）使整行日志被吞 | 日志诊断字段丢失 | 中 | P1 | 仅给 `sk-` 加 `(?<![A-Za-z0-9])` 与 `{8,}`；其余分支与整行脱敏强度不变 |
| TD-08 | `JsonFormatter` 只对 `message` 脱敏，`trace_id` 等 extra 字段原样输出且不截断 | 脱敏遗漏路径、日志膨胀 | 中 | P1 | event/component/trace_id/extra 统一 `redact_text`（含 512 截断） |
| TD-09 | 异常堆栈与 message 共用 512 截断，traceback 丢关键帧 | 生产排障 | 中 | P1 | traceback 单独 4096 上限（头 2048 + 尾 2048 保留最内层帧）；message 仍 512 |
| TD-03 | 轨迹写入失败被 `except: pass` 完全静默 | 轨迹可回放性 | 中 | P1 | 加 `trace_emit_failed` warning，仍不影响主链路 |
| TD-04 | `reflector_node` 静默吞检索器异常，故障伪装成成功 | 降级可观测性 | 中 | P1 | 加 `retriever_failed` warning；不改 status/响应字段 |
| TD-05 | 临时上传文件删除失败静默，正文残留磁盘 | 上传正文保密性 | 中 | P1 | 加 `tmp_cleanup_failed` warning |
| TD-06 | 配置/轨迹文件读取失败静默 → 伪装成「0 样例」「轨迹不存在」 | 指标可信度、回放排障 | 中 | P1 | 加 `eval_samples_unreadable` / `trace_unreadable` warning，区分「文件不存在」 |
| TD-18（低风险子集） | SSE 生成异常 `logger.error` 无堆栈 | 服务端诊断 | 中 | P1 | 补 `exc_info=True`；**不改** emergency `done` 帧语义 |

### 2.4 局部性能（输出逐位不变）

| ID | 问题 | 影响范围 | 风险 | 优先级 | 修复 |
| --- | --- | --- | --- | --- | --- |
| TD-11 | `tracer.replay()` 一次 `read_text()` 全量读入解析 | `/v1/trace` 延迟与内存 | 中 | P1 | 改流式逐行解析；返回顺序/字段不变 |
| TD-12 | `StubEncoder` 对每个字符单独 `sha256`，无字符级缓存 | 每次灌库与 query 编码 | 低 | P2 | 模块级 `lru_cache` 包字符/token 摘要 |

### 2.5 文档与实现一致性（零代码风险）

| ID | 问题 | 修复 |
| --- | --- | --- |
| DC-01 | `CHANGELOG.md` / `CONTRIBUTING.md` 仍称 CI「三步」，实际五步 | 改为五步并与 `ci.yml` 逐项对齐 |
| DC-02 | 4 个交付文件 6 处仍以现在时声明「占位符／地址未到位／替换完成前不得推送」，与已公开仓库矛盾 | 改为「S2 已完成、仓库已公开，见 §6」；真实 URL/邮箱/版权行零改动 |
| DC-04 | `CHANGELOG.md` 称「9 个统一占位符」，登记表为 11 符号 | 改为「11 个符号（含派生）与 12 个 RP 点」 |
| DC-05 | 登记表 §1 身份默认值/校验方式与 §6 实际取值冲突 | 标注「已被用户确认值替换」，校验改为与 §6 一致 |
| DC-06 | §3 判据要求 `blob/main` 无残留，但 `main` 正是最终取值 | 改为「分支段须与 §6 实际取值一致」 |
| FC-01 | `README.md` 的 `evidences[]`/`tool_calls[]` 嵌套字段枚举不完整 | 补 `source_id` / `id`；顶层 11 字段不变 |

### 2.6 测试加固（假绿断言 / 覆盖补充）

由 QA 实施，全部只改 `tests/`：
- **P0 假绿加固 6 条**：`QA-T01` 状态序列化全字段、`QA-T02` routes 级 SSE 断连、`QA-T05` `strategy == "hybrid"` 正面断言、`QA-T06` 评测指标语义、`QA-T07` capsys→caplog 覆盖日志通道、`QA-T08` 宿主环境变量清理。
  排查期负向验证证明 NEG-1~6 与 V1 共 7 次「改坏源码仍 139 passed」，属真实假绿。
- **覆盖补充**：`QA-T03/T04/T10/T11/T12/T13/T16/T17` —— 新建 `test_edge_generation.py`、`test_edge_evaluator.py`、`test_edge_guards.py` 等，覆盖 generation 生产分支、evaluator 分支、guards 边界、store 损坏恢复、日志脱敏边界、幂等。
- **本次修复定向回归**：新建 `test_audit_regressions.py`，覆盖 A-01/A-02/BF-01/TD-01/TD-02/TD-07/TD-11/TD-12 的修复后行为。

---

## 3. 需进一步确认（本期只记录，未改动）

| ID | 问题 | 风险 | 优先级 | 原因 | 影响 | 后续处理 / 需补充信息 |
| --- | --- | --- | --- | --- | --- | --- |
| BF-02 / TD-18 | SSE 生成异常兜底 `done` 报 `status=ok` 且 `answer=""`，前端显示「完成（SSE）」 | 中 | P1 | 改 `status` 会改变**异常路径对外语义**与业务结果 | 故障对客户端不可感知，仅服务端日志可查 | 需确认是否接受「异常路径 `status=error` + 可读提示」；若否，维持现状并在 README 披露 |
| TD-14 | HTTP 成功响应绕过脱敏：完整 prompt / 工具异常原文 / 内部路径进入 `answer`、`tool_results[].error`、SSE `step` | 高 | P0 | 改 `answer` 会破坏模板四段式与 `eval.jsonl` 命中口径（`hit_rate` 现 1.0） | 与 SECURITY.md「完整 prompt 不得进 API 响应」口径冲突 | 需确认是否允许改 `UnifiedResponse.answer` 内容、`hit_rate` 变化；可先做低风险子集（清洗 `error`/`last_observation`，不动 answer） |
| B-01 / TD-15 | `async def` 端点内同步执行 `graph.run` / `evaluator.evaluate`，阻塞 event loop（实测 5ms 心跳静默 316ms） | 中 | P1 | 改 `run_in_threadpool` 改变并发模型，且会放大 A-01 类竞争；与「无并发写入锁」披露边界相邻 | 单请求期间同 worker 其他请求停摆 | 需确认目标并发模型 / 是否允许多 worker；若维持单机串行演示，则 README 补一句说明 |
| B-02 / TD-10 | 每次检索重算文档范数与 BM25/重排（N=1000 时单次 86ms，79% 耗在重复 norm） | 中 | P1 | 缓存涉及 `_chunks`/`_vectors` 结构与索引变更失效；`version:1` 格式是否演进需决策 | 万级切片时单次提问约 0.9s | 需确认是否允许演进 `vector_index.json` 格式、万级是否真实目标负载；可先做纯算法项（`heapq.nlargest`） |
| B-03（完整） | `settings.yaml` 的 `allowed_extensions` 不参与上传准入判定，配置形同死键 | 中 | P1 | 配置化属上传准入行为变更，需同步 2 文件 + MIME 兜底 | 改配置不改行为 | 本期已做局部修法（错误提示同源）；需确认 Q3 是否要求运行时可调整 |
| TD-16 | `/v1/eval` 请求 `samples` 无数量上限（n=200 实测 5.8s） | 中 | P1 | 加上限会拒绝当前被接受的请求，默认值属产品决策 | 单请求可长时间占用 worker | 需确认上限值 / 是否要分页或异步任务 |
| TD-17 | 上传「先整体 `read()` 再校验大小」，11MiB 文件已全量进内存 | 中 | P1 | 需改 `UploadFile.read()` 用法并确认 Starlette `max_part_size`/SpooledTemporaryFile 行为 | 多文件/大文件内存放大 | 需确认是否允许应用层流式读取、单块大小 |
| TD-19（增量写部分） | 每次 ingest 全量重写索引 JSON（1000 chunks / 2.07MB / 44ms） | 中 | P1 | 增量写会改持久化格式或写入策略 | ingest 延迟随 N 线性 | 本期已完成**原子写**；增量写需确认索引文件是否外部可读产物 |
| TD-20 | 上传 `text` 字段无应用层上限；MIME 与扩展名未做一致性双校验 | 低 | P2 | 两者都改变请求接受范围，且需新增配置键 | 放大与模态判定可解释性 | 需确认 text 上限目标值、MIME 不一致是拒绝还是仅告警 |
| TD-21 / B-04 | 工具超时后运行中线程无法取消，`max_workers=4` 可被连锁占满 | 中 | P1 | Python 无法强杀线程，彻底修复需进程池或协作式取消点 | 生产模式慢工具连续超时后整体可用性 | 需确认是否仅治理生产模式、是否允许进程池 |
| B-05 | `AgentTracer.emit()` 每条轨迹 open/write/close 同步 IO 在关键路径 | 低 | P2 | 改常驻句柄需重定义 `close()`、flush 与多进程 append 安全 | 随轨迹数量线性增长 | 当前「不持有句柄」反而利于异常恢复；需确认是否要求异步化（会引入丢失风险） |
| QA-T18 | CI 五步不校验评测指标语义、Makefile 四目标、Windows CRLF 反护 | 中 | P1 | 需改 `ci.yml` / `Makefile`（非测试文件），超出本轮授权 | 三类退化仍靠人工发现 | 需确认是否允许扩 CI 面、是否接受时长增加 |
| QA-T19 | 并发/无锁条件下不应新增并发断言 | 低 | P2 | 无锁是已披露设计决策，加断言会固化未定义行为且 flaky | 若未来加锁需重新定义契约 | 需确认是否把「无锁」升级为「加锁」 |
| QA-T20 | CI 仅 Python 3.11，本机 3.13 无 CI job | 低 | P2 | 架构 v1.1 已把多版本矩阵列 P2、本期不做 | 跨版本兼容性 | 需确认是否接受额外 runner 成本 |
| DC-03 | 设计文档群仍以「当前状态（地址未到位）」描述，与 S2 记录冲突 | 低 | P2 | 属历史流程记录，保留时态便于追溯；大范围改写易引入基线漂移 | 内部文档时态标注 | 已在 §5/§6 声明 S2 完成；后续可在文档版本升级时统一时态 |
| TD-13 | 组合根装配 `AnswerGenerator` 门面 / `started_at` 等未被读取 | 低 | P2 | 死代码删除属清理而非缺陷，且需确认公开 API 兼容性 | 可维护性、装配开销 | 后续版本统一清理，标注为预留扩展点 |

---

## 4. 排查中确认「未发现问题」的部分（如实记录）

- **架构边界守住**：`config/schemas` 未被业务模块反向依赖；`store.py` 不 import modalities（组合根注入 `TextProcessor`）；`routes.py` 不 import `main`；`build_context()` 仍是唯一组合根（main / demo.py / conftest.py 三处复用）；`main.py` 装配在 lifespan，无 import 期业务装配副作用。
- **无两套业务逻辑**：`PureStateMachine` 与 `LangGraphCompiled` 共用同一份 `NODE_FUNCTIONS`/`EDGE_SPEC`/`CONDITIONAL_EDGES`；`UnifiedResponse(` 构造点唯一（`generation/router.py`）；`format_sse` 业务调用点唯一；四模态共用 `ModalityChunk`，视频抽帧复用 `ImageProcessor`。
- **无 O(n²) 融合隐患**：`retriever.py` 线性遍历 + 一次 `sort`，`by_id` 为 dict O(1) 查找。
- **SSE 路径完整性**：同步 generator 由 Starlette `iterate_in_threadpool` 承载，不直接阻塞 event loop；断连 `finally` 与 `cleanup_temporary` 齐备。
- **受限 AST 计算器未发现绕过**：9 个 payload 全部被拒；深度上限 24、长度上限 256 生效；无 `eval`/`exec`、无内置 `hash()` 实际调用。
- **零字节 / 畸形 / 不可解码媒体降级正确**：`empty.txt`、`zero.png`、`bad.wav` 均返回 200 total=0 且写 `modality_failed` warning，无 500。
- **主业务链路无逻辑断点**：ingest → 检索 → Planner/Worker/Reflector → 工具 → 应答 → 评测无状态丢失；`replan_count` 保证重规划一次后收敛，`guard_steps` 有硬上限。
- **非流式与 SSE 同构造**：均调 `build_unified_response`，字段集合一致；`/health.components` 取 `effective_backends`，与披露一致；错误响应统一 `{"detail": ...}`，无堆栈直出。
- **稳定性未发现异常**：连续 3 次全量结果一致、用例顺序无依赖、仓库根无 `.env`/`data/` 残留、无后台进程。
- **零改动基线保持**：`requirements.txt` / `samples/knowledge.txt` / `web/index.html` / `docs/reference/*` 字节级未变。

---

## 5. 变更影响范围

- **源码**：`app/rag/{store,encoder}.py`、`app/api/{routes,guards}.py`、`app/agent/{graph,nodes}.py`、`app/observability/{logging,tracer,evaluator}.py`、`app/config.py`、`app/main.py`、`app/modalities/base.py`（共 13 个文件）。
- **文档**：`README.md`、`CHANGELOG.md`、`CONTRIBUTING.md`、`SECURITY.md`、`NOTICE`、`pyproject.toml`、`docs/REPO_METADATA.md`。
- **测试**：`tests/` 下既有断言加固 + 新建 `test_audit_regressions.py`（11 条定向回归）、`test_edge_evaluator.py`、`test_edge_generation.py`、`test_edge_guards.py`；用例 139 → 247。另修复 1 处测试侧时序竞态（QA-T21，见 §6.8），仅改测试等待方式，不动产品代码。
- **不变**：7 组对外端点、`UnifiedResponse` 11 字段、SSE 事件顺序、`done` 恒末帧、DEMO `/health` 响应字段集合、配置键兼容性、`requirements.txt` 依赖、索引持久化格式、评测命中口径、模板答案内容、四个零改动文件。
- **行为变化（仅缺陷路径）**：超长文件名从 500 变为 400 可读提示；`nan`/`inf` 配置从「静默接受」变为可读 `ConfigError`；日志不再误吞普通词；`done` 轨迹在帧下发前落盘。正常路径业务结果不变。

---

## 6. 验证结果

> 口径：**只记录实际执行过的命令与真实输出**；未执行或环境不可用的项目一律标注「未验证」，不标通过。
> 执行环境：Windows 11 / Python **3.13.12** / `DEMO_MODE=1`（零 API Key、零联网、零权重下载）。
> 执行人：QA（独立全量回归）+ 主理人（合并态独立复跑，不复用 QA 输出）。

### 6.1 用例规模变化

| 项 | 基线（`8fcf22b`） | 本期 | 变化 |
| --- | --- | --- | --- |
| 测试文件 | 11 | 15 | +4（`test_audit_regressions` / `test_edge_evaluator` / `test_edge_generation` / `test_edge_guards`） |
| 用例数 | 139 | **247** | **+108（+77.7%）** |
| 结果 | 139 passed | **247 passed, 1 warning** | 0 failed / 0 skipped |

### 6.2 五步验证（与 `.github/workflows/ci.yml` 逐字等价，主理人合并态复跑）

| 步 | 命令 | 结果 | 关键输出 |
| --- | --- | --- | --- |
| 1/5 | `python3 -m compileall -q app scripts tests` | **通过** | rc=0，无 SyntaxError |
| 2/5 | `DEMO_MODE=1 python3 -m pytest -q tests` | **通过** | `247 passed, 1 warning in 6.49s`；连续 5 次全绿 |
| 3/5 | `DEMO_MODE=1 python3 scripts/demo.py` | **通过** | 四模态入库 + 轨迹 + 全部 7 组端点冒烟；`frames=99 order_head=['meta','step','step','step'] last=done`；`fields=11 has_96=True` |
| 4/5 | `DEMO_MODE=1 python3 -m app.observability.evaluator` | **通过** | 8/8 命中，`hit_rate=1.0 tool_hit_rate=1.0 avg_steps=2.875 avg_latency≈45.2ms`，rc=0 |
| 5/5 | 内联契约冒烟（不新增文件/依赖） | **通过** | `contract smoke OK`；`health keys=['components','demo_mode','index_chunks','status','version']`；`components=11`；`response fields=11`；`frame[0]=meta frame[-1]=done`；`set(done)==set(非流式 JSON) → True` |

### 6.3 负向验证（回退修复 → 用例必须转红 → 恢复 → 转绿）

QA 以「回退单点修复」方式独立完成 **7/7 全部转红**；主理人另以不共享 QA 上下文的方式**抽样 2 项**复核：

| 项 | 回退动作 | 期望 | 实际 |
| --- | --- | --- | --- |
| BF-01 `done` 轨迹时序 | 把 `_emit_trace(..., "done")` 移回 `yield ("done", ...)` 之后 | 转红 | **红**：`assert 'step' == 'done'`（`events[-1]["event"]` 为 `step`）；恢复后 **绿** |
| TD-01 超长文件名 | 同时移除 `sanitize_filename` 的 128 上限**与** `routes.ingest` 的 `except OSError → IngestError(400)` | 转红 | **红**：`FileNotFoundError: [Errno 2] ... 322506510d4c4b12a204d026cbe5695b_aaaa….txt`（原始缺陷）；恢复后 **绿** |

> TD-01 说明（如实记录）：该缺陷有**双层防御**（准入校验 + 落盘异常映射）。**只回退任一层时用例仍绿**——另一层会把同样的 400 返回给调用方。用例钉住的是对外行为（400 + 可读提示），不是某一层实现，这是刻意的；要证明它确实覆盖缺陷，必须两层同时回退，如上表。

### 6.4 环境变量矩阵（真实子进程，非 mock）

| 场景 | 结果 |
| --- | --- |
| `DEMO_MODE=1` 默认 | rc=0，`max_steps=8 demo=True` |
| `MAP_AGENT__MAX_STEPS=7` 长格式覆盖 | rc=0，`max_steps=7`（长格式生效） |
| `MAP_SERVER__PORT=` 空白串 | rc=0，回落到默认 `8000`（不再抛「无法转换为 int」） |
| `MAP_AGENT__MAX_STEPS=` 空白串 | rc=0，回落到默认 `8` |
| `MAP_AGENT__MAX_STEPS=abc` 非法值 | rc=1，`ConfigError: 配置项 agent.max_steps 的环境变量值 'abc' 无法转换为 int 类型` |
| `MAP_RETRIEVAL__DENSE_WEIGHT=nan` / `inf` / `1e400` | rc=1，`ConfigError: … 必须是有限数值，收到 'nan'`（TD-02 修复点） |
| `MAP_RETRIEVAL__DENSE_WEIGHT=0.7` 合法值 | rc=0，取值生效（未误伤） |
| `DEMO_MODE=0` 生产模式（模板后端兜底） | rc=0，`demo=False`，未因缺 Key 崩溃 |

### 6.5 真实端口验证（`uvicorn --host 127.0.0.1 --port 8077`，非 TestClient）

| 请求 | 结果 |
| --- | --- |
| `GET /health` | 200；键集 5 个；`components` 11 项；`status=degraded`（DEMO 下可选依赖均为 fallback，符合披露）；**无** `configured_backends` |
| `POST /v1/chat` 非流式 | 200；11 字段；`answer` 含 `96`；`evidences` 5 条含 `source_id` |
| `POST /v1/chat` 流式 | 首帧 `event: meta`，末帧 `event: done` |
| `GET /v1/tools` | 200；4 个工具，`calculator` 参数 schema 完整 |
| `POST /v1/eval {}` | 200；`hit_rate=1.0 tool_hit_rate=1.0 samples=8` |
| `POST /v1/ingest` 正常文件 | 200；`total=1`，`chunk_id/source_id/modality/snippet` 齐备 |
| `POST /v1/ingest` 129 字符文件名 | **400**；`{"detail":"文件名过长（最多 128 字符），请缩短后重试"}`（TD-01 修复点） |
| `POST /v1/ingest` `.exe` | **400**；`{"detail":"不支持的扩展名 .exe，仅允许 …"}` |
| `POST /v1/ingest` 空文件 | 200；`{"chunks":[],"total":0}`（降级不报 500） |
| `POST /v1/ingest` 纯 `text` | 200；`total=1`，`source_id=webui:pasted.txt` |
| `GET /v1/trace/{id}` | 200；`events` 含 `planner` 快照与 `step` 记录 |
| `GET /v1/nope` / `GET /v1/ingest` | 404 / 405（框架默认，语义正确） |

### 6.6 安全与脱敏

| 用例 | 输入 | 输出 | 判定 |
| --- | --- | --- | --- |
| 普通词不被误吞（TD-07） | `task-list processed 10 items` | `task-list processed 10 items` | **通过**（修复前为 `ta***REDACTED***`） |
| 同上 | `risk-free risk-level task-based` | 原样保留 | 通过 |
| Bearer 令牌 | `Authorization: Bearer secret-token` | `***REDACTED***` | 通过（强度未削弱） |
| 明文密码 | `password=hunter2` | `***REDACTED***` | 通过 |
| `sk-` 密钥 | `sk-` + 20 位字母数字假串（此处不复述原文，避免本文件自身被静态凭据扫描命中） | `***REDACTED***` | 通过 |

### 6.7 零改动与字节一致性

- `requirements.txt` / `samples/` / `web/` / `docs/reference/`：`git diff --stat` 与 `git status` 均为 **0 行**（未改动）。
- 受保护文件哈希守护 `-k protected_files`：**1 passed**（已归一化 `\r\n → \n` 后再比对，避免 Windows 工作区 CRLF 与 git 索引 LF 造成假红）。
- `git ls-files --eol` 实测 `requirements.txt`/`samples/knowledge.txt` 为 `i/lf w/lf`，`web/index.html`、`docs/reference/*` 为 `i/lf w/crlf` → 归一化断言与平台无关。
- 索引持久化格式未变：`data/vector_index.json` 顶层键仍为 `['chunks','vectors','version']`，`version=1`，`chunks` 与 `vectors` 条数相等。

### 6.8 本轮验证中发现并已修复的测试侧缺陷（QA 自检遗漏项，如实登记）

| ID | 现象 | 根因 | 处置 |
| --- | --- | --- | --- |
| QA-T21 | `tests/test_edge_api.py::test_sse_disconnect_via_streaming_response` 在**全量套件**下间歇失败（3 次中 2 次 `sse_completed` 未捕获），单跑 6/6 稳定 | 测试退出 `with` 只完成客户端侧关闭；生成器 `finally` 在 anyio 工作线程中异步执行，负载下晚于断言读取 `caplog`，属**测试侧时序竞态**而非产品缺陷 | 改为**有界轮询**（上限 2s，10ms 步进）等待收尾日志出现；判据不变（两个事件必须出现其一）。修复后全量**连续 5 次 247 passed** |
| QA-T22 | 本文档 §6.6 曾直接复述脱敏用例的 `sk-` 假串原文，被仓库自带静态凭据扫描用例 `test_no_hardcoded_credentials_in_shipped_text_files` 判红——**本机未触发、CI 首次触发** | 文档作者把「待验证的凭据样式串」原样写进交付文档；用例的 `.md` 扫描范围正确覆盖了 `docs/`，是**用例按设计工作**而非误报 | 改为描述性写法（不复述原文），全仓 `sk-[A-Za-z0-9]{16,}` / `Bearer …{20,}` 扫描 0 命中；该用例转绿。**教训：文档与测试同属受扫描面，验证样例不得落原文** |

### 6.9 CI 状态

| 项 | 状态 |
| --- | --- |
| 基线提交 `8fcf22b` | **success**（run `42351880718`） |
| 审计轮首次推送 `a174d31` | **failure**（run `42438075352`）——仅 `Pytest` 步骤红：仓库自带静态凭据扫描 `test_no_hardcoded_credentials_in_shipped_text_files` 命中**本文档 §6.6 复述的 `sk-` 样例原文**。属文档自伤，非产品缺陷；本机因扫描路径差异未触发，CI 首次触发（见 §6.8 QA-T22） |
| 修复提交 `1778137` | **success**（run `42438294549`）—— 五步全绿（Compile / Pytest 247 passed / Demo smoke / Evaluator / Contract smoke），runner `Python 3.11.18` |
| `make demo/test/run/eval` 四个目标 | **未验证** —— 本机无 `make`；已按 `Makefile` 注释中的逐字等价 `python3` 命令执行全部四条，结果见 §6.2 |

### 6.10 结论

五步验证全绿（本机 3.13.12 + CI 3.11.18 双版本各跑一遍）、负向验证可复现转红、契约零漂移（7 组端点 / 11 字段 / SSE 顺序 / `done` 恒末帧 / `/health` 键集）、零改动文件字节未变、依赖未新增。
唯一**未闭环**项是「`make` 四目标本身」（本机无 `make`，已用 `Makefile` 注释里的逐字等价命令全跑，但目标入口未被真实执行）。
