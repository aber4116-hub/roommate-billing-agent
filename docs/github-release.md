# GitHub 仓库初始化、开源与发布流程

- 目标：把项目整理成可公开审查、可复现测试、可安全部署的 GitHub 仓库。
- 当前状态：MIT License 已创建；本地 Git 仓库已初始化并提交 `v0.1.0-rc.1`；**尚未创建 GitHub 远程仓库、未推送**。
- 本文是阶段 8 的操作清单与本地交付记录。

---

## 0. 本地交付记录（2026-10-23）

- 本地 Git：`main`，tag `v0.1.0-rc.1`；
- tracked files：完整源码（具体数量由 `git ls-files` 为准）；
- `.env` 未入库；`.venv`/`_runtime`/覆盖率/缓存均忽略；
- 从 bundle 克隆验证：tag 正确、文件完整、`LICENSE`/`web` 存在、无 `.env`；
- GitHub Actions workflow 通过 actionlint 1.7.12 静态检查；
- 未在 GitHub runner 实际运行。
- 未配置 GitHub remote、未 push。

运行时产物（不提交仓库）：

```text
_runtime/roommate-billing-agent-v0.1.0-rc.1.bundle
_runtime/roommate-billing-agent-v0.1.0-rc.1.zip
_runtime/SHA256SUMS
```

具体哈希以 `_runtime/SHA256SUMS` 为准。

推送前必须：

1. 决定 Private/Public；
2. 公开前处理 `legacy/合租账单分摊器.html`（MIT 不覆盖，见 `NOTICE`）；
3. 决定是否等在 Docker/CI 运行时验收后再发布。

---

## 1. 许可证：MIT（已采用）

项目所有者已授权选择 **MIT**；`LICENSE` 已创建，README 已同步。下面是当时的影响说明，保留作决策记录。

| 许可证 | 类型 | 主要影响 | 适用场景 |
|---|---|---|---|
| **MIT** | 宽松 | 允许商用、修改、再分发；需保留版权/许可声明；**无明确专利授权**；不要求公开修改 | 个人项目、希望尽量多人使用/参考，最简单 |
| **Apache-2.0** | 宽松 | 允许商用/修改/再分发；含明确专利授权和专利报复条款；需保留 NOTICE/变更说明；比 MIT 更正式 | 希望有专利保护、面向企业采用 |
| **AGPL-3.0** | 网络 copyleft | 允许修改/分发，但通过网络提供服务时也需向用户提供对应源码；商用闭源集成受限 | 希望托管服务商的修改也回馈社区 |
| **GPL-3.0** | copyleft | 分发衍生作品需开源；网络使用不一定触发（与 AGPL 不同） | 桌面/分发型 copyleft |
| **无许可证** | 保留所有权利 | 默认不是开源；他人不能合法复制/修改/分发 | 不想开放复用，不建议作为“开源项目” |

### 1.1 推荐

- 如果希望项目容易被个人/小团队使用、修改、部署：**推荐 MIT**。
- 如果担心专利风险或希望更正式的企业友好条款：**推荐 Apache-2.0**。
- 如果希望任何提供在线服务的修改都必须开源：**AGPL-3.0**。
- 本项目保存真实收款、可能被托管为服务；若采用 AGPL，需要接受“网络服务也要提供源码”的义务。

**已创建 MIT `LICENSE`；README 与 `pyproject` 均声明 MIT。**

---

## 2. 仓库初始化流程

### 2.1 本地初始化

```bash
cd roommate-billing-agent

git init
git branch -M main

git add .
git status
git commit -m "chore: initial design and legacy audit"
```

- 首次提交前检查：
  - 没有 `.env`；
  - 没有真实账单/姓名/收款账号；
  - 没有 API Key/数据库密码；
  - `legacy/` 中的 HTML 只含示例数据；
  - `docs/audits/legacy-split-audit-results.json` 不含真实个人信息。
- 如需保留旧页面历史，`legacy/合租账单分摊器.html` 可保留；建议加 `legacy/README.md` 说明来源、用途、许可证归属。

### 2.2 创建远程仓库

```bash
# 在 GitHub 创建空仓库（不要勾选自动生成 README/LICENSE）
git remote add origin git@github.com:<owner>/roommate-billing-agent.git
git push -u origin main
```

- 建议先 **Private**，完成 secrets 扫描和真实数据检查后再 Public。
- 仓库名：`roommate-billing-agent`。
- 描述：`合租账单分摊与结算 Agent：确定性整数分摊、规则版本、实收流水、审计与自然语言操作。`
- Topics：`fastapi`, `postgresql`, `billing`, `roommate`, `agent`, `llm`, `docker`。

### 2.3 分支保护

在 GitHub Settings → Branches：

