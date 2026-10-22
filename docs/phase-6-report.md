# 阶段 6 报告：前端改造、旧 DOM 契约与浏览器 E2E

- 状态：**阶段 6 核心已完成，等待验收后进入阶段 7（Docker/CI/备份恢复）**。
- 前端：原生 ES modules + 外部 CSS，无构建步骤、无内联脚本/样式。
- 服务端：FastAPI 同源托管 `/`、`/assets`，并设置 CSP 与安全头。
- 未包含：Docker/Caddy/CI、真实模型 Key、生产域名。

---

## 1. 目标

1. 登录与真实 Session/CSRF；
2. 多账本选择、账期/账单/入住/规则/实收/结算/导出/审计；
3. Agent 会话与 pending action 确认卡片；
4. 保留旧版视觉语言与 `data-testid`；
5. 通过严格 CSP；
6. 真实浏览器 E2E 与移动端宽度验证。

---

## 2. 页面结构

```text
/
├── 登录
└── 账本控制台
    ├── 总览（旧版 01–05 区块）
    ├── 账单
    ├── 入住
    ├── 规则
    ├── 实收
    ├── 结算 / CSV
    ├── 成员 / 邀请
    ├── 审计
    └── Agent
```

### 2.1 旧版 DOM 契约保留

- `main[data-testid="app"]`
- `[data-testid="days-input"][data-person=…]`
- `[data-testid="amount-input"][data-bill=…]`
- `[data-testid="cell"][data-bill][data-person][data-cents]`
- `[data-testid="bill-total"]`
- `[data-testid="person-total"]`
- `[data-testid="paid-total"]`
- `[data-testid="new-total"]`
- `[data-testid="balance"]`
- `[data-testid="balance-label"]`
- `[data-testid="grand-total"]`
- `#balance-check`
- `[data-testid="notes"]`
- `[data-testid="generated-at"]`
- `#status`

旧 ID：`days-lin`、`days-zhe`、`days-zhou`、`amount-electric`、`amount-water`、`amount-internet`、`amount-trash` 由 slug/category 映射动态生成。

金额输出同时保留 `data-cents` 整数分；`#balance-check` 使用 `positive/negative/zero` class，不使用内联 style。

### 2.2 新增测试标记

`household-select`、`period-select`、`nav-*`、`login-*`、`bill-create-submit`、`agent-send`。

---

## 3. 前端实现

### 3.1 无构建 ES modules

```text
web/
├── index.html
├── package.json                 # only type=module + node test script
├── assets/
│   ├── app.css
│   └── js/
│       ├── api.js               # Cookie/CSRF/账本头/幂等键
│       ├── app.js               # 状态、渲染、表单、Agent
│       ├── dom.js               # 无 innerHTML 的 DOM 构建
│       ├── format.js            # 整数分/标签/日期
│       └── store.js
└── tests/format.test.mjs
```

- 所有金额输入用 `parseYuanToCents` 转整数分；
- 所有输出用 `formatCents`；
- 不使用 `innerHTML`；
- 不使用内联事件处理器；
- 不使用 `eval/new Function`；
- API 401 自动回登录；
- 写操作自动带 CSRF；
- 财务写操作带 `Idempotency-Key`；
- `X-Household-ID` 由当前选择注入。

### 3.2 账本/账期/账单

- 多账本下拉框；
- 新建账本；
- 账期选择、创建、锁定、重开；
- 入住天数 0–31 保存；
- 账单新增、金额修改、名称修改、作废；
- 账单分摊矩阵与个人合计；
- 实收与差额；
- 所有数据来自服务端，前端不自行分摊。

### 3.3 规则

- 当前生效规则；
- 5 个分类的 split_method 选择；
- 零头归属人；
- 保存草稿 → 预览 → 确认激活；
- 版本历史；
- 激活使用 preview_hash/row_version；
- 模型不能确认，前端由用户点击。

### 3.4 实收/结算/导出

- 登记实收；
- 结算预览；
- 锁定后才能创建正式结算；
- 已有 final 时创建新修订需确认；
- 结算历史；
- CSV 下载（Cookie + 账本头）。

### 3.5 成员/审计

- 成员列表；
- owner 修改 admin/member 与 active/left；
- 人员创建；
- 邀请创建，token 只显示一次；
- 审计日志管理员可见。

