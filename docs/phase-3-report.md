# 阶段 3 报告：数据库、账单、付款、结算与核心 API

- 状态：**核心阶段 3 已完成，等待验收后进入阶段 4（认证/权限/审计查询）**。
- 本阶段不包含真实登录、会话、CSRF、前端、Agent、Docker/CI。
- 当前 API 的 `get_current_principal` 默认返回 401；集成测试通过依赖覆盖注入测试主体。**不能作为生产 API 部署。**

---

## 1. 本阶段目标

1. 用 PostgreSQL 16 落地上阶段设计的数据模型；
2. 用 Alembic 管理结构；
3. 把整数分摊引擎接入账单/规则/入住天数；
4. 实现付款只追加、结算快照、幂等与并发保护；
5. 提供核心 REST API；
6. 用真实 PostgreSQL 做集成测试，而不是用 SQLite 模拟。

---

## 2. 实际环境

- Windows 10 专业版，PostgreSQL **16.15**（本地服务 `postgresql-roommate`，端口 `127.0.0.1:55432`）。
- 数据库：`roommate_billing`（开发）、`roommate_test`（测试）。
- 数据目录/密码文件在项目外的 `_runtime/`，不进 Git；`.env` 已被 `.gitignore` 忽略。
- Python 3.12.14 / SQLAlchemy 2.0.55 / psycopg 3.3.6 / Alembic 1.20.1 / FastAPI 0.160.0。
- Alembic head：`82f2f551741e`。

> 当前环境没有 Docker；本地 PostgreSQL 仅用于开发与测试，生产仍按 Docker Compose 方案在阶段 7 验证。

---

## 3. 数据库实现

### 3.1 已创建的 15 张表

- `users`
- `households`
- `household_members`
- `people`
- `billing_periods`
- `occupancies`
- `bills`
- `rule_versions`
- `rule_version_items`
- `bill_allocations`
- `payments`
- `settlements`
- `settlement_lines`
- `audit_logs`
- `idempotency_keys`

尚未创建（阶段 4/5）：

- `auth_sessions`、`household_invites`（阶段 4）
- `agent_conversations`、`agent_messages`、`pending_actions`（阶段 5）

### 3.2 已落地的关键约束

- 所有金额 `bigint` 分。
- 每个账单分摊行 `amount = base + remainder`。
- 账单金额 0–100,000,000,000 分。
- 入住天数 0–31。
- 每账本一个 active 规则版本（partial unique index）。
- 每账期最多一个 final 结算（partial unique index）。
- 每账期 `(revision)` 唯一。
- 付款/结算行/审计日志只追加（数据库触发器拒绝 UPDATE/DELETE）。
- 关键父子关系使用复合外键 `(household_id, id)`，防止跨账本挂接。
- 规则/账单/账期/幂等写入同一事务。
- 幂等键 `(actor, household, scope, key)` 唯一。

### 3.3 迁移

- `migrations/versions/82f2f551741e_initial_billing_schema.py`
- 从空 schema 升级成功。
- 迁移包含三个 append-only 触发器。
- `alembic check`：无模型/迁移漂移。
- 测试 session 启动时 `DROP SCHEMA public CASCADE; CREATE SCHEMA public; alembic upgrade head`，确保每次都从空库开始。
- 已额外验证 `upgrade head → downgrade base → upgrade head`，均成功。

---

## 4. 服务层实现

| 服务 | 能力 |
|---|---|
| `allocations` | 人员/入住天数/规则 → 整数分摊；重算账期；写 `bill_allocations` |
| `bills` | 创建/更新/作废账单；单笔守恒；只读 `split_preview` |
| `periods` | 创建账期；设置入住天数并重算；锁定/重开 |
| `rules` | 初始规则；创建草稿；影响预览；管理员激活；历史规则保留 |
| `payments` | 登记实收；负向调整；只追加；按人汇总 |
| `settlements` | 预览；正式快照；修订/superseded；解释；CSV 导出 |
| `idempotency` | 请求哈希 + 唯一 scope/key；重放响应 |
| `audit` | 写操作前后值 JSONB；只追加 |
| `ledger` | 当前账本/账期摘要 |
| `households` | 创建账本、人员、owner 成员 |

### 4.1 分摊关键规则

- 人员按 `slug` 稳定排序（`lin`, `zhe`, `zhou`），不依赖 UUID/创建时间。
- 零头归属人存的是人员外键，不存数组下标。
- 每笔账单守恒；失败回滚。
- 权重全 0 时走均分 fallback。

### 4.2 结算关键规则

- 预览与正式结算使用同一 `preview()` 函数。
- 正式结算要求账期 `locked`。
- `preview_hash` 覆盖账期版本、规则、账单/分摊、实收、每人差额。
- 旧 final 先标记 `superseded` 再插入新 final，避免 partial unique 冲突。
- 每个账期最多一个 final。
- 结算行保存 allocated/paid/balance/remainder；`bills_snapshot` 保存逐账单分摊；`rule_snapshot` 保存规则。

### 4.3 幂等与并发