- 保护 `main`：
  - 禁止直接 push（管理员也建议）；
  - 要求 PR；
  - 要求 CI 通过；
  - 要求至少 1 个 review（个人项目可对自己豁免，但 CI 必须）；
  - 禁止 force push/删除。
- 开发分支：`feat/...`、`fix/...`。
- 每个 PR 关联阶段任务/issue。

### 2.4 Secrets

- 仓库 Secrets **不保存**生产数据库密码/真实用户数据。
- CI 用临时 Postgres service，密码是测试值。
- 生产部署密钥放在服务器/部署平台，不放 GitHub Actions（除非使用 Environment + 保护规则）。
- 如发布 GHCR 镜像，使用 `GITHUB_TOKEN` + `packages: write`，限制在 release workflow。

---

## 3. 必须提交的文件

```text
README.md
LICENSE                  # 确认后
CONTRIBUTING.md
SECURITY.md
CHANGELOG.md
.gitignore
.editorconfig
.env.example
.dockerignore
pyproject.toml
uv.lock
Dockerfile
docker-compose.yml
docker-compose.prod.yml
Caddyfile
alembic.ini
migrations/
src/
tests/
docs/
scripts/
.github/
runbooks/
```

### 3.1 `.gitignore` 必须包含

```gitignore
# secrets
.env
.env.*
!.env.example
*.pem
*.key

# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage
coverage.xml

# Node/Playwright
node_modules/
playwright-report/
test-results/

# data/backups
*.dump
*.sql
*.db
*.sqlite3
backups/
data/

# OS/IDE
.DS_Store
Thumbs.db
.idea/
.vscode/

# build
dist/
build/
```

注意：`*.sql` 可能误伤迁移中的 SQL 文件；如需要，改为忽略 `backups/*.sql`。迁移使用 Python 文件，不受影响。

### 3.2 `.env.example` 只放占位符

- 数据库 URL 用 `replace-me`；
- `APP_SECRET_KEY=replace-with-random-32-bytes`；
- `LLM_API_KEY=replace-me`；
- 不写真实域名/邮箱/密码。

### 3.3 `.dockerignore`

- `.git`
- `.env`
- `tests`
- `docs`
- `backups`
- `*.dump`
- `node_modules`
- `__pycache__`

---

## 4. README 结构（阶段 8 完成）

必须包含并实际验证：

1. 项目简介和主要功能；
2. 系统架构图（Mermaid）；
3. 技术栈；
4. 本地开发环境要求；
5. 环境变量配置说明；
6. 本地启动步骤；
7. Docker 启动步骤；
8. 数据库迁移步骤；
9. 测试运行步骤；
10. Agent 配置方法；
11. 部署步骤（HTTPS/Caddy）；
12. 数据备份与恢复方法；
13. 已知限制；
14. 贡献指南；
15. 许可证说明。

写作要求：

- 不写未验证的命令/测试结果。
- 命令在干净环境执行后再写入。
- 说明“旧页面自动基线不是真实收款”。
- 说明 Agent 关闭时核心账务仍可用。
- 说明金额单位为分、零头归属规则。
- 提供截图（可选）但不要含真实数据。
- 安全提示：不要公网裸奔、先改默认密码、备份。

---

## 5. GitHub Actions

### 5.1 CI（`.github/workflows/ci.yml`）

触发：

- `push` 到 `main`；
- 所有 PR；
- 手动 `workflow_dispatch`。

任务：

1. Checkout；
2. setup Python 3.12；
3. install uv；
4. `uv sync --frozen --extra dev`；
5. 启动 Postgres 16 service；
6. `alembic upgrade head`；
7. `ruff check .` + `ruff format --check .`；
8. `pytest`（单元/集成/Agent）；
9. `pip-audit`；
10. gitleaks（或 GitHub secret scanning）。

权限：

```yaml
permissions:
  contents: read
```

- 固定 action 版本。
- 缓存 uv/pip 时不要把 `.env` 带入缓存。
- 测试失败阻断合并。
- 不打印环境变量。

### 5.2 Release（`.github/workflows/release.yml`）

- 触发 tag `v*`。
- 构建/测试；
- 可选构建并推送 GHCR 镜像；
- 生成 release notes；
- 不自动部署生产（手动 runbook）。

### 5.3 Dependabot

`.github/dependabot.yml`：

- pip（weekly）；
- github-actions（weekly）；
- docker（weekly）。

- 自动 PR 必须通过 CI。
- 安全更新优先。

### 5.4 其他

- PR 模板：变更说明、测试命令、迁移/配置影响、安全影响。
- Issue 模板：bug/feature/security（security 不公开细节，指向 SECURITY.md）。
- `CODEOWNERS`（可选）。
- Branch protection required checks：`test`、`lint`。

---

## 6. 首次公开发布检查

### 6.1 安全

