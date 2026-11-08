# 仓库元信息与占位符集中登记表

> **唯一登记处**（主理人裁决 + `docs/ARCHITECTURE-OPENSOURCE.md` v1.1 §5.1；替代 PRD-OPENSOURCE §4.1 的旧登记位置）。
> 全部含 URL／身份的交付文件只引用本表符号，禁止散落硬编码不同写法。
> 仓库地址未到位（无 `.git`／无 remote、同名仓库 404、工作区其它 24 个子仓库 origin 属别的项目禁止挪用）：
> 交付**占位符版**，**推送前必须 S2 一次性全量替换**。
> 架构师／工程师／QA 均不执行 git 操作、不推送（S1–S7 归主理人 #9）。

---

## 1. 统一占位符符号表（11 个符号 · 6 列）

| 占位符键 | 类别 | 用途 | 默认取值（用户可替换） | 出现文件（RP 点） | 替换后校验方式 |
| --- | --- | --- | --- | --- | --- |
| `__REPO_URL__` | 地址·待用户提供 | 完整仓库 URL | `<待用户提供；禁止臆造>` | RP-01～04、06、08、10、11 | 全仓 `grep -r "__REPO_URL__"` = 0；所有出现处 URL 完全一致；S6 阶段 `curl -I` 可访问 |
| `__OWNER__` | 地址·派生 | 仓库 owner | 由 `__REPO_URL__` 解析（**不得用账号名反推**） | RP-04、06（如需） | grep 0 残留；与 URL 中 owner 段一致 |
| `__REPO_NAME__` | 地址·派生 | 仓库名（`cd` 目录） | 由 `__REPO_URL__` 解析 | RP-02、08 | grep 0 残留；与 URL 末段一致 |
| `__CI_BADGE_URL__` | 地址·派生 | CI badge 图片 URL | `__REPO_URL__ + /actions/workflows/ci.yml/badge.svg` | RP-01 | grep 0 残留；与派生公式一致 |
| `__DEFAULT_BRANCH__` | 地址·派生 | `blob` 路径分支段 | `main` | RP-04、11 | grep 0 残留；与仓库实际默认分支一致 |
| `__AUTHOR_NAME__` | 身份·有默认值 | 作者／版权 holder | `Nephets1010`（gh 实测登录账号、目标仓库所有者） | RP-05、07、12 | 值与 gh 账号一致；不臆造真实姓名 |
| `__AUTHOR_EMAIL__` | 身份·有默认值 | 作者／联系邮箱 | `Nephets1010@users.noreply.github.com`（默认取值；**已被用户确认值替换，实际取值见 §6**） | RP-05、07、09、10 | 与 §6 实际取值一致、用户已知悉公开可见 |
| `__COPYRIGHT_YEAR__` | 身份·有默认值 | 版权年份 | `2026`（当前年份） | RP-12 | 值为当前年份 |
| `__COPYRIGHT_HOLDER__` | 身份·有默认值 | 版权持有人 | `Nephets1010` | RP-12 | 与 `__AUTHOR_NAME__` 一致 |
| `__SECURITY_CONTACT__` | 联系·有默认值 | 安全／行为准则举报渠道 | `Nephets1010@users.noreply.github.com`（默认取值；**已被用户确认值替换，实际取值见 §6**） | RP-09、10 | 与 §6 实际取值一致、用户已知悉公开可见 |
| `__RELEASE_DATE__` | 元信息·待用户提供 | CHANGELOG／CITATION 发布日期 | `<待用户提供；不得臆造月日>` | RP-11、CHANGELOG、CITATION | grep 0 残留；格式 `YYYY-MM-DD` |

**两条区分铁律**（v1.1 §5.1）：

1. **身份类有可核实默认值，地址类没有**：`Nephets1010` 是 gh 实测登录账号且为目标仓库所有者，可用于作者／版权；但仓库名未确认、同名仓库 404，**禁止**用该账号拼装仓库 URL。
2. **禁止挪用**工作区其它 24 个子仓库的 origin；地址来源唯一 = 用户提供的 URL。

> 交付文件中身份字段**仍写占位符符号**（全占位符版交付），默认值只在本表登记并标注「默认取值，用户可替换」，S2 时按本表一次性替换。

---

## 2. 12 个 RP 点逐点映射

