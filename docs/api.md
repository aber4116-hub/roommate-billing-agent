# 阶段 1：REST API 设计

- Base URL：`/api/v1`
- 内容类型：`application/json; charset=utf-8`（导出为 `text/csv`）
- 认证：HttpOnly 会话 Cookie
- 多租户：所有账本资源都在路径中包含 `household_id`，服务端逐请求校验成员关系
- 金额：所有请求/响应金额使用整数分，字段名以 `_cents` 结尾
- 版本：URL 版本 `/api/v1`；后续不破坏兼容的字段只做加法

> 本文是设计，不是完整已实现接口。阶段 3 已实现核心账务/规则/付款/结算 API；阶段 4 已实现登录/会话/CSRF/邀请/成员/审计；阶段 5 已实现 Agent 会话/工具/待确认动作；阶段 6 已实现前端并新增会话动作列表（共 47 个 OpenAPI path）。

---

## 1. 通用约定

### 1.1 认证与会话

- 登录成功后设置：
  - `__Host-rba_session`：HttpOnly、Secure、SameSite=Lax、Path=/；
  - `rba_csrf`：非 HttpOnly，供前端读取并放入 `X-CSRF-Token`，SameSite=Lax。
- 所有非 GET/HEAD/OPTIONS 请求必须带 `X-CSRF-Token`；登录/注册等无会话端点使用 Origin/Referer 校验，登录后所有写请求都使用 CSRF。
- 会话绝对有效期默认 7 天，空闲 24 小时；改密/登出吊销。
- 不使用 `Authorization: Bearer`，不在 localStorage 放会话令牌。
- 同源部署，默认不启用 CORS；如必须分离部署，使用显式白名单，不使用 `*`。

### 1.2 统一响应

成功：

```json
{
  "data": { "...": "..." },
  "meta": { "request_id": "..." }
}
```

列表：

```json
{
  "data": {
    "items": [],
    "next_cursor": "opaque-string-or-null"
  },
  "meta": { "request_id": "..." }
}
```

错误：

```json
{
  "error": {
    "code": "VERSION_CONFLICT",
    "message": "账单已被其他人修改，请刷新后重试。",
    "details": [],
    "request_id": "..."
  }
}
```

- 生产环境不返回堆栈、SQL、DSN、配置值。
- 校验错误 `details` 只含字段路径和可公开原因。
- 所有响应带 `X-Request-ID`；客户端可传 `X-Request-ID`，服务端校验格式后复用。

### 1.3 状态码

| 状态码 | 用途 |
|---|---|
| `200` | 查询/更新成功 |
| `201` | 创建成功 |
| `204` | 无响应体成功（登出/删除邀请等） |
| `400` | 请求格式/语义错误 |
| `401` | 未登录/会话过期 |
| `403` | 已登录但权限不足/CSRF 失败 |
| `404` | 资源不存在，或跨账本不可见 |
| `409` | 版本冲突、账期已锁、幂等冲突、预览过期 |
| `422` | 字段校验失败 |
| `423` | 账户锁定（登录） |
| `429` | 限流 |
| `500` | 未预期错误 |
| `503` | 数据库/模型服务不可用 |

### 1.4 错误码

| code | HTTP | 说明 |
|---|---:|---|
| `AUTH_REQUIRED` | 401 | 未登录/会话失效 |
| `INVALID_CREDENTIALS` | 401 | 邮箱或密码错误（不区分） |
| `ACCOUNT_LOCKED` | 423 | 登录失败过多 |
| `CSRF_INVALID` | 403 | CSRF 缺失/不匹配 |
| `FORBIDDEN` | 403 | 角色/资源权限不足 |
| `NOT_FOUND` | 404 | 资源不存在或跨账本 |
| `VALIDATION_ERROR` | 422 | 参数校验失败 |
| `VERSION_CONFLICT` | 409 | `expected_version` 不匹配 |
| `PERIOD_NOT_OPEN` | 409 | 账期非开放状态 |
| `PERIOD_NOT_LOCKED` | 409 | 结算要求先锁定 |
| `RULE_PREVIEW_STALE` | 409 | 规则预览哈希过期 |
| `SETTLEMENT_PREVIEW_STALE` | 409 | 结算预览哈希过期 |
| `IDEMPOTENCY_KEY_REUSED` | 409 | 同 key 不同请求体 |
| `REQUEST_IN_PROGRESS` | 409 | 同 key 请求正在处理 |
| `ACTION_EXPIRED` | 409 | 待确认动作过期 |
| `ACTION_CONSUMED` | 409 | 动作已确认/取消 |
| `RATE_LIMITED` | 429 | 触发限流 |
| `AGENT_UNAVAILABLE` | 503 | 模型未配置/不可用 |
| `DB_UNAVAILABLE` | 503 | 数据库不可用 |
| `INTERNAL_ERROR` | 500 | 未预期错误 |

