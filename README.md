# roommate-billing-agent

合租账单分摊与结算 Agent。

> Release candidate：`v0.1.0-rc.1`。本地验证通过；Docker/CI 运行时尚未验证；尚未 push 到 GitHub。

> 当前状态：阶段 0–6 已完成；阶段 7 的 Docker/Compose/Caddy/CI/备份恢复交付物已创建，备份恢复与本地 Caddy 内部 CA TLS 已真实演练，**Docker 运行时和 GitHub Actions 尚未执行**。不可按生产系统部署。
>
> 原文件 `合租账单分摊器.html` 未被修改；只读副本在 `legacy/`。

## 这个项目要解决什么

现有页面是一个单文件计算器：刷新即丢失、没有真实收款、没有用户和权限。目标系统要支持：

- 多人登录、多个合租账本隔离；
- 账单、入住天数、规则版本、实际收款、正式结算；
- 每笔账单按整数分守恒，零头明确归属；
- 规则变更先预览、再由有权限的用户确认；
- 历史实收不被规则变化覆盖，结算保存当时的规则和金额快照；
- 自然语言 Agent，但金额只由确定性后端计算；
- 审计、导出、Docker 部署、备份恢复和 GitHub Actions。

## 设计文档

| 文档 | 内容 |
|---|---|
| [阶段 0 审查报告](docs/phase-0-audit.md) | 旧页面功能/DOM/算法/缺陷/迁移差异 |
| [阶段 2 测试报告](docs/phase-2-report.md) | 整数分摊引擎、79 个测试、已知限制 |
| [阶段 3 实现报告](docs/phase-3-report.md) | PostgreSQL 16、Alembic、账单/付款/结算/API、129 个测试 |
| [阶段 4 实现报告](docs/phase-4-report.md) | 登录、会话、CSRF、邀请、角色、审计、140 个测试 |
| [阶段 5 实现报告](docs/phase-5-report.md) | Agent、Provider、工具白名单、待确认动作、157 个测试 |
| [阶段 6 实现报告](docs/phase-6-report.md) | 前端、旧 DOM 契约、CSP、Chrome E2E、160 个测试 |
| [阶段 7 实现报告](docs/phase-7-report.md) | Docker/Compose/Caddy/CI、备份恢复、安全扫描；运行时未验证 |
| [备份与恢复演练](docs/backup-restore.md) | pg_dump/pg_restore、逐表比对、恢复库健康检查 |
| [安全扫描记录](docs/security-review.md) | pip-audit、hadolint、Caddy/Compose 验证、未验证项 |
| [阶段 8 实现报告](docs/phase-8-report.md) | MIT、社区文档、本地 Git/bundle/zip、未推送 |
| [架构与选型](docs/architecture.md) | 技术评估、架构图、目录结构、ADR |
| [数据库设计](docs/database.md) | ER、字段、约束、索引、事务、备份、隔离 |
| [REST API](docs/api.md) | 端点、权限、错误码、幂等、并发、示例 |
| [Agent 设计](docs/agent.md) | 工具契约、确认流程、模型适配、防注入 |
| [安全设计](docs/security.md) | 认证、CSRF、XSS、SQLi、密钥、审计、恢复 |
| [测试方案](docs/testing.md) | 测试矩阵、阶段 0 实测结果、部署/恢复测试 |
| [部署方案](docs/deployment.md) | Docker、Caddy、HTTPS、迁移、备份/恢复 |
| [GitHub 发布](docs/github-release.md) | 许可证建议、仓库初始化、CI、发布检查 |
| [开发路线图](docs/roadmap.md) | 阶段 2–8 任务与验收标准 |

## 已实际验证的内容

### 旧页面审计

```bash
node docs/audits/legacy-split-audit.mjs
```

- 14/14 审计探针通过；
- 旧版默认新规则分摊：12494 / 18402 / 18409 分；
- 旧版自动基线：11378 / 18964 / 18963 分；
- 原 HTML 与 `legacy/` 副本 SHA-256 一致。

结果见 [审计结果](docs/audits/legacy-split-audit-results.json)。

### 阶段 2 分摊引擎

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

- 79 个测试通过（Python 3.12.14 / pytest 9.1.1 / Hypothesis 6.170.5）；
- `ruff check` 通过；
- 固定样例：电费 66.38/110.63/110.64，水费 22.24/37.07/37.09，宽带 29.66/29.66/29.68，垃圾 6.66/6.66/6.68；
- 每笔账单守恒，个人合计 124.94/184.02/184.09，总账单 493.05。

### 阶段 3 数据库/API

- PostgreSQL 16.15 本地测试服务；Alembic 从空 schema 升级到 `82f2f551741e`；
- 15 张表、3 个只追加触发器、29 个 OpenAPI path；
- 账单、入住天数、规则草稿/预览/激活、付款、结算、修订、解释、CSV 导出；
- 幂等键 + 行锁 + partial unique + 结算重复保护；
- 129 个测试通过（含 5000 + 1000 组分摊属性样例），覆盖率 91%；
- 阶段 3 时尚无真实登录；阶段 4 已接入。

详细结果见 [阶段 3 报告](docs/phase-3-report.md)。

### 阶段 4 认证/权限

- Argon2id 密码、登录失败锁定、服务端会话、HttpOnly Cookie；
- CSRF double-submit + session-bound HMAC、轮换、改密吊销其他会话；
- 邀请、成员角色、`X-Household-ID` 多账本切换；
- 审计写入与管理员审计查询；
- 40 个 OpenAPI path；
- **140 个测试通过，覆盖率 89%**；原有账务/结算/并发测试继续通过。

详细结果见 [阶段 4 报告](docs/phase-4-report.md)。

