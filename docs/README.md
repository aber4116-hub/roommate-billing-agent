# 设计文档索引

- 阶段 0/1 状态：设计已完成。
- 阶段 2 状态：整数分摊引擎已完成，79 个测试通过。
- 阶段 3 状态：PostgreSQL/Alembic、账单/付款/结算/API 已完成，129 个测试通过，覆盖率 91%。
- 阶段 4 状态：登录/会话/CSRF/邀请/角色/审计已完成，140 个测试通过，覆盖率 89%。
- 阶段 5 状态：Agent/Provider/工具/确认已完成，157 个测试通过，覆盖率 88%。
- 阶段 6 状态：前端/旧 DOM 契约/CSP/Chrome E2E 已完成，160 个测试通过，覆盖率 88%。
- 阶段 7 状态：Docker/Compose/Caddy/CI/备份恢复交付物已创建；备份恢复和安全扫描已执行；Docker 运行时/CI 未执行。
- 项目根目录：`roommate-billing-agent/`
- 旧版文件：原路径未修改；只读副本 `legacy/合租账单分摊器.html`。
- 当前有 Docker/CI/备份恢复配置；Docker 运行时尚未验证。

## 阅读顺序

1. [阶段 0 审查报告](phase-0-audit.md)
2. [阶段 2 测试报告](phase-2-report.md)
3. [阶段 3 实现报告](phase-3-report.md)
4. [阶段 4 实现报告](phase-4-report.md)
5. [阶段 5 实现报告](phase-5-report.md)
6. [阶段 6 实现报告](phase-6-report.md)
7. [阶段 7 实现报告](phase-7-report.md)
8. [备份与恢复演练](backup-restore.md)
9. [安全扫描记录](security-review.md)
10. [架构与选型](architecture.md)
11. [数据库设计](database.md)
12. [REST API](api.md)
13. [Agent 设计](agent.md)
14. [安全设计](security.md)
15. [测试方案](testing.md)
16. [部署方案](deployment.md)
17. [GitHub 发布](github-release.md)
18. [开发路线图](roadmap.md)

## 阶段 0 证据

- [旧版审计脚本](audits/legacy-split-audit.mjs)
- [审计结果 JSON](audits/legacy-split-audit-results.json)
- 旧版 SHA-256：`E1CC8C58FFFCBD6CBFB62DEFBBEC6F229489C86825AA6599CF985482ABC963EC`

复现：

```bash
node docs/audits/legacy-split-audit.mjs
```

## 阶段 2 证据

- [阶段 2 测试报告](phase-2-report.md)
- 源码：`src/roommate_billing/domain/money.py`、`allocation.py`、`errors.py`
- 测试：`tests/unit/test_money.py`、`test_allocation.py`、`test_allocation_properties.py`
- 实测：79 passed；ruff check/format 通过。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
```

## 阶段 3 证据

- [阶段 3 实现报告](phase-3-report.md)
- PostgreSQL 16.15 + Alembic `82f2f551741e`
- 129 passed，coverage 91%
- 核心服务：`services/bills.py`、`rules.py`、`payments.py`、`settlements.py`
- 集成测试：`tests/integration/`

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest --cov=roommate_billing --cov-report=term-missing
```

## 阶段 4 证据

- [阶段 4 实现报告](phase-4-report.md)
- Alembic `bc8299ee45ed`（`auth_sessions`、`household_invites`）
- 140 passed，coverage 89%
- 认证服务：`services/auth.py`、`security/passwords.py`、`api/v1/auth.py`
- 测试：`tests/integration/test_auth.py`、`test_auth_sessions.py`

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest --cov=roommate_billing --cov-report=term-missing
```

## 阶段 5 证据

- [阶段 5 实现报告](phase-5-report.md)
- Alembic `f9d42243af3a`（`agent_conversations`、`agent_messages`、`pending_actions`）
- 157 passed，coverage 88%
- Agent：`agent/providers.py`、`agent/tools.py`、`agent/loop.py`
- 动作：`services/actions.py`
- 测试：`tests/integration/test_agent*.py`、`tests/unit/test_providers.py`

## 阶段 6 证据

- [阶段 6 实现报告](phase-6-report.md)
- 前端：`web/index.html`、`web/assets/app.css`、`web/assets/js/`
- 静态契约/CSP：`tests/integration/test_web.py`
- 浏览器 E2E：`scripts/e2e_frontend.mjs`、`scripts/seed_demo.py`
- 160 passed，coverage 88%
- 旧版 DOM 契约：12 cell / 4 bill-total / 3 person-total / `#balance-check`
- Chrome E2E：规则 v2、账单、实收、锁定、结算、CSV、审计、Agent 降级

## 阶段 7 证据

- [阶段 7 实现报告](phase-7-report.md)
- Dockerfile/Compose/Caddy/CI：根目录、`.github/`
- `docker compose config`：prod/dev 均通过（无 daemon）
- Caddy 2.11.7 `validate`：Valid configuration；本机内部 CA TLS/反代 200、HTTP 301
- hadolint 2.15.1：exit 0
- [备份恢复](backup-restore.md)：20 张表行数一致、`/health/ready` 200
- [安全扫描](security-review.md)：pip-audit 无已知第三方漏洞
- **未执行**：Docker build/up、公网 ACME TLS、GitHub Actions（本地内部 CA TLS 已通过）

## 设计摘要

- 单体 FastAPI + PostgreSQL 16 + SQLAlchemy 2.0（同步）+ Alembic。
- 原生 ES modules 前端，保留旧页面视觉与 `data-testid`。
- 金额只用整数分；每笔账单守恒；零头归规则版本指定人员。
- 付款只追加；正式结算不可变；规则版本化；审计只追加。
- Agent 只调用白名单工具；写工具只创建待确认动作；模型不能确认。
- 服务端会话 + HttpOnly Cookie + CSRF；账本隔离 + 复合外键。
- Docker Compose + Caddy HTTPS；每日 `pg_dump` + 恢复演练。
- MIT License 已创建；本地 release candidate，未配置 GitHub 远程。

## 未验证声明

当前验证了旧页面审计、阶段 2 领域层测试、阶段 3 PostgreSQL/服务/API 集成测试、阶段 4 真实 Cookie/CSRF 认证测试、阶段 5 FakeProvider/HTTP mock Agent 测试、阶段 6 静态契约/CSP/Chrome E2E、阶段 7 备份恢复/静态部署验证。真实模型生产调用、Docker build/up、Caddy TLS 实机、GitHub Actions 尚未执行；相关文档已明确标注。