### 1.5 分页

- Query：`limit`（1–100，默认 50）、`cursor`（不透明字符串）。
- 响应：`items`、`next_cursor`。
- 排序默认按 `created_at DESC, id DESC`；接口可指定允许的排序字段。
- 不使用页码，避免数据插入导致重复/遗漏。

### 1.6 并发控制

- 可变资源带整数 `version`（账单、账期）或 `row_version`（规则草稿）。
- 更新请求必须带 `expected_version`；不匹配 → `409 VERSION_CONFLICT`。
- 服务端不静默覆盖较新数据。
- 账期锁：所有财务写先 `SELECT ... FOR UPDATE`。

### 1.7 幂等

- 对创建账单、付款、调整、规则激活、结算、动作确认要求请求头：
  `Idempotency-Key: <uuid-v4>`。
- 服务端以 `(actor_user_id, household_id, 逻辑 scope, key)` 去重，保存 24 小时；scope 包含资源 ID（如 `create_bill:{period_id}`）。
- 同 key 同 body → 重放原响应；同 key 不同 body → 409。
- Agent 消息使用 `client_message_id` 去重。
- `GET` 不需要幂等键。

### 1.8 权限模型

| 操作 | owner | admin | member |
|---|---|---|---|
| 查看账本/账单/结算 | ✅ | ✅ | ✅ |
| 创建/编辑/作废账单 | ✅ | ✅ | ❌ |
| 编辑入住天数 | ✅ | ✅ | ❌ |
| 创建规则草稿/预览 | ✅ | ✅ | ❌（只读预览可开放） |
| 激活规则 | ✅ | ✅ | ❌ |
| 登记付款 | 任意人 | 任意人 | 仅本人 |
| 付款调整/冲正 | ✅ | ✅ | ❌ |
| 创建正式结算 | ✅ | ✅ | ❌ |
| 邀请成员 | ✅ | ✅ | ❌ |
| 修改成员角色 | ✅ | ❌ | ❌ |
| 查看审计日志 | ✅ | ✅ | ❌ |
| 导出结算 | ✅ | ✅ | ✅ |
| 归档账本 | ✅ | ❌ | ❌ |
| Agent 只读工具 | ✅ | ✅ | ✅ |
| Agent 写工具 | 创建待确认动作 | 创建待确认动作 | 仅本人付款的待确认动作 |

- Agent 权限永远继承当前用户，不额外提权。
- 未授权跨账本统一 404，避免泄露存在性。
- 账本 owner 唯一；admin 不能修改 owner。

### 1.9 审计

以下操作必须写 `audit_logs`：

- 登录成功/失败（写安全日志，不含密码）；
- 创建/修改/作废账单；
- 修改入住天数；
- 创建/激活规则；
- 登记付款/调整；
- 锁定/重开账期；
- 创建结算/重放/导出；
- 修改成员/角色/邀请；
- 确认/取消 Agent 动作；
- 查看审计日志（可记录“查看”事件）。

普通读取、预览不强制审计；导出和敏感读取建议审计。

### 1.10 限流

| 端点 | 建议限制 |
|---|---|
| 登录 | 5 次/分钟/IP，10 次/小时/邮箱 |
| 注册 | 3 次/小时/IP |
| 普通写 | 60 次/分钟/用户 |
| Agent 消息 | 20 次/小时/用户 + 每日 token 预算 |
| 导出 | 10 次/小时/用户 |
| 普通读 | 300 次/分钟/用户 |

- 超限返回 `429 RATE_LIMITED` 和 `Retry-After`。
- v1 单实例内存限流 + DB 登录锁定；多实例时迁移到 Redis。

---

## 2. 接口清单

### 2.1 健康检查（无需登录）