- [ ] 全仓库 secret 扫描通过；
- [ ] `.env`/数据库密码/API Key/真实账单/真实姓名/访问令牌不在 Git；
- [ ] 示例数据是虚构的；
- [x] 备份文件不在仓库；
- [ ] `legacy/` 内容可公开（MIT 不覆盖；公开前需移除或取得许可）；
- [x] 依赖审计无未处理高危（pip-audit 当前无已知第三方漏洞）；
- [x] README 有安全部署说明；
- [x] `SECURITY.md` 提供私下报告方式（不要公开漏洞细节）。

### 6.2 可复现

- [ ] 干净环境按 README 启动（本地非 Docker 已跑；Docker 未跑）；
- [x] 空库迁移成功；
- [x] 测试命令实际通过；
- [ ] Docker Compose 启动（未执行）；
- [x] 备份/恢复演练；
- [ ] CI 绿（workflow 已写，未运行）。

### 6.3 文档

- [x] README 15 项齐全；
- [x] LICENSE 已确认；
- [x] CONTRIBUTING；
- [x] SECURITY；
- [x] CHANGELOG；
- [x] 架构/数据库/API/Agent/安全/测试/部署文档；
- [x] 已知限制；
- [x] 版本号/Release notes。

### 6.4 许可证

- [x] 用户明确选择 MIT；
- [x] `LICENSE` 内容正确；
- [x] README 许可证段落与之一致；
- [ ] 第三方依赖许可证逐项审计（当前只依赖常见 MIT/BSD/Apache 包）；
- [ ] `legacy/` 文件的权利归属已确认（MIT 不覆盖；公开前需移除或取得许可）。

---

## 7. 版本与发布

- 版本：SemVer `MAJOR.MINOR.PATCH`。
- 初始版本建议 `0.1.0`（设计/可用 MVP），稳定后 `1.0.0`。
- Tag：`v0.1.0`。
- Release notes：
  - 新增功能；
  - 数据库迁移；
  - 配置变化；
  - 破坏性变更；
  - 已知问题；
  - 升级步骤。
- `CHANGELOG.md` 使用 Keep a Changelog 风格。
- Docker 镜像 tag：
  - `ghcr.io/<owner>/roommate-billing-agent:v0.1.0`
  - `:latest` 可选，不用于生产固定部署。

---

## 8. 贡献指南要点

- 先开 issue 讨论较大改动。
- PR 小而聚焦；一个 PR 一个主题。
- 必须：
  - 新增/修改测试；
  - 更新文档；
  - 通过 ruff/pytest；
  - 不提交 secrets/真实数据。
- 代码风格：
  - Python 3.12；
  - 类型标注；
  - 业务逻辑中文注释（关键规则）；
  - 金额只用整数分。
- 数据库变更：
  - 必须 Alembic 迁移；
  - 说明升级/回滚；
  - 不手改生产 schema。
- Agent 变更：
  - 新增工具需权限/确认/测试；
  - 不得让模型直接写库。
- 安全问题：
  - 不公开 issue；按 SECURITY.md 私下报告。
- 许可证：
  - 贡献即同意按项目许可证发布（需在 CONTRIBUTING 中写清）。

---

## 9. 安全政策（SECURITY.md）

- 支持版本；
- 私下报告渠道（邮箱/私密 issue）；
- 响应时间目标；
- 不公开利用细节；
- 范围：
  - 认证/会话；
  - 越权/隔离；
  - 金额/结算；
  - Agent 工具越权；
  - 依赖漏洞；
  - 部署配置。
- 不在仓库放真实密钥。

---

## 10. 发布后的维护

- 每月：
  - 依赖更新；
  - 备份恢复抽查；
  - 证书/磁盘检查。
- 每季度：
  - 完整恢复演练；
  - 权限/审计复查；
  - 安全测试回归。
- 每半年：
  - 依赖大版本评估；
  - 数据保留策略复核。
- Issue 分类：
  - bug；
  - security（私下）；
  - enhancement；
  - docs；
  - question。
- 不承诺无法维持的 SLA。

---

## 11. 当前阶段与下一步

- 当前：阶段 0–6 完成；阶段 7 的 Docker/Compose/Caddy/CI/备份恢复交付物已创建，备份恢复/静态验证完成，Docker/CI 运行时未执行；尚未 `git init`，未创建远程仓库，未选择许可证。
- 阶段 3 起继续实现数据库/API，阶段 8 才执行：
  - 创建 LICENSE；
  - 完成 README；
  - 初始化 Git/远程；
  - 推送；
  - 发布 v0.1.0。
- 从阶段 2 起持续提交小步变更，不要等到最后一次性上传。

**需要用户确认**：

1. 选择哪个许可证；
2. 仓库 Public 还是 Private；
3. GitHub 用户名/仓库地址；
4. 是否发布 Docker 镜像到 GHCR；
5. 是否保留 `legacy/` 旧页面（已按推荐保留）。