### 3.6 Agent

- 会话列表、创建、消息；
- 待确认动作卡片显示 preview；
- 确认/取消按钮；
- 规则确认工具不在模型工具列表；
- 模型禁用时显示错误，核心账务页面仍可用。

---

## 4. 服务端托管与安全头

`main.py`：

- `GET /` → `web/index.html`；
- `/assets` → StaticFiles；
- `GET /favicon.ico` → 204；
- 同源 CSP：

```text
default-src 'self'; script-src 'self'; style-src 'self';
img-src 'self' data:; font-src 'self'; connect-src 'self';
object-src 'none'; base-uri 'none'; form-action 'self';
frame-ancestors 'none'
```

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Cross-Origin-Opener-Policy: same-origin`
- `/docs`/`/redoc`/`/openapi.json` 不注入 CSP，避免破坏 Swagger UI；
- HSTS 在阶段 7 的 HTTPS/Caddy 环境启用。

---

## 5. 测试结果

### 5.1 后端 + 前端静态契约

```text
160 passed, 1 warning in 57.00s
coverage: 88% (3175 statements, 366 missed)
ruff check: All checks passed
ruff format --check: 111 files formatted
alembic check: No new upgrade operations detected
Alembic: f9d42243af3a (head)
OpenAPI: 47 paths
```

带覆盖率耗时 71.78s。

### 5.2 前端纯函数

```text
node --test web/tests/format.test.mjs
5 tests passed
```

覆盖金额格式化、严格元→分、整数分输入、旧 data-bill 映射、差额标签。

### 5.3 浏览器 E2E（真实 Chrome）

脚本：`scripts/e2e_frontend.mjs`；演示数据：`scripts/seed_demo.py`。

实际结果：

```text
initial:
  cells=12, billTotals=4, personTotals=3,
  grand=¥493.05, days=3, amounts=4
actions:
  规则草稿 → 激活 v2
  新增 10.00 账单 → grand=¥503.05
  登记 50.00 实收
  锁定账期 → 生成正式结算
  CSV 导出 182 bytes
  审计表有记录
  Agent 禁用 → 显示“Agent 未启用”
final:
  cells=15, grand=¥503.05, error="", exceptions=[]
```

- 无浏览器异常；
- 桌面截图：1350×2471（总览全页）；
- 移动端 390px：`scrollWidth=390`，无页面横向溢出；导航自身横向滚动。

截图（运行时产物，不提交仓库）：

- `_runtime/stage6-dashboard-final.png`
- `_runtime/stage6-mobile.png`

---

## 6. 已知限制

1. **没有 Docker/Caddy/CI/备份恢复**：阶段 7。
2. **没有真实模型 Key**：Agent 页面在未启用时只能验证降级；pending action 的 UI 确认未在真实模型流中端到端跑过（后端 FakeProvider 已测试）。
3. **邀请接受/密码修改**：阶段 8 已补账户对话框；后端测试已覆盖。
4. **新账本初始化是手动流程**：新建账本 → 添加人员 → 规则草稿/激活 → 创建账期；没有一步向导。
5. **只验证 Chrome**：未跑 Firefox/Safari。
6. **没有完整无障碍审计**：有 label、aria-live、键盘可操作，但没有 axe/WCAG 全量。
7. **没有前端打包/版本哈希**：原生 ES modules；阶段 7 可加缓存指纹。
8. **CSV 下载依赖浏览器 Cookie**；无服务端签名 URL。
9. **TestClient/httpx 弃用 warning** 仍存在。

---

## 7. 文件清单

```text
web/index.html
web/assets/app.css
web/assets/js/api.js
web/assets/js/app.js
web/assets/js/dom.js
web/assets/js/format.js
web/assets/js/store.js
web/package.json
web/tests/format.test.mjs
src/roommate_billing/main.py
tests/integration/test_web.py
scripts/seed_demo.py
scripts/e2e_frontend.mjs
```

---

## 8. 阶段 7 开始条件

- 用户验收本报告；
- 确认 Docker/Caddy 端口与域名策略；
- 确认备份路径/保留策略；
- 许可证仍待选择，不影响开发。

阶段 7 不会自动开始，等待用户确认。