| 方法 | URL | 请求 | 响应 | 说明 |
|---|---|---|---|---|
| GET | `/health/live` | 无 | `{"status":"ok"}` | 进程存活，不查 DB |
| GET | `/health/ready` | 无 | `{"status":"ok"}` / 503 `{"status":"unavailable"}` | 执行 `SELECT 1`，不返回异常/配置 |
| GET | `/api/v1/meta` | 无 | `{"version":"0.1.0","api_version":"v1"}` | 只返回公开版本信息 |

### 2.2 认证与账户

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| POST | `/auth/register` | 公开（可关闭） | `{email,password,display_name}` → 会话 + 用户 | 是 | 建议 | 是 |
| POST | `/auth/login` | 公开 | `{email,password}` → 会话 + CSRF + 用户 | 是 | 否 | 是（成功/失败） |
| POST | `/auth/logout` | 登录 | 空 → 204 | 是 | 否 | 是 |
| GET | `/auth/me` | 登录 | 用户 + 账本列表 + 角色 | 否 | — | 否 |
| GET | `/auth/csrf` | 登录 | `{csrf_token}` | 否 | — | 否 |
| POST | `/auth/password` | 登录 | `{current_password,new_password}` → 204 | 是 | 否 | 是 |
| POST | `/auth/sessions/revoke-all` | 登录 | 空 → 204 | 是 | 否 | 是 |
| POST | `/auth/invites/accept` | 登录 | `{token}` → 账本成员 | 是 | 是 | 是 |

- 注册默认关闭（`ALLOW_REGISTRATION=false`）；首个管理员通过 CLI 创建。
- 登录失败统一 `INVALID_CREDENTIALS`，不暴露邮箱是否存在；使用 dummy hash 抗时序枚举。
- 密码长度 12–128；Argon2id。
- 邀请 token 只显示一次；数据库只存 SHA-256。

### 2.3 账本与成员

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| GET | `/households` | 登录 | 当前用户加入的账本列表 | 否 | — | 否 |
| POST | `/households` | 登录 | `{name,timezone?}` → 账本 + owner 成员 | 是 | 是 | 是 |
| GET | `/households/{hid}` | 成员 | 账本详情 | 否 | — | 否 |
| PATCH | `/households/{hid}` | owner | `{name?,timezone?,expected_version?}` | 是 | 否 | 是 |
| GET | `/households/{hid}/members` | 成员 | 成员列表（不含密码/会话） | 否 | — | 否 |
| PATCH | `/households/{hid}/members/{uid}` | owner | `{role?,status?}` | 是 | 否 | 是 |
| GET | `/households/{hid}/invites` | admin | 未接受且未过期邀请 | 否 | — | 否 |
| POST | `/households/{hid}/invites` | admin | `{email?,role}` → `{token,expires_at}` | 是 | 是 | 是 |
| DELETE | `/households/{hid}/invites/{iid}` | admin | 空 → 204 | 是 | 否 | 是 |
| GET | `/households/{hid}/ledger/current` | 成员 | 当前账期摘要、人员、规则、账单合计 | 否 | — | 否 |

- `role` 只允许 `admin/member`；不能邀请 owner。
- 不能移除最后一个 owner。
- 账本归档后只读，不能新增财务数据。

### 2.4 人员

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| GET | `/households/{hid}/people` | 成员 | 人员列表（含 inactive） | 否 | — | 否 |
| POST | `/households/{hid}/people` | admin | `{display_name,slug?,user_id?}` → 人员 | 是 | 是 | 是 |
| GET | `/households/{hid}/people/{pid}` | 成员 | 人员详情 | 否 | — | 否 |
| PATCH | `/households/{hid}/people/{pid}` | admin | `{display_name?,slug?,is_active?,user_id?,expected_version?}` | 是 | 否 | 是 |

- `slug` 账本内唯一；默认从显示名生成 ASCII slug，冲突则追加序号。
- 不能把两个人员绑定同一用户。
- 停用人员不删除历史分摊/付款。

