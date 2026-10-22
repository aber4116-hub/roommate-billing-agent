# 阶段 4 报告：登录、会话、CSRF、邀请、成员权限与审计查询

- 状态：**核心阶段 4 已完成；后续阶段 5 已实现，见 `phase-5-report.md`**。
- 本阶段不包含前端、Agent、Docker/CI。
- 真实认证已接入；旧的集成测试通过依赖覆盖注入 Principal，认证测试使用真实 Cookie/CSRF。

---

## 1. 本阶段目标

1. Argon2id 密码哈希与登录锁定；
2. 服务端会话、HttpOnly Cookie、CSRF；
3. 账本邀请、成员角色、账本切换；
4. 每个受保护 API 的真实身份验证与账本权限；
5. 审计日志查询；
6. 用真实 Cookie/Session 的 API 集成测试验证。

---

## 2. 新环境/迁移

- PostgreSQL 16.15（本地服务 `postgresql-roommate`，127.0.0.1:55432）。
- 新迁移：`bc8299ee45ed_auth_sessions_and_invites.py`。
- 新增表：
  - `auth_sessions`
  - `household_invites`
- 当前共 17 张表。
- `alembic check`：无漂移。
- 已验证完整 `upgrade head → downgrade base → upgrade head`（包含阶段 3 和阶段 4 迁移）。
- OpenAPI path：40 个。

---

## 3. 认证与会话实现

### 3.1 密码

- Argon2id（`argon2-cffi`），不存明文。
- 密码长度 12–128。
- 登录失败统一返回 `INVALID_CREDENTIALS`，不区分邮箱是否存在。
- 不存在账户也执行 dummy verify，降低时序枚举。
- 连续失败 5 次锁定账户 15 分钟（`ACCOUNT_LOCKED`/423）。
- 登录成功重置失败计数和锁定。

### 3.2 会话

- 服务端 `auth_sessions`，数据库只存 session token 的 SHA-256。
- Cookie：
  - 生产 `__Host-rba_session`：HttpOnly、Secure、SameSite=Lax、Path=/；
  - 本地 `rba_session`（`SESSION_COOKIE_SECURE=false`）。
- 绝对有效期 7 天；空闲 24 小时。
- 登出/改密吊销。
- 请求时更新 `last_seen_at`。
- 过期/吊销/空闲超时返回 401。

### 3.3 CSRF

- 登录时生成随机 CSRF token；
- 数据库存 HMAC-SHA256（用 `APP_SECRET_KEY` 作为 pepper）；
- Cookie `rba_csrf`（非 HttpOnly）供前端读取；
- 所有非 GET/HEAD/OPTIONS 的受保护请求必须同时满足：`X-CSRF-Token`、`rba_csrf` Cookie 值一致、且与数据库 session 中的 HMAC 匹配；
- 失败返回 403 `CSRF_INVALID`；
- `GET /auth/csrf` 可轮换 token；
- 登录/注册无会话，使用 Origin 校验（`APP_BASE_URL`）。

### 3.4 会话安全

- Login 失败也会写审计（未知邮箱 actor 为空；已知账户记录 actor）。
- 失败计数/锁定/审计在返回错误前显式提交，避免被请求事务回滚。
- 改密吊销其他会话，当前会话保留。
- 测试覆盖：登录、错误密码、锁定、CSRF、轮换、过期、登出、改密吊销。

---

## 4. 成员、邀请与多账本

### 4.1 Principal

`Principal` 现在包含：

- `user_id`
- `session_id`
- `household_id`（当前活动账本）
- `role`（活动账本角色）
- `person_id`（活动账本绑定的人员）
- `memberships: {household_id: role}`
- `person_ids: {household_id: person_id}`

`X-Household-ID` 可用于选择当前账本；未提供时使用第一个 active 成员关系。路径中的账本仍会逐请求校验成员关系。

### 4.2 邀请

- `POST /households/{hid}/invites`：owner/admin 创建一次性邀请码（7 天）；
- 数据库只存 token SHA-256；原始 token 只在创建响应出现一次；
- 角色只能是 admin/member；
- `POST /auth/invites/accept`：登录用户接受邀请；
- 邮箱匹配、一次性、过期校验；
- 接受后写审计。

### 4.3 成员管理

