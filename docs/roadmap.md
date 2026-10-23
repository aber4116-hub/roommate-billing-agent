# 阶段 2–8：开发路线图与验收标准

- 当前进度：阶段 0–6 完成；阶段 7 备份/Caddy TLS/静态验证/Docker build/run（QEMU）完成，Compose/CI 未执行；Caddy HTTPS 已通过；阶段 8 本地 rc.1 完成，未 push。
- 规则：每次只推进一个阶段；上一阶段验收通过并经用户确认后，才进入下一阶段。
- 金额、历史、权限、审计的正确性优先于功能数量。
- 所有“已通过”必须有可复现命令与真实输出。

---

## 0. 阶段总览

| 阶段 | 目标 | 主要产物 | 门禁 |
|---|---|---|---|
| 0 | 审查旧版 | `docs/phase-0-audit.md`、审计脚本/结果、旧文件存档 | ✅ 已完成 |
| 1 | 架构/数据/API/Agent 设计 | `docs/architecture.md`、`database.md`、`api.md`、`agent.md`、安全/测试/部署/发布计划 | ✅ 已完成，用户已确认推荐方案 |
| 2 | 分摊引擎 + 单元测试 | `domain/money.py`、`domain/allocation.py`、单元/属性测试 | ✅ 79 tests passed；报告见 `docs/phase-2-report.md` |
| 3 | 数据库/账单/付款/结算 | 模型、Alembic、服务、核心 API、集成测试 | ✅ 129 tests passed；coverage 91%；报告见 `docs/phase-3-report.md` |
| 4 | 登录/成员/权限/审计 | 会话、CSRF、邀请、RBAC、审计、隔离测试 | ✅ 140 tests passed；coverage 89%；报告见 `docs/phase-4-report.md` |
| 5 | Agent/模型适配/确认 | provider、工具网关、pending actions、FakeProvider 测试 | ✅ 157 tests passed；coverage 88%；报告见 `docs/phase-5-report.md` |
| 6 | 前端改造 | 登录、账期、账单、规则、结算、聊天、确认、导出 | ✅ 160 tests passed；coverage 88%；Chrome E2E 通过；报告见 `docs/phase-6-report.md` |
| 7 | 测试/部署/CI/恢复 | Docker、Compose、Caddy、CI、备份恢复、安全检查 | ⚠️ Docker build/run/备份/Caddy TLS 完成；Compose/CI 未执行 |
| 8 | README/许可证/发布 | README、LICENSE、CONTRIBUTING、SECURITY、Release | ⚠️ MIT/本地 rc.1/bundle 完成；未 push/GitHub Release |

---

## 1. 阶段 2：确定性分摊引擎（TDD）

### 1.1 目标

先实现一个**不依赖数据库、不依赖 Web、不依赖模型**的纯 Python 分摊引擎，并用测试锁死业务规则。后续所有账单、预览、结算、Agent 解释都调用它。

### 1.2 任务清单

1. 确认 Python 3.12 工具链（已完成：Python 3.12.14；Docker 仍不可用）。
2. 创建最小项目骨架：
   - `pyproject.toml`；
   - `src/roommate_billing/__init__.py`；
   - `src/roommate_billing/domain/`；
   - `tests/unit/`。
3. 实现 `money.py`：
   - 严格的十进制字符串 → 整数分；
   - 拒绝超过 2 位小数、负数（普通账单）、指数、NaN、空值；
   - 单笔上限；
   - 格式化整数分为人民币显示。
4. 实现 `allocation.py`：
   - 输入：`total_cents: int`、`weights: list[int]`、`remainder_owner_index: int`、`fallback: Literal["equal"]`；
   - 整数除法/余数，不用浮点；
   - 每人 `base_cents`、`remainder_cents`、`amount_cents`；
   - 全部零头给 owner；
   - 权重全 0 → 显式均分 fallback；
   - 空人员/非法权重 → 明确错误；
   - 负金额（引擎级）支持符号；
   - 每笔守恒断言。
