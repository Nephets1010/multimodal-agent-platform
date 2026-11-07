# 安全策略

## 1. 支持版本

| 版本 | 状态 |
| --- | --- |
| `1.0.0` | ✅ 支持（当前版本） |
| `< 1.0.0` | ❌ 不支持 |

版本值静态镜像 `app/__init__.py::__version__ = "1.0.0"`，与 `pyproject.toml`／`CITATION.cff`／
`CHANGELOG.md` 保持一致。

## 2. 报告渠道

**请不要用公开 GitHub Issue 报告安全问题。** 请通过以下私密渠道之一提交：

- `__SECURITY_CONTACT__`（邮箱或私密报告入口；真实值见 `docs/REPO_METADATA.md`，发布前替换）
- 由 `__REPO_URL__` 派生的 GitHub Security Advisories 私密报告入口：`__REPO_URL__/security/advisories/new`

**响应预期**：维护者会在收到报告后尽快确认收悉，并给出初步判断与后续修复／缓解计划。
本项目为教学／作品集用途，不承诺固定 SLA，也不会因为报告未被立即处理而将其视为已接受风险。

## 3. 敏感信息不入 Issue／PR

以下信息**一律不得**出现在公开 Issue、Pull Request、日志、`data/traces.jsonl` 或任何 HTTP 响应中：

- `LLM_API_KEY`／`LLM_BASE_URL` 中的凭据、Authorization 头、Bearer Token、`token=`／`password=` 值；
- 上传文件正文、完整 prompt 原文、轨迹状态快照中的敏感原文；
- 任何可复用的私有端点地址或账号凭据。

平台侧已在三个出口强制脱敏（日志 Formatter、轨迹落盘前、HTTP 异常响应构造）；
异常响应只返回 `{"detail": "可读中文"}`，堆栈只进结构化日志且不直出 HTTP。

## 4. 已知设计边界（不是漏洞）

> **未实现鉴权、多租户、会话持久化与并发写入锁，属已知设计边界而非漏洞；
> 仅限本机或可信内网单机演示，勿暴露公网。** `/v1/chat` 的流式请求与入库请求共享进程内
> 索引，无并发写入保护（Q15 单机假设）；所有端点对外开放，也没有输入配额。

因此以下报告**不属于安全漏洞**，请勿重复提交：缺少登录／鉴权、没有多租户隔离、
会话不持久化、并发写入无锁、DEMO 模板答案的语义质量不及真实多模态大模型、
`samples/eval.jsonl` 自建 8 条基准不代表业务准确率。这些限制已在 `README.md` §6、
`docs/PRD.md` §4.7、启动日志与本文件中如实披露，本期不偷偷补齐。

## 5. 部署边界与 `0.0.0.0` 暴露风险

Makefile `run` 目标与规格 §2 保持 `--host 0.0.0.0 --port 8000`，会监听所有网卡；
**把默认监听地址直接暴露到公网是危险的**。若只在本机使用，请收紧监听：

```bash
HOST=127.0.0.1 PORT=8000 DEMO_MODE=1 python3 -m app.main
```

长格式覆盖请用 `MAP_SERVER__HOST` / `MAP_SERVER__PORT`；不带 `MAP_` 前缀的
`SERVER__HOST` / `SERVER__PORT` 等宿主同名变量不会被本平台读取。

## 6. 零依赖红线与依赖边界

`DEMO_MODE=1` 下不读取／不发起任何外部 API 请求，不加载 `torch`／`transformers` 权重、
不调用 CUDA、不联网下载权重；三后端无条件锁定 `template`／`stub`／`memory`。
可选依赖只用 `importlib.util.find_spec` 探测 + 局部 `try/except ImportError` 降级。
报告依赖相关问题时，请注明是否处于生产模式（`DEMO_MODE=0`）以及实际安装的包版本。

## 7. 相关文件

- 许可与免责：`LICENSE`（Apache-2.0）、`NOTICE`
- 已知限制汇总：`README.md` §6；行为契约：`docs/PRD.md` §4
- 占位符登记：`docs/REPO_METADATA.md`

本文件中的 URL 与联系渠道为占位符，属地址未到位期间的冻结状态；S2 全量替换前不得推送。