### 2.5 账期与入住天数

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| GET | `/households/{hid}/periods` | 成员 | 分页账期列表，按 `period_key` 降序 | 否 | — | 否 |
| POST | `/households/{hid}/periods` | admin | `{period_key:"2026-10", starts_on?,ends_on?}` → 账期 | 是 | 是 | 是 |
| GET | `/households/{hid}/periods/{pid}` | 成员 | 账期 + 状态 + version | 否 | — | 否 |
| PATCH | `/households/{hid}/periods/{pid}` | admin | `{starts_on?,ends_on?,expected_version}` | 是 | 否 | 是 |
| POST | `/households/{hid}/periods/{pid}/lock` | admin | `{expected_version}` → 账期 | 是 | 是 | 是 |
| POST | `/households/{hid}/periods/{pid}/reopen` | admin | `{reason,expected_version}` → 账期 | 是 | 是 | 是 |
| GET | `/households/{hid}/periods/{pid}/occupancies` | 成员 | 每人天数 | 否 | — | 否 |
| PUT | `/households/{hid}/periods/{pid}/occupancies` | admin | `{items:[{person_id,days}],expected_version}` → 结果 | 是 | 否 | 是 |

- 只允许 `open` 账期修改日期/天数；`locked/settled` 需先重开。
- `days` 为 0–31 整数。
- 修改天数会重算该账期所有开放账单分摊，事务内完成并审计。
- `reopen` 必须写原因；生成审计；旧 final 结算保留，后续新结算修订。

### 2.6 账单与分摊

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| GET | `/households/{hid}/periods/{pid}/bills` | 成员 | 账单列表（含分摊合计） | 否 | — | 否 |
| POST | `/households/{hid}/periods/{pid}/bills` | admin | `{category,name,amount_cents,incurred_on?}` → 账单 + 分摊 | 是 | 是 | 是 |
| GET | `/households/{hid}/bills/{bid}` | 成员 | 账单 + 逐人分摊 | 否 | — | 否 |
| PATCH | `/households/{hid}/bills/{bid}` | admin | `{name?,amount_cents?,incurred_on?,expected_version}` | 是 | 否 | 是 |
| POST | `/households/{hid}/bills/{bid}/void` | admin | `{reason,expected_version}` → 账单 | 是 | 是 | 是 |
| GET | `/households/{hid}/bills/{bid}/allocations` | 成员 | 分摊明细 | 否 | — | 否 |
| POST | `/households/{hid}/periods/{pid}/split-preview` | 成员 | 假设输入 → 预览分摊，不落库 | 否 | — | 否 |

`split-preview` 请求示例：

```json
{
  "rule_version_id": "可选，默认 active",
  "occupancies": [
    {"person_id": "uuid-lin", "days": 18},
    {"person_id": "uuid-zhe", "days": 30},
    {"person_id": "uuid-zhou", "days": 30}
  ],
  "bills": [
    {"category": "electricity", "name": "电费", "amount_cents": 28765},
    {"category": "water", "name": "水费", "amount_cents": 9640},
    {"category": "internet", "name": "宽带费", "amount_cents": 8900},
    {"category": "trash", "name": "垃圾清运费", "amount_cents": 2000}
  ]
}
```

响应要点：

```json
{
  "data": {
    "rule_version_id": "uuid",
    "remainder_owner_person_id": "uuid-zhou",
    "bills": [
      {
        "category": "internet",
        "amount_cents": 8900,
        "allocations": [
          {"person_id": "uuid-lin", "amount_cents": 2966, "remainder_cents": 0},
          {"person_id": "uuid-zhe", "amount_cents": 2966, "remainder_cents": 0},
          {"person_id": "uuid-zhou", "amount_cents": 2968, "remainder_cents": 2,
           "is_remainder_owner": true}
        ],
        "shares_total_cents": 8900,
        "conservation_ok": true
      }
    ],
    "person_totals": [
      {"person_id": "uuid-lin", "allocated_cents": 12494},
      {"person_id": "uuid-zhe", "allocated_cents": 18402},
      {"person_id": "uuid-zhou", "allocated_cents": 18409}
    ],
    "grand_total_cents": 49305
  }
}
```

- `preview_split` 不写任何表。
- 服务端必须对每笔账单断言 `shares_total_cents == amount_cents`。
- 前端/Agent 不允许自行用浮点重算金额。

### 2.7 规则版本

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| GET | `/households/{hid}/rule-versions` | 成员（draft 仅 admin） | 版本列表；`status=active` 可查当前 | 否 | — | 否 |
| POST | `/households/{hid}/rule-versions` | admin | `{note,remainder_owner_person_id,items[]}` → draft | 是 | 是 | 是 |
| GET | `/households/{hid}/rule-versions/{rid}` | 成员（draft 仅 admin） | 版本 + items | 否 | — | 否 |
| PATCH | `/households/{hid}/rule-versions/{rid}` | admin | 草稿 items/owner/note + `expected_row_version` | 是 | 否 | 是 |
| POST | `/households/{hid}/rule-versions/{rid}/preview` | admin | 空 → 影响预览 + preview_hash | 是（缓存预览） | 否 | 建议 |
| POST | `/households/{hid}/rule-versions/{rid}/activate` | admin | `{expected_active_version_no,expected_preview_hash,expected_row_version}` | 是 | 是 | 是 |