| RP | 位置 | 引用符号 | 类别 |
| --- | --- | --- | --- |
| **RP-01** | `README.md` §8.1 徽章（CI badge img/href、License） | `__CI_BADGE_URL__`、`__REPO_URL__` | URL |
| **RP-02** | `README.md` §8.2 克隆 | `__REPO_URL__`／`__REPO_NAME__` | URL |
| **RP-03** | `README.md` §8.4–8.7 Issues／PR／Homepage | `__REPO_URL__` 派生 | URL |
| **RP-04** | `pyproject.toml [project.urls]` 5 子键 | `__REPO_URL__` + `__DEFAULT_BRANCH__` + `__OWNER__` | URL |
| **RP-05** | `pyproject.toml authors`／`maintainers` | `__AUTHOR_NAME__`／`__AUTHOR_EMAIL__` | 身份 |
| **RP-06** | `CITATION.cff url`／`repository-code` | `__REPO_URL__`／`__OWNER__` | URL |
| **RP-07** | `CITATION.cff authors` | `__AUTHOR_NAME__`／`__AUTHOR_EMAIL__` | 身份 |
| **RP-08** | `CONTRIBUTING.md` 克隆／Issue／PR／CI 链接 | `__REPO_URL__`／`__REPO_NAME__` | URL |
| **RP-09** | `CODE_OF_CONDUCT.md` 举报渠道 | `__SECURITY_CONTACT__` | 联系 |
| **RP-10** | `SECURITY.md` 报告渠道／公告 | `__REPO_URL__` 或 `__SECURITY_CONTACT__` | URL／联系 |
| **RP-11** | `CHANGELOG.md` 底部版本比较链接 | `__REPO_URL__` + `__DEFAULT_BRANCH__` + `__RELEASE_DATE__` | URL／元信息 |
| **RP-12** | `NOTICE` 版权行 | `__COPYRIGHT_YEAR__`／`__COPYRIGHT_HOLDER__` | 身份 |

**统计**：12 个依赖点 = **9 个需真实仓库 URL／联系渠道**（RP-01～04、06、08～11，其中 RP-11 含日期）+ **3 个需作者与版权身份**（RP-05、07、12）。所有符号集中在 `docs/REPO_METADATA.md`。

**引用点边界说明（供 QA 核对）**：

- 上表 12 个 RP 点是**唯一的实际引用点**，分布在 9 个开源／元信息文件与 `README.md` §8。
- 本登记表自身，以及 `docs/PRD-OPENSOURCE.md`／`docs/ARCHITECTURE-OPENSOURCE.md`／`docs/TASKS-OPENSOURCE.md` 中出现的符号名属**说明性文字／索引**，不是引用点，S2 不计入替换目标。
- 地址未到位时全仓允许 `__...__` 残留，但不得推送；S2 后**交付文件**必须为 0 残留。

---

## 3. 唯一派生规则与替换顺序

```
__CI_BADGE_URL__  := __REPO_URL__ + "/actions/workflows/ci.yml/badge.svg"
__DEFAULT_BRANCH__ := main（可替换，须与仓库实际默认分支一致）
__OWNER__ / __REPO_NAME__ := 由用户提供的 URL 解析，不得反推
```

| 用途 | 派生表达式 |
| --- | --- |
| Issues | `__REPO_URL__/issues` |
| Pull Requests | `__REPO_URL__/pulls` |
| Changelog | `__REPO_URL__/blob/__DEFAULT_BRANCH__/CHANGELOG.md` |
| Documentation | `__REPO_URL__/blob/__DEFAULT_BRANCH__/README.md` |
| Security Advisories | `__REPO_URL__/security/advisories/new` |
| Release tag | `__REPO_URL__/releases/tag/v1.0.0` |
| Version compare | `__REPO_URL__/compare/v1.0.0...__DEFAULT_BRANCH__` |

**S2 替换顺序**（避免「符号里套符号」残留）：先展开派生符号
`__DEFAULT_BRANCH__` / `__CI_BADGE_URL__` / `__OWNER__` / `__REPO_NAME__`
→ 再替换 `__REPO_URL__` → 最后身份／日期符号 → `grep` 确认交付文件 0 残留。

> **分支校验说明**：分支段须与 §6 实际取值 `main` 一致；`blob/main` 是合法最终值，
> 仅当用户指定其他分支时才检查旧分支残留。当前仓库默认分支为 `main`（见 §6），
> 故 issues／PR／compare 链接中的 `blob/main` 无需替换。

---

## 4. 冻结门与 S1–S7 交接

1. **当前状态（地址未到位）**：交付占位符版，全仓允许 `__...__` 残留，**不得推送**。
2. **S1**：用户提供真实 URL 或授权使用已有仓库（Q-OS2 明确**不新建仓库**），主理人确认 owner／repo／可见性。
3. **S2**：按 §1／§2 一次性全量替换 12 个 RP 点。替换后执行下方命令（**排除 `docs/` 下设计文档的说明性文字，只查实际产物**；本登记表自身作为历史索引不列入），期望 **0 残留**；并核对 12 处 URL 完全一致、无臆造 owner/repo、无散落硬编码、无旧分支写法：

   ```bash
   grep -rnE '__[A-Z_]+__' --exclude-dir=data --exclude-dir=__pycache__ \
     --exclude-dir=.pytest_cache --exclude='REPO_METADATA.md' \
     README.md pyproject.toml CITATION.cff CONTRIBUTING.md CODE_OF_CONDUCT.md \
     SECURITY.md CHANGELOG.md NOTICE LICENSE .github/workflows/ci.yml
   # S2 后期望：无输出（0 残留）；分支段须与 §6 实际取值 main 一致，blob/main 是合法最终值，
   # 仅当用户指定其他分支时才检查旧分支残留
   ```