- `GET /households/{hid}/members`：成员可见；
- `PATCH /households/{hid}/members/{uid}`：只有 owner 可改 admin/member 或 active/left；
- 不允许通过该接口修改 owner；所有权转移留待后续；
- 不能修改最后一个 owner（owner 本身不可被此接口降级/移除）。

### 4.4 多账本

- 创建新账本后，用户可通过 `X-Household-ID` 切换；
- `GET /households` 返回用户所有 active 账本；
- `GET /auth/me` 返回成员关系；
- 跨账本路径返回 404。

---

## 5. 审计查询

- `GET /households/{hid}/audit-logs`：仅 owner/admin。
- 分页：`limit` 1–200，`before_id`。
- 返回 actor、action、entity、before/after、metadata、request_id、时间。
- 审计写入仍由各服务完成；审计表只追加。

---

## 6. API 清单（新增/变更）

新增：

- `POST /api/v1/auth/login`
- `POST /api/v1/auth/register`（默认关闭）
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/csrf`
- `POST /api/v1/auth/password`
- `POST /api/v1/auth/invites/accept`
- `GET /api/v1/households/{hid}/members`
- `PATCH /api/v1/households/{hid}/members/{uid}`
- `GET /api/v1/households/{hid}/invites`
- `POST /api/v1/households/{hid}/invites`
- `GET /api/v1/households/{hid}/audit-logs`

变更：

- 所有受保护路由现在要求真实 Session Cookie；
- 所有非安全方法要求 CSRF；
- `require_admin` 按路径账本角色判断；
- member 登记付款时按路径账本绑定人员判断。

---

## 7. 测试结果

### 7.1 命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest --cov=roommate_billing --cov-report=term:skip-covered
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

### 7.2 实测

```text
140 passed, 1 warning in 45.48s
coverage: 89% (2435 statements, 276 missed)
ruff check: All checks passed
ruff format --check: 93 files formatted
alembic check: No new upgrade operations detected
```

带覆盖率耗时 56.74s。

### 7.3 覆盖的场景

- 真实登录 + Cookie + CSRF；
- 无 CSRF 写请求 403；
- CSRF 轮换后旧 token 失效；
- 错误密码、5 次失败锁定、锁定后 423；
- 会话绝对过期 401；
- 登出后 401；
- 改密后其他会话 401；
- Origin 不在 `APP_BASE_URL` 时拒绝；
- 邀请创建/接受；
- 多账本 `X-Household-ID` 切换；
- owner 修改成员角色；
- admin 查询审计、member 查询审计 403；
- 默认关闭注册；
- 原有账务/结算/幂等/并发测试继续通过。

---

## 8. 已知限制

1. **没有前端登录页**：阶段 6。
2. **没有 Agent**：当时尚未实现；阶段 5 已补齐。
3. **没有 IP 维度限流**：当前只有账户锁定；阶段 7 加。
4. **没有 MFA/密码重置邮件**：v1 不做；管理员通过 CLI 重置。
5. **没有所有权转移**：owner 不可变更；后续可加转移流程。
6. **没有会话列表/远程吊销 UI**：只有登出和改密吊销其他会话。
7. **`users.password_hash` 仍可空**：无密码用户不能登录；阶段 6/7 可做数据回填并设为 NOT NULL。
8. **审计无哈希链/WORM**：只追加 + 数据库触发器；归档/防篡改后续增强。
9. **一个 TestClient/httpx 弃用 warning**：不影响测试。
10. **没有 Docker/CI/备份恢复演练**：阶段 7。

---

## 9. 文件清单

```text
migrations/versions/bc8299ee45ed_auth_sessions_and_invites.py
src/roommate_billing/db/models/auth.py
src/roommate_billing/security/passwords.py
src/roommate_billing/security/principal.py
src/roommate_billing/security/cookies.py
src/roommate_billing/services/auth.py
src/roommate_billing/api/deps.py
src/roommate_billing/api/v1/auth.py
src/roommate_billing/api/v1/audit.py
src/roommate_billing/api/v1/households.py
src/roommate_billing/cli.py
tests/integration/test_auth.py
tests/integration/test_auth_sessions.py
```

---

## 10. 阶段 5 开始条件

- 用户验收本报告；
- 确认 Agent 的写操作/确认协议（阶段 1 已设计：模型不能确认，用户点击确认）；
- 确认模型 API 配置环境（可关闭，核心账务仍可用）；
- 许可证仍待选择（不影响开发）。

阶段 5 已在后续实现，见 `phase-5-report.md`。