`items` 示例：

```json
[
  {"category": "electricity", "split_method": "days", "fallback_method": "equal_household"},
  {"category": "water", "split_method": "days", "fallback_method": "equal_household"},
  {"category": "internet", "split_method": "equal_household", "fallback_method": "equal_household"},
  {"category": "trash", "split_method": "equal_household", "fallback_method": "equal_household"},
  {"category": "other", "split_method": "equal_household", "fallback_method": "equal_household"}
]
```

预览响应：

```json
{
  "data": {
    "rule_version_id": "uuid",
    "preview_hash": "sha256-hex",
    "affected_periods": [
      {
        "period_id": "uuid",
        "period_key": "2026-10",
        "before": [{"person_id":"uuid-lin","allocated_cents":12494}],
        "after":  [{"person_id":"uuid-lin","allocated_cents":12500}],
        "delta":  [{"person_id":"uuid-lin","allocated_cents":6}]
      }
    ],
    "warnings": []
  }
}
```

- 只影响 `open` 账期；`locked/settled` 不变。
- 激活后 active 版本不可修改；修改必须新建 draft。
- 预览哈希与激活时重新计算的结果不一致 → 409。
- 不允许把零头归属人设为已停用且不在历史版本中的人员（新版本要求 active）。

### 2.8 实际收款

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| GET | `/households/{hid}/periods/{pid}/payments` | 成员 | 收款/调整流水 + 每人合计 | 否 | — | 否 |
| POST | `/households/{hid}/periods/{pid}/payments` | member 本人/admin | `{person_id,amount_cents,paid_on,method,reference?,note?}` | 是 | 是 | 是 |
| GET | `/households/{hid}/payments/{payid}` | 成员 | 单条付款 | 否 | — | 否 |
| POST | `/households/{hid}/payments/{payid}/adjustments` | admin | `{amount_cents,reason}`（负数为冲减） | 是 | 是 | 是 |

- `amount_cents` 必须为正（payment）；调整可为正/负，但绝对值不超过原付款。
- member 只能登记 `person_id` 绑定到自己账户的人员；admin 可任意。
- 付款只追加；不允许 PATCH/DELETE。
- `paid_on` 为日期；`reference` 可能含敏感信息，日志/审计脱敏。
- 已结算账期登记付款需先重开；否则 409。

### 2.9 结算

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| GET | `/households/{hid}/periods/{pid}/settlement-preview` | 成员 | 应承担/实收/差额 + preview_hash | 否 | — | 否 |
| POST | `/households/{hid}/periods/{pid}/settlements` | admin | `{preview_hash,expected_period_version,note?}` → 正式结算 | 是 | 是 | 是 |
| GET | `/households/{hid}/periods/{pid}/settlements` | 成员 | 历史版本（final/superseded） | 否 | — | 否 |
| GET | `/households/{hid}/settlements/{sid}` | 成员 | 快照 + lines | 否 | — | 否 |
| GET | `/households/{hid}/settlements/{sid}/explain` | 成员 | 某人差额解释（query `person_id`） | 否 | — | 否 |
| GET | `/households/{hid}/settlements/{sid}/export` | 成员 | `text/csv` | 否 | — | 是（导出） |

结算预览：

> 下面金额仅用于展示响应结构，不是真实收款；生产中的 `paid_cents` 必须来自用户确认的实际付款记录。

```json
{
  "data": {
    "period_id": "uuid",
    "period_version": 3,
    "rule_version_id": "uuid",
    "preview_hash": "sha256-hex",
    "bills_total_cents": 49305,
    "payments_total_cents": 49305,
    "balance_total_cents": 0,
    "lines": [
      {"person_id":"uuid-lin","allocated_cents":12494,"paid_cents":11378,
       "balance_cents":1116,"remainder_cents":0},
      {"person_id":"uuid-zhe","allocated_cents":18402,"paid_cents":18964,
       "balance_cents":-562,"remainder_cents":0},
      {"person_id":"uuid-zhou","allocated_cents":18409,"paid_cents":18963,
       "balance_cents":-554,"remainder_cents":7}
    ],
    "conservation": {
      "allocations_match_bills": true,
      "payments_match_lines": true
    }
  }
}
```