### 阶段 5 Agent/确认

- 会话/消息持久化、按用户隔离；
- OpenAI-compatible Provider、FakeProvider、DisabledProvider；
- 白名单工具：读账本/账期/分摊预览/结算解释/导出；
- 写工具只生成 10 分钟有效的 pending action；
- 确认绑定 payload hash、权限复核、Idempotency-Key、只执行一次；
- 规则确认工具不暴露给模型；
- 46 个 OpenAPI path、20 张表；
- **157 个测试通过，覆盖率 88%**；模型禁用/失败时核心 API 仍可用。

详细结果见 [阶段 5 报告](docs/phase-5-report.md)。

### 阶段 6 前端/E2E

- 原生 ES modules + 外部 CSS，无构建步骤、无内联脚本/样式；
- 登录、账本/账期、账单、入住、规则、实收、结算/CSV、成员/邀请、审计、Agent；
- 保留旧版 `data-testid`、`data-bill`、`data-person`、`data-cents` 与 `#balance-check`；
- 严格 CSP + 安全头；
- 47 个 OpenAPI path；
- **160 个测试通过，覆盖率 88%**；
- 真实 Chrome E2E：12 个旧分摊单元格、493.05 初始总账、规则 v2、新增账单、实收、锁定、结算、CSV、审计、Agent 禁用降级；
- 390px 移动端无页面横向溢出。

详细结果见 [阶段 6 报告](docs/phase-6-report.md)，截图在运行时 `_runtime/`（不提交）。

### 阶段 7 部署/CI/备份（部分验证）

- Dockerfile、`.dockerignore`、生产/开发 Compose、Caddyfile、`.env.example`；
- GitHub Actions CI、Dependabot；
- 备份/恢复 shell + PowerShell 脚本；
- Compose config、Caddy validate、hadolint 均通过（无 daemon 静态验证）；
- 真实 `pg_dump` → `pg_restore` → 20 张表逐表比对 → 恢复库 `/health/ready` 200；
- Caddy 2.11.7 内部 CA TLS 反代：`https://localhost:8443` 的 `/health/ready`、`/`、`/api/v1/meta` 均 200，HTTP 301；
- `pip-audit` 未发现第三方依赖已知漏洞；
- **Docker build/up、公网 ACME TLS、GitHub Actions 实际运行未执行**：本机无 Docker daemon，Hyper-V/Containers 未启用。

详细结果见 [阶段 7 报告](docs/phase-7-report.md)、[备份恢复](docs/backup-restore.md)、[安全扫描](docs/security-review.md)。

**没有**声称已运行 Docker 或 CI，也没有声称已生产部署；没有使用真实模型 Key。

### 阶段 8 文档/发布

- MIT `LICENSE`；`legacy/` 除外（见 `NOTICE`）；
- `CONTRIBUTING.md`、`SECURITY.md`、`CHANGELOG.md`、`RELEASE_NOTES.md`；
- 本地 Git tag `v0.1.0-rc.1`；
- tracked files 以 `git ls-files` 为准；`.env`/`.venv`/运行时不在库；
- bundle/zip 已生成并做 clone 校验；
- **尚未配置 GitHub remote、未 push、未运行 Actions**。

## 本地运行

```powershell
# 1. 数据库迁移（需要 PostgreSQL）
.\.venv\Scripts\alembic.exe upgrade head

# 2. 创建账号（交互输入密码）
.\.venv\Scripts\python.exe -m roommate_billing.cli create-user --email demo@example.com --name 演示房东

# 3. 可选：演示数据（需要已创建账号；密码从环境变量读取）
$env:DEMO_PASSWORD="至少十二位密码"
.\.venv\Scripts\python.exe scripts/seed_demo.py

# 4. 启动
.\.venv\Scripts\python.exe -m uvicorn roommate_billing.main:app --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000/`。`.env` 中 `APP_BASE_URL` 必须与浏览器地址一致；本地默认关闭 `SESSION_COOKIE_SECURE`，生产必须开启。

## Docker 部署（交付物已创建，运行时未验证）

```bash
cp .env.example .env
# 修改 APP_BASE_URL/DOMAIN/ACME_EMAIL/APP_SECRET_KEY/数据库密码
chmod 600 .env
docker compose up -d --build
docker compose ps
curl -fsS https://<DOMAIN>/health/ready
```

- 只发布 Caddy 80/443，Postgres/API 不映射公网；
- 本机无 Docker daemon，`docker build/up` 未执行；
- 备份/恢复脚本与实测见 [backup-restore.md](docs/backup-restore.md)。

## 已确认的决策

- 历史实收：按“个人已为账期共同费用实际支付”的贡献语义；
- 已结算修正：重开账期 + 新结算修订，旧版标记 `superseded`；
- 普通账单拒绝负数；引擎支持有符号金额用于冲正/测试；
- 入住天数：整数 0–31；
- 规则确认工具不暴露给模型，必须用户点击确认；
- 旧版页面保留在 `legacy/`；
- 许可证：MIT；当前只做本地 Git 交付，仓库默认 Private，待运行时验收后再决定公开。

## 下一步

本地交付已完成；剩余：提供 GitHub 远程并 push、在 Docker 环境执行 build/up + 公网 ACME TLS + Actions；通过后再发布正式版。

## 许可证

[MIT](LICENSE)（新代码）。`legacy/合租账单分摊器.html` 是用户提供的参考资料，**不在 MIT 范围内**，公开仓库前需确认权利或移除；见 [NOTICE](NOTICE) 与 [legacy 说明](legacy/README.md)。当前没有 GitHub 远程仓库；本地 release candidate 与推送步骤见 [GitHub 发布文档](docs/github-release.md)。