4. **S3**：本地最终验证（PRD-OPENSOURCE §3 十条判据 + ARCH-OPENSOURCE v1.1 §7 A–F）。
5. **S4**：`git init` → remote（**只用用户地址**）→ 本地首次提交【**停在推送前**】；提交信息不含密钥。
6. **S5**：用户授权后推送 → **S6** 设 public + description／homepage／topics／license → **S7** 反馈推送结果／仓库可见性／开源配置状态。
7. 若 S4 提交时地址仍未到位，提交必然含占位符；**推送前必须完成 S2 并追加一次提交**，严禁把占位符或臆造 URL 推入公开仓库。

---

## 5. 与实现的一致性说明

- 9 个开源文件与 `.github/workflows/ci.yml` 的许可表述一律 **Apache-2.0**；`LICENSE` 为完整原文（11358 字节，条款零改写）。
- 版本号 `1.0.0` 五处一致：`app/__init__.py::__version__`、`pyproject.toml`、`CITATION.cff`、`CHANGELOG.md`、`SECURITY.md`；`/health.version` 运行期读取 `__version__`，**开源徽章／版本／许可／repo 信息一律不得写入 `/health`**。
- `pyproject.toml` 无 `[build-system]`，`requirements.txt` 仍是唯一依赖来源；`[tool.pytest.ini_options]` 仅 `testpaths = ["tests"]`。
- 占位符替换**不得**触碰零改动清单：`web/index.html`、`requirements.txt`、`samples/knowledge.txt`、`docs/reference/*`（含 `platform-spec-README.md:648`）、`Makefile` 四目标命令、`config/settings.yaml`。

> **文档状态**：S2 已执行完毕（见 §6），交付文件中的占位符均已替换为真实值；本表 §1 符号定义作为历史索引保留。


---

## 6. S2 执行记录（主理人执行）

用户提供账号主页 `https://github.com/Nephets1010` 并授权主理人定义仓库名；目标分支要求与本地一致。
经实测该账号下无同名仓库（GitHub API 404），故新建公开仓库。

| 符号 | 实际取值 | 依据 |
| --- | --- | --- |
| `__REPO_URL__` | `https://github.com/Nephets1010/multimodal-agent-platform` | 用户账号 + 主理人定义仓库名（与本地目录、pyproject 的 name 一致） |
| `__OWNER__` | `Nephets1010` | 由用户提供账号解析 |
| `__REPO_NAME__` | `multimodal-agent-platform` | 由 URL 末段解析 |
| `__CI_BADGE_URL__` | `https://github.com/Nephets1010/multimodal-agent-platform/actions/workflows/ci.yml/badge.svg` | 由 `__REPO_URL__` 单向派生 |
| `__DEFAULT_BRANCH__` | `main` | 用户要求与本地一致，本地分支为 main |
| `__AUTHOR_NAME__` | `Nephets1010` | 用户确认的 git 全局身份 |
| `__AUTHOR_EMAIL__` | `stephen_rong@foxmail.com` | 用户确认的 git 全局身份邮箱（已知悉公开可见） |
| `__COPYRIGHT_YEAR__` | `2026` | 当前年份 |
| `__COPYRIGHT_HOLDER__` | `Nephets1010` | 与作者名一致 |
| `__SECURITY_CONTACT__` | `stephen_rong@foxmail.com` | 真实可收信的私密举报渠道；另有 GitHub Security Advisories 入口 |
| `__RELEASE_DATE__` | `2026-11-07` | 由 date 命令实取，不臆造 |

**替换范围**：8 个实际产物（README.md / pyproject.toml / CITATION.cff / CONTRIBUTING.md /
CODE_OF_CONDUCT.md / SECURITY.md / CHANGELOG.md / NOTICE）；LICENSE 与 ci.yml 本就不含符号。
本登记表与 docs 下三份 OPENSOURCE 设计文档中的符号属定义与说明性文字，按 S2 检查口径排除。

**同步修正**：把「发布前替换 / 占位符版 / 替换完成前不得推送」等与最终状态矛盾的句子改写为真实状态
（README §8.1/§8.4/§8.7、pyproject 注释、SECURITY §2、CODE_OF_CONDUCT §3、
CONTRIBUTING 社区链接、CHANGELOG Unreleased），并在 README 首屏补 CI／License／Python 徽章。

**校验**：S2 残留检查命令（§4 第 3 条）实跑 0 残留；12 处 URL 完全一致；无旧分支写法；
TOML／CFF 可解析；五步验证全绿。