- 预览与正式结算必须使用同一纯函数和同一输入。
- 创建结算要求账期 `locked`；`open` 先锁定。
- 事务：
  - 锁账期；
  - 重算/重读；
  - 校验 preview_hash；
  - 旧 final → superseded；
  - 插入新 final + lines + 快照；
  - 账期 → settled；
  - 审计。
- 每个账期最多一个 final（partial unique index）。
- 重复提交同一 `Idempotency-Key` 返回原结算；不同 key 但已有 final 且未重开 → 409。

`explain` 响应要点：

```json
{
  "data": {
    "person_id": "uuid-lin",
    "settlement_id": "uuid",
    "allocated_cents": 12494,
    "paid_cents": 11378,
    "balance_cents": 1116,
    "components": [
      {"bill_id":"uuid","bill_name":"电费","amount_cents":28765,
       "weight_units":18,"weight_total":78,
       "base_cents":6638,"remainder_cents":0,"allocated_cents":6638},
      {"bill_id":"uuid","bill_name":"水费","amount_cents":9640,
       "weight_units":18,"weight_total":78,
       "base_cents":2224,"remainder_cents":0,"allocated_cents":2224},
      {"bill_id":"uuid","bill_name":"宽带费","amount_cents":8900,
       "weight_units":1,"weight_total":3,
       "base_cents":2966,"remainder_cents":0,"allocated_cents":2966},
      {"bill_id":"uuid","bill_name":"垃圾清运费","amount_cents":2000,
       "weight_units":1,"weight_total":3,
       "base_cents":666,"remainder_cents":0,"allocated_cents":666}
    ],
    "payments": [
      {"payment_id":"uuid","amount_cents":11378,"paid_on":"2026-10-01"}
    ],
    "explanation": "应承担 124.94 元 − 已收 113.78 元 = 需补缴 11.16 元"
  }
}
```

- `explanation` 可以展示给用户，但金额必须来自 `allocated_cents/paid_cents/balance_cents`，不能由模型自行加减。
- 解释必须引用具体账单/付款。

### 2.10 审计

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| GET | `/households/{hid}/audit-logs` | admin | 分页；筛选 actor/action/entity/from/to | 否 | — | 建议记录查看 |
| GET | `/households/{hid}/audit-logs/{id}` | admin | 单条详情 | 否 | — | 建议 |

- 返回值脱敏；`before/after` 只保留业务字段。
- 不返回密码、Token、API Key、完整聊天原文、支付参考号。
- 审计不可编辑/删除。

### 2.11 Agent

| 方法 | URL | 权限 | 请求/响应 | 事务 | 幂等 | 审计 |
|---|---|---|---|---|---|---|
| GET | `/households/{hid}/agent/conversations` | 本人 | 会话列表 | 否 | — | 否 |
| POST | `/households/{hid}/agent/conversations` | 成员 | `{title?}` → 会话 | 是 | 建议 | 否 |
| GET | `/households/{hid}/agent/conversations/{cid}` | 本人 | 会话 + 最近消息 | 否 | — | 否 |
| GET | `/households/{hid}/agent/conversations/{cid}/messages` | 本人 | 分页消息 | 否 | — | 否 |
| POST | `/households/{hid}/agent/conversations/{cid}/messages` | 本人 | `{content,client_message_id}` → 助手回复 + 工具摘要 + 待确认动作 | 是 | `client_message_id` | 是（写动作） |
| PATCH | `/households/{hid}/agent/conversations/{cid}` | 本人 | `{title?,archived?}` | 是 | 否 | 否 |
| GET | `/households/{hid}/agent/conversations/{cid}/actions` | 本人 | 本人的待确认/已处理动作 | 否 | — | 否 |
| GET | `/households/{hid}/actions/{aid}` | 本人 | 待确认动作 + 预览 | 否 | — | 否 |
| POST | `/households/{hid}/actions/{aid}/confirm` | 本人且权限足够 | `{expected_payload_hash}` + CSRF + Idempotency-Key | 是 | 是 | 是 |
| POST | `/households/{hid}/actions/{aid}/cancel` | 本人 | 空 | 是 | 否 | 是 |