5. 先写测试（或测试与实现同步），覆盖 `docs/testing.md` 的 AL-01..20。
6. 加 Hypothesis 属性测试（5000 + 1000 组）。
7. 提供一个只读 CLI/脚本，输出固定样例，便于人工核对（可选；当前通过报告命令完成）。
8. 记录中文注释：金额分、余数分配、零头归属、fallback。

### 1.3 文件清单

```text
pyproject.toml
uv.lock
src/roommate_billing/__init__.py
src/roommate_billing/domain/__init__.py
src/roommate_billing/domain/money.py
src/roommate_billing/domain/allocation.py
src/roommate_billing/domain/errors.py
tests/unit/test_money.py
tests/unit/test_allocation.py
tests/unit/test_allocation_properties.py
```

### 1.4 如何运行/测试

```powershell
.\.venv\Scripts\uv.exe sync --frozen --extra dev
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

### 1.5 验收标准

- [x] 所有 AL 用例通过；
- [x] 5,000+ 组属性测试通过（5000 正数 + 1000 有符号）；
- [x] `287.65 / 18,30,30 → 6638,11063,11064`；
- [x] `89.00 / 1,1,1 → 2966,2966,2968`；
- [x] 总额 0、权重全 0、非法权重、负金额、单人、空人员行为明确；
- [x] 无 `float` 参与金额计算；
- [x] 每笔分摊守恒；
- [x] 同一输入重复结果一致；
- [x] 代码通过 ruff；
- [x] 测试输出真实记录在阶段报告中。

### 1.6 已知风险

- 旧版 `spread` 模式只用于迁移对照，不要误用为新规则。
- 零头归属人变更时，历史版本必须保留；阶段 2 只做索引参数，阶段 3 接数据库人员 ID。
- 已确认：普通账单拒绝负数；引擎支持负数用于冲正/测试。

### 1.7 下一阶段条件

用户确认阶段 2 测试结果；金额/零头/fallback 语义无异议。

---

## 2. 阶段 3：数据库、账单、付款与结算

### 2.1 目标

把分摊引擎落到 PostgreSQL：模型、迁移、事务、账单 CRUD、实收流水、结算快照。此阶段以服务层和集成测试为主；在阶段 4 完成鉴权前**不部署到公网**。

### 2.2 任务清单

1. 创建 SQLAlchemy 模型（按 `docs/database.md`）：
   - users/sessions/households/members/invites/people；
   - periods/occupancies/bills/rules/allocations；
   - payments/settlements/lines/audit；
   - conversations/messages/pending_actions/idempotency。
2. 创建 Alembic 初始迁移：
   - 所有表、CHECK、复合外键、partial unique、索引；
   - 付款/结算/审计不可更新触发器；
   - 迁移从空库可执行。
3. 实现 DB session/transaction 管理。
4. 实现服务：
   - `bill_service`：创建/更新/作废/重算；
   - `period_service`：账期/入住天数/锁定/重开；
   - `payment_service`：登记/调整/汇总；
   - `settlement_service`：预览/创建/查询/导出；
   - `rule_service`：draft/预览/激活（规则部分可提前）；
   - `audit_service`：追加/查询；
   - `allocation_persistence`：把引擎结果写入 `bill_allocations`。
5. 实现核心 API（阶段 3 可用测试 principal/临时开发鉴权，生产关闭）：
   - periods/occupancies/bills/allocations；
   - payments；
   - settlements/preview/create/list/explain/export；
   - 健康检查。
6. 实现幂等表和写接口保护。
7. 集成测试：
   - 迁移；
   - 事务回滚；
   - 账单守恒；
   - 付款不可变；
   - 结算幂等/并发；
   - 规则快照；
   - 数据隔离的数据库层。
8. 备份/恢复脚本雏形（阶段 7 完成演练）。

### 2.3 文件清单

```text
alembic.ini
migrations/env.py
migrations/script.py.mako
migrations/versions/0001_initial.py
src/roommate_billing/db/base.py
src/roommate_billing/db/session.py
src/roommate_billing/db/enums.py
src/roommate_billing/db/models/*.py
src/roommate_billing/schemas/billing.py
src/roommate_billing/schemas/payments.py
src/roommate_billing/schemas/settlements.py
src/roommate_billing/services/bills.py
src/roommate_billing/services/periods.py
src/roommate_billing/services/payments.py
src/roommate_billing/services/settlements.py
src/roommate_billing/services/rules.py
src/roommate_billing/services/audit.py
src/roommate_billing/api/v1/bills.py
src/roommate_billing/api/v1/periods.py
src/roommate_billing/api/v1/payments.py
src/roommate_billing/api/v1/settlements.py
tests/integration/test_migrations.py
tests/integration/test_bills.py
tests/integration/test_payments.py
tests/integration/test_settlements.py
tests/integration/test_idempotency.py
tests/integration/test_concurrency.py
```

### 2.4 如何运行/测试

```bash
docker compose up -d db
alembic upgrade head
uv run pytest tests/integration -q
```

### 2.5 验收标准

- [x] 空库迁移成功；
- [x] 所有表/约束/索引/触发器存在；
- [x] 账单创建 + 分摊在同一事务；
- [x] 每笔账单守恒；
- [x] 付款只追加，修正留原记录；
- [x] 结算保存规则/账单/实收快照；
- [x] 重复结算不重复；
- [x] 并发结算只有一个 final；
- [x] 预览与正式结算一致；
- [x] 账期锁/重开流程；
- [x] 审计前后值；
- [x] 集成测试真实输出。

> 阶段 3 的“核心 API”使用测试用 Principal 依赖覆盖；真实登录/成员权限在阶段 4。

### 2.6 已知风险

- 初始迁移大，已用集成测试覆盖；`upgrade → downgrade → upgrade` 已验证。
- 付款语义已确认：个人已付贡献。
- 账期重开/修订流程已确认：重开 + 新结算修订。
- 新增人员后不会自动重算开放账单，阶段 4 明确成员变更流程。
- 没有阶段 4 鉴权前，不能公网部署。

### 2.7 下一阶段条件

已满足：129 tests passed，coverage 91%，Alembic 从空库升级成功，并发结算/幂等/隔离测试通过。等用户验收后进入阶段 4。

---

## 3. 阶段 4：登录、成员、权限与审计

### 3.1 目标

让系统真正支持多人访问：安全登录、服务端会话、CSRF、邀请、角色、账本隔离、审计。

### 3.2 任务清单

1. 密码 Argon2id、登录锁定、限流。
2. 服务端会话表、Cookie、CSRF。
3. 注册开关/首个管理员 CLI。
4. 邀请码、成员管理、owner 唯一。
5. `Principal` 依赖：user + household + role。
6. 全部 API 加权限校验；跨账本 404。
7. 审计覆盖所有写操作和敏感读取。
8. 安全响应头/CORS/错误脱敏。
9. 测试：
   - 未登录/越权/隔离/CSRF；
   - 会话过期/改密；
   - 角色矩阵；
   - 最后一个 owner；
   - 邀请一次性；
   - 审计不可改。
10. 移除阶段 3 的临时开发 principal，生产只走真实会话。

### 3.3 文件清单

```text
src/roommate_billing/security/passwords.py
src/roommate_billing/security/sessions.py
src/roommate_billing/security/csrf.py
src/roommate_billing/security/rate_limit.py
src/roommate_billing/security/headers.py
src/roommate_billing/security/redaction.py
src/roommate_billing/services/auth.py
src/roommate_billing/services/households.py
src/roommate_billing/services/people.py
src/roommate_billing/api/deps.py
src/roommate_billing/api/v1/auth.py
src/roommate_billing/api/v1/households.py
src/roommate_billing/api/middleware.py
src/roommate_billing/cli.py
tests/integration/test_auth.py
tests/integration/test_isolation.py
tests/integration/test_permissions.py
tests/integration/test_audit.py
```

### 3.4 验收标准

- [x] 未登录不能访问受保护数据；
- [x] 所有写接口校验 CSRF；
- [x] 登录失败锁定（IP 维度限流待阶段 7）；
- [x] 会话可吊销，改密失效；
- [x] 账本隔离测试全通过；
- [x] member 不能执行 admin 操作；
- [ ] Agent 工具不能绕过后端权限（阶段 5 再端到端验证）；
- [x] 审计记录完整且不可改；
- [x] 错误响应不含敏感信息；
- [ ] 安全头生效（CSP 待前端外链化后严格启用）。

### 3.5 下一阶段条件

已满足：真实登录/Cookie/CSRF/邀请/角色/审计测试通过，140 tests passed；无临时鉴权后门。等用户验收后进入阶段 5。

---

## 4. 阶段 5：Agent、模型适配与确认流程

### 4.1 目标

实现自然语言入口，但模型只能通过工具读写服务；所有写操作先生成待确认动作。

### 4.2 任务清单

1. `LLMProvider` 接口 + `OpenAICompatibleProvider` + `FakeProvider` + `DisabledProvider`。
2. 系统提示词、上下文裁剪、工具 schema。
3. 工具网关：
   - 注入 actor/household/role；
   - Pydantic 校验；
   - 只读工具直接执行；
   - 写工具创建 pending_action；
   - 工具错误结构化。
4. 10 个指定工具 + `create_bill/update_bill/void_bill/set_occupancies`。
5. `pending_actions` 确认接口：
   - CSRF + 幂等 + 重新鉴权 + payload hash + 版本；
   - 模型不可见 confirm。
6. 会话/消息持久化、限流、token 预算。
7. 降级：`LLM_ENABLED=false` 时核心 API 正常。
8. 测试：AG-01..18、提示注入、模型失败、确认/幂等。
9. 前端可先用简单聊天页验证（阶段 6 完整 UI）。

### 4.3 文件清单

```text
src/roommate_billing/agent/loop.py
src/roommate_billing/agent/prompts.py
src/roommate_billing/agent/tools.py
src/roommate_billing/agent/confirmations.py
src/roommate_billing/agent/guardrails.py
src/roommate_billing/agent/providers/base.py
src/roommate_billing/agent/providers/openai_compatible.py
src/roommate_billing/agent/providers/fake.py
src/roommate_billing/agent/providers/disabled.py
src/roommate_billing/services/actions.py
src/roommate_billing/api/v1/agent.py
src/roommate_billing/api/v1/actions.py
tests/integration/test_agent*.py
 tests/unit/test_providers.py
```

### 4.4 验收标准

- [x] 用户说“录入电费”能走通只读→预览→准备动作；
- [x] 缺少金额/人员/账期会追问；
- [x] 写工具不直接写正式账；
- [x] 模型没有确认工具；
- [x] 用户确认后只写一次；
- [x] 重复确认幂等；
- [x] 模型不可用时核心功能正常；
- [x] 解释金额与后端一致；
- [ ] 提示注入评测集（当前只测了白名单/未知确认工具）；
- [x] 工具只允许白名单；
- [ ] 真实模型调用（需用户提供 Key；测试不依赖外网）。

### 4.5 下一阶段条件

已满足核心：FakeProvider/HTTP mock 验证工具白名单、pending action、确认幂等、权限与降级，157 tests passed。提示注入评测集和真实模型调用仍需后续补充；等用户验收后进入阶段 6。

---

## 5. 阶段 6：前端改造

### 5.1 目标

保留旧页面的布局、视觉、金额体验和 `data-testid`，增加登录、账本/账期、规则、实收、结算、审计、聊天和确认。

### 5.2 任务清单

1. 把旧单文件拆成：
   - `static/index.html`；
   - `css/tokens.css`、`legacy.css`、`app.css`；
   - `js/app.js`、`api.js`、`store.js`、页面模块。
2. 保留：
   - 暗色视觉；
   - 三列人员/四列账单表格；
   - 金额格式；
   - `data-testid`、`data-person`、`data-bill`、`data-cents`。
3. 新增：
   - 登录/邀请接受；
   - 账本选择；
   - 账期切换；
   - 账单 CRUD/预览；
   - 规则版本对比；
   - 实收录入/调整；
   - 结算预览/确认/历史；
   - 导出；
   - 审计入口；
   - Agent 聊天侧栏；
   - 工具结果/预览卡片/确认/取消；
   - 网络/权限/冲突/限流错误提示。
4. 移除内联脚本/样式（严格 CSP）。
5. 前端只保存 UI 状态；正式账目全部来自 API。
6. 不保存模型 Key。
7. 安全渲染：textContent，不用 innerHTML 拼用户内容。
8. 移动端适配。
9. 旧 DOM 回归测试 + Playwright 冒烟。
10. 加载/空状态/错误状态/重试。

### 5.3 文件清单

```text
web/index.html
web/assets/app.css
web/assets/js/*.js
web/tests/*.test.mjs
scripts/e2e_frontend.mjs
scripts/seed_demo.py
```

### 5.4 验收标准

- [x] 旧的核心数据标记仍可用；
- [x] 旧布局/视觉基本保留；
- [x] 登录、账本、账期、账单、规则、实收、结算、导出、审计、聊天均可操作；
- [x] 预览→确认→刷新后数据仍在；
- [x] 未确认不落账；
- [ ] 错误提示不丢表单（人工检查，未做自动化断言）；
- [x] CSP 下无内联脚本/样式违规；
- [x] 移动端可用；
- [x] 无 API Key/正式账目在前端存储；
- [x] E2E 通过。

### 5.5 下一阶段条件

已满足核心：Chrome E2E 覆盖登录、旧 DOM、规则、账单、实收、锁定、结算、CSV、审计与 Agent 降级，160 tests passed；错误表单保持待人工检查。等用户验收后进入阶段 7。

---

## 6. 阶段 7：测试补全、Docker、CI、备份恢复与安全检查

### 6.1 目标

从“能跑”变成“可部署、可恢复、可维护”。

### 6.2 任务清单

1. 补全单元/集成/Agent/E2E 测试。
2. Dockerfile、Compose、Caddyfile、`.dockerignore`。
3. 迁移服务、非 root、只读、cap_drop。
4. GitHub Actions：
   - lint、迁移、测试、覆盖率、依赖审计、secret scan。
5. 备份脚本/cron/恢复 runbook。
6. 健康检查/日志脱敏/安全头。
7. 并发/幂等/隔离/提示注入回归。
8. 全新环境按 README 启动。
9. 容器重启持久化。
10. 备份→恢复→验证。
11. 依赖审计/容器扫描（可选）。
12. 性能冒烟（20 人/200 账单/100 结算）。

### 6.3 验收标准

- [x] 空库迁移；
- [ ] 全新环境启动（Docker 未执行）；
- [ ] Docker/HTTPS（未执行）；
- [x] Postgres 不暴露（Compose 静态配置）；
- [ ] 重启数据保留（未执行）；
- [x] 备份恢复通过（本地 PostgreSQL 实测）；
- [ ] CI 绿（workflow 已写，未运行）；
- [x] 安全检查；
- [ ] README 命令实测（本地命令已跑；Docker 命令未跑）；
- [x] 无 secrets/真实数据入库。

### 6.4 下一阶段条件

备份恢复、Caddy 本地 TLS、Docker build/run（QEMU）已有真实输出；Compose 编排、GitHub Actions 仍未执行；Caddy HTTPS 已通过。

---

## 7. 阶段 8：文档、许可证与 GitHub 发布

### 7.1 目标

整理为可公开的 GitHub 项目，并完成首次 Release。

### 7.2 任务清单

1. 完成 README 15 项。
2. 许可证：MIT 已创建 LICENSE。
3. CONTRIBUTING/SECURITY/CHANGELOG/CODE_OF_CONDUCT（可选）。
4. 架构/数据库/API/Agent/安全/测试/部署文档最终校对。
5. `.env.example`、`.gitignore`、`.dockerignore`。
6. secret scan / 真实数据检查。
7. `git init`、首次提交、远程、PR/分支保护。
8. CI 绿。
9. Tag `v0.1.0`、Release notes。
10. 可选 GHCR 镜像。
11. 公开前最终检查。
12. 发布后 issue/dependabot/维护计划。

### 7.3 验收标准

- [ ] README 命令全部验证（本地命令已验证；Docker 命令未跑）；
- [x] LICENSE 已确认并一致（MIT）；
- [ ] CI 绿（workflow 已写，未运行）；
- [x] 无 secrets/真实数据（secret scan 0 hits）；
- [x] 备份恢复文档；
- [x] 已知限制；
- [x] 贡献指南；
- [ ] Release 可下载/可部署（本地 bundle/zip 有；GitHub Release 未创建）；
- [ ] 仓库公开（当前默认 Private，未创建远程）。

---

## 8. 跨阶段工程规范

### 8.1 提交

- 小步提交，主题明确：
  - `feat: add integer allocation engine`
  - `test: cover zero-weight fallback`
  - `fix: reject >2 decimal places`
  - `docs: add deployment runbook`
- 不把多个不相关改动塞进一个 PR。
- 不提交 `.env`/密钥/真实数据。

### 8.2 分支

- `main` 保护；
- `feat/phase-2-allocation`；
- `feat/phase-3-settlements`；
- 每个阶段一个 PR/里程碑。

### 8.3 代码质量

- Python 3.12；类型标注；ruff。
- 关键业务逻辑中文注释。
- 金额只用整数分。
- 服务层事务边界清晰。
- 错误码稳定。
- 测试命名对应业务规则。

### 8.4 文档同步

- 代码行为改变 → 更新 `docs/`；
- API 改变 → 更新 OpenAPI/`docs/api.md`；
- 数据库改变 → Alembic + `docs/database.md`；
- 规则改变 → 版本 + 测试 + 文档；
- 部署改变 → README/部署文档。

### 8.5 完成定义（Definition of Done）

一个任务只有同时满足才算完成：

- [ ] 代码实现；
- [ ] 单元/集成测试；
- [ ] 错误/权限/边界；
- [ ] 审计（如适用）；
- [ ] 文档；
- [ ] 本地命令可复现；
- [ ] 没有 secrets/真实数据；
- [ ] 用户验收。

---

## 9. 依赖与阻塞

| 依赖 | 影响 | 处理 |
|---|---|---|
| 付款语义 | 数据模型/结算 | ✅ 已确认：个人已付贡献 |
| 账期修正流程 | 重开/修订 | ✅ 已确认：重开 + 新结算修订 |
| 许可证 | 发布 | ✅ MIT |
| Docker / PostgreSQL 环境 | 阶段 3/7 | ✅ 阶段 3 用本地 PostgreSQL 16.15；Docker 仍待阶段 7 |
| Python 3.12 | 阶段 2 起 | ✅ 已确认：3.12.14 |
| 模型 API Key | 阶段 5 真实调用 | 测试用 FakeProvider，不阻塞核心 |
| 域名/服务器 | 阶段 7 HTTPS | 可先用内网/本地验证 |
| 备份存储 | 阶段 7 | 宿主机目录/对象存储 |

---

## 10. 当前请求的停止点

阶段 0–6 已完成；阶段 7 交付物已完成、运行时未验证：

- 旧页面审查、数值复现、缺陷清单；
- 技术选型、架构图、目录结构；
- 数据库设计；
- API 清单；
- Agent 工具与确认流程；
- 安全/测试/部署/发布计划；
- 整数分摊引擎、79 个测试、`uv.lock`；
- PostgreSQL 16 + Alembic、20 张表、47 个 API path、160 个测试、覆盖率 88%；
- Agent Provider/工具/确认/动作；
- 前端/CSP/Chrome E2E；
- Docker/Compose/Caddy/CI/备份恢复交付物；
- 本地备份恢复真实演练与非 Docker 安全检查；
- MIT、社区文档、本地 Git `v0.1.0-rc.1`、bundle/zip；
- GitHub 远程/Release 待推送。

**本地 rc.1 已完成；剩余：GitHub 远程 push/Actions、Compose 编排、公网 ACME TLS。** 用户已确认：

1. 历史实收：个人已付贡献；
2. 账期修正：重开 + 新结算修订；
3. 普通账单拒绝负数，引擎支持负数用于冲正/测试；
4. 入住天数：整数 0–31；
5. 确认工具不暴露给模型；
6. 保留 `legacy/` 旧页面。

仍未确认：

- 仓库 Public/Private 与 GitHub 远程地址（当前无远程）；
- 真实模型 API Key 与 Provider（阶段 5 只用 Fake/HTTP mock）；
- Compose 编排环境与 GitHub 远程。