- 账单创建/作废、付款创建/调整、规则草稿/激活、结算创建要求 `Idempotency-Key`。
- scope 包含资源 ID，例如 `create_bill:{period_id}`、`create_settlement:{period_id}`。
- 并发结算测试：两个线程同时创建，只有一个 final，另一个收到 `PERIOD_NOT_LOCKED`/`VERSION_CONFLICT`。
- 账期行锁 `SELECT FOR UPDATE` 串行化财务写。

---

## 5. API 实现

已注册 29 个 OpenAPI path：

- 健康：`/health/live`、`/health/ready`
- 元信息：`/api/v1/meta`
- 账本/人员：`GET/POST /households`、`GET /households/{hid}`、`GET/POST /people`、`GET /ledger/current`
- 账期：列表/创建/详情、入住天数、锁定、重开
- 账单：列表/创建/详情/修改/作废/分摊、`split-preview`
- 付款：列表/创建/详情/调整
- 规则：列表/草稿/详情/预览/激活
- 结算：预览/创建/列表/详情/解释/CSV 导出

统一：

- 错误格式 `{"error": {"code", "message", "details", "request_id"}}`；
- `X-Request-ID` 响应头；
- 版本冲突 409；
- 权限不足 403；
- 跨账本 404；
- 写接口幂等键。

完整设计见 `docs/api.md`；实际实现路径可用 `/openapi.json` 查看。

---

## 6. 测试结果

### 6.1 命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

### 6.2 实测

```text
129 passed, 1 warning in 35.44s
All checks passed!
80 files already formatted
coverage: 91% (1910 statements, 173 missed)
```

说明：最后一次全量测试不带 coverage 的耗时是 35.44s；带 coverage 的耗时 47.09s。两者测试结果均为 129 passed。

唯一的 warning 来自 FastAPI/Starlette TestClient 对 httpx 的弃用提示；不影响测试结果，后续依赖升级时处理。

### 6.3 覆盖的关键场景

- 空库迁移、三个 append-only 触发器。
- 4 笔账单 × 3 人逐笔守恒。
- 创建/修改/作废账单后重算。
- 入住天数变化后重算。
- 规则草稿 → 预览 → 激活；旧 active 归档；开放账期重算。
- 预览后账单变化导致激活被拒绝。
- 付款登记/调整、只追加触发器、超额调整拒绝。
- 结算预览/创建/重复创建/修订/superseded。
- 结算解释与 CSV 导出。
- 规则变更不修改历史付款行。
- 结算保存规则版本与账单快照。
- 幂等请求重放与同 key 不同 body 冲突。
- 跨账本 404、成员越权 403、未登录 401。
- 并发结算只产生一个 final。
- 健康检查不泄露配置。

---

## 7. 已知限制

1. **没有真实认证**：所有受保护路由默认 401；测试通过依赖覆盖注入 Principal。阶段 4 接入 Argon2id、会话、CSRF、邀请。
2. **`POST /households` 创建后不能切换当前账本**：Principal 目前只有单账本上下文；阶段 4 加账本选择/成员关系解析。
3. **新增人员后不自动重算开放账单**：阶段 4 的成员管理会明确“新增/停用人员是否重算当前开放账期”的流程；当前需重新 PUT 入住天数触发重算。
4. **`users.password_hash` 暂可为空**：阶段 4 接入密码后改为 NOT NULL（可能需要一次数据回填迁移）。
5. **没有审计查询 API**：审计已写入，查询/展示在阶段 4。
6. **部分写接口尚未加幂等键**：household/person/period 创建按唯一约束/业务低风险处理；财务写已加。
7. **没有 CSRF/CSP/限流**：阶段 4/7。
8. **没有 Docker/CI/备份恢复演练**：阶段 7。
9. **没有前端/Agent**：阶段 5/6。
10. **迁移已测试 upgrade/downgrade/upgrade**；生产升级仍需备份。
11. **覆盖率 91%，非 100%**：未覆盖分支主要是错误处理/少数 CRUD 分支；关键财务路径已有测试。

---

## 8. 文件清单

```text
alembic.ini
migrations/env.py
migrations/script.py.mako
migrations/versions/82f2f551741e_initial_billing_schema.py
src/roommate_billing/config.py
src/roommate_billing/main.py
src/roommate_billing/db/base.py
src/roommate_billing/db/session.py
src/roommate_billing/db/models/*.py
src/roommate_billing/domain/*.py
src/roommate_billing/schemas/api.py
src/roommate_billing/services/*.py
src/roommate_billing/api/deps.py
src/roommate_billing/api/errors.py
src/roommate_billing/api/serializers.py
src/roommate_billing/api/v1/*.py
tests/conftest.py
tests/integration/*.py
```

测试数据只使用虚构的 lin/zhe/zhou、287.65/96.40/89.00/20.00 等示例金额；不包含真实收款/个人信息。

---

## 9. 阶段 4 开始条件

- 用户验收本报告；
- 确认阶段 4 范围：Argon2id 密码、服务端会话、CSRF、邀请、成员/角色、账本切换、审计查询；
- 确认 `POST /households` 多账本切换的用户体验；
- 确认新增/停用人员是否触发开放账期重算；
- 许可证仍待选择（不影响开发）。

阶段 4 不会自动开始，等待用户确认。