消息响应示例：

```json
{
  "data": {
    "message": {
      "id": 42,
      "role": "assistant",
      "content": "已生成预览：电费改为 300.00 元后，小林需补缴 12.35 元。请确认是否应用。"
    },
    "tool_runs": [
      {"tool":"preview_split","status":"ok","duration_ms":12}
    ],
    "pending_actions": [
      {
        "id": "uuid",
        "action_type": "update_bill",
        "preview": {"before_cents":28765,"after_cents":30000,"delta_cents":1235},
        "expires_at": "2026-10-23T01:00:00Z"
      }
    ],
    "usage": {"input_tokens": 800, "output_tokens": 120}
  }
}
```

- 当前只支持非流式；超时 30 秒。后续可加 SSE。
- 模型不可用返回 503 `AGENT_UNAVAILABLE`；账务页面不受影响。
- 待确认动作不落正式账；确认接口重新校验用户、角色、账本、哈希、过期、版本。
- Agent 不能调用确认接口；确认只能来自带 CSRF 的用户请求。
- 聊天内容不写审计全文；写操作审计只记录动作摘要。

### 2.12 导出

| 方法 | URL | 权限 | 说明 |
|---|---|---|---|
| GET | `/households/{hid}/settlements/{sid}/export?format=csv` | 成员 | 导出结算明细；默认 CSV |
| GET | `/households/{hid}/periods/{pid}/export?format=csv` | 成员 | 导出账期账单/分摊/实收汇总 |

- CSV：
  - UTF-8 BOM，便于 Excel；
  - 金额输出十进制字符串 + 分列（可选）；
  - 对以 `= + - @ \t \r` 开头的单元格加 `'` 前缀，防止公式注入；
  - `Content-Disposition: attachment; filename=...`；
  - 不包含密码/账号/会话/密钥。
- v1 只做 CSV；XLSX 可选后续。

---

## 3. 关键接口详细约定

### 3.1 `POST /auth/login`

请求：

```json
{"email":"lin@example.com","password":"correct horse battery staple"}
```

成功：

```json
{
  "data": {
    "user": {"id":"uuid","email":"lin@example.com","display_name":"小林"},
    "households": [
      {"id":"uuid","name":"望京 3 号房","role":"admin"}
    ],
    "csrf_token": "opaque"
  }
}
```

错误：

- `401 INVALID_CREDENTIALS`：统一文案，不暴露邮箱。
- `423 ACCOUNT_LOCKED`：带 `Retry-After`。
- `429 RATE_LIMITED`。

### 3.2 `GET /households/{hid}/ledger/current`

响应：

```json
{
  "data": {
    "household": {"id":"uuid","name":"望京 3 号房","timezone":"Asia/Shanghai"},
    "period": {
      "id":"uuid","period_key":"2026-10","status":"open","version":2,
      "starts_on":"2026-10-01","ends_on":"2026-10-31"
    },
    "people": [{"id":"uuid","slug":"lin","display_name":"小林"}],
    "rule": {"id":"uuid","version_no":3,"remainder_owner_person_id":"uuid-zhou"},
    "bills_total_cents": 49305,
    "payments_total_cents": 49305,
    "allocated_total_cents": 49305,
    "balances": [
      {"person_id":"uuid-lin","balance_cents":1116},
      {"person_id":"uuid-zhe","balance_cents":-562},
      {"person_id":"uuid-zhou","balance_cents":-554}
    ]
  }
}
```

- Agent 的 `get_current_ledger` 使用此接口/服务。
- `household_id` 来自路径，必须与当前用户成员关系匹配。
- 若无当前账期，返回 `period: null`，不自动创建。

### 3.3 `POST /households/{hid}/periods/{pid}/settlements`

请求：

```json
{
  "preview_hash": "sha256-hex",
  "expected_period_version": 3,
  "note": "2026 年 10 月结算"
}
```

成功 `201`：

```json
{
  "data": {
    "settlement": {
      "id":"uuid","period_id":"uuid","revision":1,"status":"final",
      "bills_total_cents":49305,"payments_total_cents":49305,
      "balance_total_cents":0,
      "rule_version_id":"uuid","created_at":"2026-10-23T01:00:00Z"
    },
    "lines": [
      {"person_id":"uuid-lin","allocated_cents":12494,"paid_cents":11378,"balance_cents":1116},
      {"person_id":"uuid-zhe","allocated_cents":18402,"paid_cents":18964,"balance_cents":-562},
      {"person_id":"uuid-zhou","allocated_cents":18409,"paid_cents":18963,"balance_cents":-554}
    ]
  }
}
```

- 幂等键必填。
- 预览哈希/账期版本不匹配 → 409。
- 账期未锁定 → 409。
- 已有 final 且未重开 → 409（或幂等重放）。
- 事务内更新旧 final 为 superseded。

### 3.4 `POST /households/{hid}/actions/{aid}/confirm`

请求：

```json
{"expected_payload_hash":"sha256-hex"}
```

- 必须带 CSRF、Idempotency-Key。
- 服务端：
  1. 校验动作属于当前用户/账本；
  2. 校验未过期、未消费；
  3. 校验 `payload_hash`；
  4. 重新校验用户角色；
  5. 校验底层资源版本；
  6. 执行领域服务；
  7. 标记 `confirmed/consumed`；
  8. 审计。
- 任何一步失败 → 回滚，动作仍可按情况重试或标记失败。
- 模型不能直接调用此端点。

### 3.5 `GET /health/ready`

- 200：`{"status":"ok"}`
- 503：`{"status":"unavailable"}`
- 不返回数据库版本、DSN、异常堆栈、迁移状态、密钥是否存在。
- 详细原因只写服务端日志。

---

## 4. API 与 Agent 工具映射

| Agent 工具 | 服务/接口 |
|---|---|
| `get_current_ledger` | `GET /households/{hid}/ledger/current` |
| `get_billing_period` | `GET /households/{hid}/periods/{pid}`；工具层可按 `period_key`/`relative_period` 解析 |
| `preview_split` | `POST /households/{hid}/periods/{pid}/split-preview` |
| `create_bill`（补充工具） | 写工具只创建 pending action；确认后调 `POST /households/{hid}/periods/{pid}/bills` |
| `update_bill`（补充工具） | 写工具只创建 pending action；确认后调 `PATCH /households/{hid}/bills/{bid}` |
| `void_bill`（补充工具） | 写工具只创建 pending action；确认后调 `POST /households/{hid}/bills/{bid}/void` |
| `set_occupancies`（补充工具） | 写工具只创建 pending action；确认后调 `PUT /households/{hid}/periods/{pid}/occupancies` |
| `explain_settlement` | `GET /households/{hid}/settlements/{sid}/explain` |
| `propose_rule_change` | 创建 draft：`POST /households/{hid}/rule-versions` + `POST /rule-versions/{rid}/preview` |
| `confirm_rule_change` | 不暴露给模型；由 `POST /actions/{aid}/confirm` 调 `POST /rule-versions/{rid}/activate` |
| `record_payment` | 写工具只创建 pending action；确认后调 `POST /households/{hid}/periods/{pid}/payments` |
| `create_settlement` | 写工具只创建 pending action；确认后调 `POST /households/{hid}/periods/{pid}/settlements` |
| `get_settlement_history` | `GET /households/{hid}/periods/{pid}/settlements` |
| `export_settlement` | `GET /households/{hid}/settlements/{sid}/export` |

---

## 5. 版本管理与兼容性

- `/api/v1` 内允许加字段；不允许改字段语义/删除字段。
- 破坏性变更发布 `/api/v2`，v1 至少保留一个发布周期。
- OpenAPI 文档：
  - 开发环境 `/api/docs`；
  - 生产默认关闭或仅内网/管理员可访问；
  - schema 不包含示例密钥。
- 所有错误码作为稳定契约；新增错误码需文档化。
- 前端对未知字段忽略；对未知错误码显示通用错误 + request_id。

---

## 6. API 验收标准

- [ ] 所有写接口有权限校验、CSRF、参数校验、审计。
- [ ] 财务写接口有幂等键。
- [ ] 未登录访问受保护数据返回 401。
- [ ] 跨账本访问返回 404/403，且测试覆盖。
- [ ] 普通成员不能执行管理员操作。
- [ ] 非法参数不产生数据库写入。
- [ ] 健康检查不泄露配置。
- [ ] 版本冲突返回 409，不静默覆盖。
- [ ] 结算/付款重复提交不重复落账。
- [ ] API 文档与实际测试一致。
