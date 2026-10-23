# 测试方案与验收矩阵

- 状态：**阶段 0–6 测试、阶段 7 备份恢复/静态部署/安全扫描/Docker build/run（QEMU）已实际运行**；Compose/Caddy 容器编排、GitHub Actions 尚未执行。
- 目标：覆盖分摊正确性、历史不可变、多用户隔离、Agent 受控、部署与恢复。
- 原则：能用纯函数测的，不依赖数据库；必须测数据库事务的，用真实 PostgreSQL，不用 SQLite 替代。

---

## 1. 测试分层

| 层 | 工具 | 内容 | 是否依赖 DB |
|---|---|---|---|
| 单元 | pytest | 金额解析、整数分摊、守恒、规则映射、权限判定、CSV 转义 | 否 |
| 属性 | Hypothesis | 随机金额/权重/人数下的守恒、整数、确定性、边界 | 否 |
| 集成 | pytest + httpx/TestClient | 登录、CRUD、事务、锁、幂等、审计、隔离、结算 | 是（PostgreSQL 16） |
| Agent | pytest + FakeProvider | 工具循环、缺参、确认、提示注入、模型失败 | 是（业务工具） |
| 前端 | Playwright（可选） | 登录、账期切换、聊天、确认按钮、错误提示 | 是 |
| 部署 | shell/pytest | 空库迁移、容器重启、备份恢复、README 冒烟 | 是 |
| 安全 | pytest + gitleaks + pip-audit | 越权、CSRF、XSS、SQLi、密钥扫描 | 部分 |

### 1.1 测试数据库

- PostgreSQL 16 容器/服务，数据库名 `roommate_test`。
- 每个测试会话：
  - 创建独立 schema 或数据库；
  - `alembic upgrade head`；
  - 测试结束回滚/销毁。
- 不用 SQLite，因为：
  - JSONB、部分唯一索引、复合外键、行锁行为不同；
  - 并发/事务测试必须在目标数据库跑。
- 测试事务：
  - 大多数测试用外层事务回滚；
  - 并发/提交测试使用独立连接和真实提交。
- 测试数据使用 factory，不引用真实账单/真实姓名。

### 1.2 覆盖率

- 目标不是追求 100%，而是：
  - `domain/allocation.py`、`services/*` 关键路径 ≥ 90%；
  - 整体 ≥ 80%；
  - 所有错误码/权限分支至少一个测试。
- CI 输出覆盖率报告，但不仅以数字作为门禁；关键业务测试必须显式命名。

---

## 2. 阶段 0 已执行结果

### 2.1 旧版审计

命令：

```bash
node docs/audits/legacy-split-audit.mjs
```

结果：

- 14/14 审计探针通过；
- 复现初始新规则分摊、旧规则基线、差额；
- 记录 8 个结构性缺陷和 3 个边界观察（`1.005` 解析、负金额未拒绝、大额浮点误差）；
- 结果文件：`docs/audits/legacy-split-audit-results.json`。

### 2.2 已确认事实

- 默认新规则个人合计：12494 / 18402 / 18409 分；总额 49305 分。
- 默认旧基线：11378 / 18964 / 18963 分。
- 默认差额：+1116 / −562 / −554 分。
- 旧基线是自动估算，不是真实收款。
- 旧算法小额守恒通过，但大额浮点误差存在。

### 2.3 尚未执行

- 真实登录/CSRF、Agent、前端 E2E、Docker、CI、备份恢复：**尚未执行**。
- Docker 在当前环境不可用；阶段 3 使用本地 PostgreSQL 16 完成集成测试。

### 2.4 阶段 2 已执行结果

- Python 3.12.14、pytest 9.1.1、Hypothesis 6.170.5、ruff 0.17.1。
- `pytest -q`：**79 passed**（7.19s，含 5000 + 1000 组 Hypothesis 样例）。
- `ruff check .`：通过。
- `ruff format --check .`：22 个文件已格式化。
- `uv sync --frozen --extra dev` 可复现依赖安装。
- 实测样例：电费 `6638/11063/11064`，水费 `2224/3707/3709`，宽带 `2966/2966/2968`，垃圾 `666/666/668`。
- 详细报告：[phase-2-report.md](phase-2-report.md)。

### 2.5 阶段 3 已执行结果

- PostgreSQL 16.15；Alembic `82f2f551741e`。
- 全量：**129 passed**（35.44s；带 coverage 47.09s）。
- 覆盖率：**91%**（1910 statements，173 missed）。
- `ruff check .` / `ruff format --check .`：通过，80 个文件已格式化。
- 集成测试覆盖：迁移/触发器、账单守恒、入住天数重算、规则预览/激活、付款幂等/调整、结算快照/修订/并发、跨账本、越权、导出。
- 详细报告：[phase-3-report.md](phase-3-report.md)。

### 2.6 阶段 4 已执行结果

- Alembic `bc8299ee45ed`（auth_sessions、household_invites）。
- 全量：**140 passed**（45.48s；带 coverage 56.74s）。
- 覆盖率：**89%**（2435 statements，276 missed）。
- `ruff check .` / `ruff format --check .`：通过，93 个文件已格式化。
- 认证测试覆盖：登录、错误密码、5 次失败锁定、423、Cookie、CSRF、CSRF 轮换、过期、登出、改密吊销、Origin、邀请、多账本切换、角色更新、审计权限、注册关闭。
- 详细报告：[phase-4-report.md](phase-4-report.md)。

### 2.7 阶段 5 已执行结果

- Alembic `f9d42243af3a`（agent_conversations、agent_messages、pending_actions）。
- 全量：**157 passed**（52.58s；带 coverage 70.01s）。
- 覆盖率：**88%**（3143 statements，365 missed）。
- `ruff check .` / `ruff format --check .`：通过，108 个文件已格式化。
- Agent 覆盖：工具白名单、读工具、写工具 pending、确认哈希、确认幂等、取消、过期、权限、模型禁用/失败降级、最大步数、重复消息、会话隔离、OpenAI-compatible HTTP mock、规则/结算/付款/账单/入住天数动作。
- 详细报告：[phase-5-report.md](phase-5-report.md)。

### 2.8 阶段 6 已执行结果

- 全量后端 + 静态契约：**160 passed**（57.00s；带 coverage 71.78s）。
- 覆盖率：**88%**（3175 statements，366 missed）。
- `ruff check .` / `ruff format --check .`：通过，111 个文件已格式化。
- 前端纯函数：`node --test web/tests/format.test.mjs`，**5 passed**。
- 静态契约：`/` 200、CSP/安全头、无内联脚本/样式/事件、assets 200、`/docs` 不被 CSP 阻断。
- 浏览器 E2E（真实 Chrome）：登录、旧 DOM 12 cell/4 bill-total/3 person-total、初始 493.05、规则草稿/激活 v2、新增账单 503.05、实收、锁定、结算、CSV 182 bytes、审计、Agent 禁用降级、无异常。
- 移动端 390px：`scrollWidth=390`，页面无横向溢出。
- 详细报告：[phase-6-report.md](phase-6-report.md)。

### 2.9 阶段 7 已执行结果

- 备份恢复：`pg_dump -Fc` + SHA-256 → `pg_restore` 到独立库；20 张表行数一致；`bill_cents=49305`、`payment_cents=12000`、`audit_logs=9`；恢复库 `/health/ready` 200。
- 部署静态验证：`docker compose config` prod/dev 均 0；Caddy 2.11.7 `validate` 通过；hadolint 2.15.1 exit 0；actionlint 1.7.12 CI workflow exit 0。
- `uv build` 成功生成 wheel/sdist；wheel 内含 `LICENSE`/`NOTICE` 与 MIT 元数据。
- Caddy 本机内部 CA 实跑：`https://localhost:8443/health/ready` 200、`/` 200、`/api/v1/meta` 200，HTTP 8080→8443 301。
- 安全：`pip-audit 2.10.1` 未发现第三方依赖已知漏洞；CSP/安全头测试通过。
- 已执行：Docker build/run（QEMU/boot2docker）、Caddy 本地 TLS。
- 未执行：Compose/Caddy 容器编排、公网 ACME、GitHub Actions。
- 详细报告：[phase-7-report.md](phase-7-report.md)、[backup-restore.md](backup-restore.md)、[security-review.md](security-review.md)。

---

## 3. 分摊算法测试

文件：`tests/unit/test_allocation.py`、`tests/unit/test_money.py`。

### 3.1 必测用例

| ID | 场景 | 期望 |
|---|---|---|
| AL-01 | 正常入住天数 18/30/30，金额 28765 | `[6638,11063,11064]`，合计 28765 |
| AL-02 | 按户平摊 8900，三人 | `[2966,2966,2968]`，合计 8900 |
| AL-03 | 零头归小周 | 只有 owner 的 `remainder_cents>0`，合计守恒 |
| AL-04 | 总额为 0 | 全 0，长度/人员不变 |
| AL-05 | 权重全为 0，显式 fallback | 按 fallback（均分）分配，合计守恒 |
| AL-06 | 主权重全 0，未提供 fallback | 使用默认显式 fallback（均分），不出现 NaN |
| AL-07 | 权重含 NaN/负数/字符串 | API 拒绝（422）；domain 层抛 `InvalidWeightError`，不静默当 0 |
| AL-08 | 负金额（引擎级） | 保持符号，合计等于负总额；API 普通账单拒绝负数 |
| AL-09 | 单笔金额上限 | 上限内正常；超上限 422 |
| AL-10 | 单笔金额为 0 | 允许，全 0；不产生 NaN/丢失（产品如需拒绝，另改） |
| AL-11 | 人数 1 | 全额给唯一人 |
| AL-12 | 人数 0/空列表 | 明确错误，不返回空合计“成功” |
| AL-13 | 多笔账单合计 | 每笔守恒，个人合计等于逐笔之和 |
| AL-14 | 同一输入重复计算 | 结果完全一致（确定性） |
| AL-15 | 每笔账单分摊总额 | `sum(shares) == total_cents` |
| AL-16 | 零头总额 | `sum(remainder_cents) == total_cents - sum(base_cents)`，且 < 人数 |
| AL-17 | owner 非法/离职 | 新规则版本校验；历史版本保留原归属；不静默换人 |
| AL-18 | 大额整数分 | 10 亿元上限内守恒；不出现浮点误差 |
| AL-19 | 含 0 天成员 | 该人 0；其他人按剩余权重；总量守恒 |
| AL-20 | 全部成员 0 天 | 走显式 fallback，不 NaN |

### 3.2 属性测试（Hypothesis）

- 随机 `n=1..20`，随机金额 `0..100_000_000_000` 分。
- 随机权重：
  - 0；
  - 正整数；
  - 极端大数；
  - 缺失；
  - 非法类型（在 API 层应被拒）。
- 断言：
  - 返回长度 = n；
  - 每项 `int`；
  - `sum == total`；
  - 无负零/NaN；
  - 同输入结果一致；
  - owner 分得全部余数（owner 模式）；
  - 非 owner 的 remainder 为 0（owner 模式）。
- 对旧版 `spread` 只保留迁移对照测试，不作为新规则。

### 3.3 金额解析

- `"287.65"` → `28765`；
- `"0.01"` → `1`；
- `"1.005"` → API 拒绝（超过 2 位小数），不得静默取整；
- `"-1.00"` → 普通账单拒绝；
- `"1e3"` → 拒绝或明确支持（建议拒绝）；
- 空、空白、`NaN`、`Infinity`、超长 → 422；
- 金额上限；
- 不用二进制浮点做乘法。

### 3.4 与旧版对照

- 固定样例 89.00 按户 → `[2966,2966,2968]`；
- 固定样例 287.65 按天 → `[6638,11063,11064]`；
- 旧基线计算只用于迁移文档，不进入生产 service。

---

## 4. 历史账目测试

文件：`tests/integration/test_settlements.py`、`test_payments.py`、`test_rules.py`。

| ID | 场景 | 期望 |
|---|---|---|
| HI-01 | 规则变更后历史付款 | `payments` 金额/记录不变 |
| HI-02 | 正式结算保存规则版本 | `settlement.rule_version_id` 指向当时 active；快照可读 |
| HI-03 | 历史实收与新应承担 | `balance = allocated - paid`，逐人正确 |
| HI-04 | 修正历史付款 | 原付款保留；新增 adjustment；合计正确 |
| HI-05 | 重复创建结算 | 同幂等键返回原结算；不同 key 但已有 final → 409（未重开） |
| HI-06 | 并发创建结算 | 只产生一个 final；另一个 409/重放 |
| HI-07 | 结算后改账单 | 拒绝；需重开，生成新 revision |
| HI-08 | 重开后修正 | 旧 final → superseded；新 final 可查；旧行不变 |
| HI-09 | 规则版本归档 | 历史结算仍能读取原版本快照 |
| HI-10 | 付款/结算不可改 | DB 触发器/服务层拒绝 UPDATE/DELETE |
| HI-11 | 结算行合计 | `SUM(allocated)=bills_total`，`SUM(paid)=payments_total` |
| HI-12 | 预览与正式结果 | 同一输入下完全一致（哈希/金额） |
| HI-13 | 结算后新增付款 | 拒绝；需调整/重开流程 |
| HI-14 | 旧自动基线 | 不写入 payments；只作为说明/测试夹具 |

### 4.1 并发测试

- 两个线程/连接同时：
  - 创建同一账期结算；
  - 同一账单更新；
  - 同一付款确认；
  - 规则激活。
- 断言：
  - 只有一个成功或一个幂等重放；
  - 不产生重复 final；
  - 版本冲突返回 409；
  - 审计记录完整。

### 4.2 事务测试

- 在账单插入后、分摊插入前抛异常 → 账单不落库；
- 结算插入后、审计前抛异常 → 全回滚；
- 规则激活中途失败 → 旧 active 不变；
- 付款调整越界 → 回滚；
- 幂等记录与业务写入同一事务/补偿策略一致。

---

## 5. 多用户、权限与隔离测试

文件：`tests/integration/test_auth.py`、`test_isolation.py`、`test_permissions.py`。

| ID | 场景 | 期望 |
|---|---|---|
| AU-01 | 未登录访问账本 | 401 |
| AU-02 | 错误密码 | 401，统一文案 |
| AU-03 | 连续失败 | 锁定/429 |
| AU-04 | 会话过期 | 401 |
| AU-05 | 改密 | 旧会话失效 |
| AU-06 | Cookie 属性 | HttpOnly/Secure/SameSite/Path 正确 |
| AU-07 | CSRF 缺失/错误 | 403 |
| AU-08 | 跨站 Origin | 403 |
| AU-09 | member 调 admin 接口 | 403 |
| AU-10 | owner 移除最后 owner | 400/409 |
| AU-11 | A 账本访问 B 的账单/付款/结算/规则/审计 | 404/403 |
| AU-12 | 请求体伪造 household_id | 被忽略/拒绝 |
| AU-13 | 跨账本复合外键 | 数据库拒绝 |
| AU-14 | Agent 工具跨账本 | 拒绝 |
| AU-15 | 非法参数（负数/超长/坏日期） | 422，无写入 |
| AU-16 | 重复确认动作 | 幂等/409，不重复写 |
| AU-17 | 角色被降级后确认旧动作 | 403 |
| AU-18 | 审计查看权限 | 仅 admin |

### 5.1 权限矩阵测试

对每个写端点至少测试：

- owner 成功；
- admin 成功/按矩阵；
- member 403；
- 未登录 401；
- 跨账本 404。

### 5.2 数据隔离测试

- 用账本 B 的所有实体 ID 遍历账本 A 的每个 GET/PATCH/DELETE/POST；
- 验证响应不包含 B 的名称/金额；
- 验证列表接口不泄露 B 的行；
- 验证导出不包含 B。

---

## 6. Agent 测试

文件：`tests/agent/*`，使用 `FakeProvider`，不调用真实模型。

| ID | 场景 | 期望 |
|---|---|---|
| AG-01 | 录入电费 287.65 | 调用 `get_current_ledger` + `preview_split` + `create_bill`（准备） |
| AG-02 | 缺少金额 | 追问，不调用写工具 |
| AG-03 | 缺少人员映射 | 追问，不猜 |
| AG-04 | 只调用白名单工具 | 未知工具拒绝 |
| AG-05 | 写工具 | 只创建 pending_action，不落正式账 |
| AG-06 | 未确认 | 账单/付款/结算数量不变 |
| AG-07 | 确认后 | 只写一次；重复确认幂等 |
| AG-08 | 规则变更 | 先 draft + preview；未确认不 active |
| AG-09 | 模型失败 | 核心账务 API 仍可用 |
| AG-10 | 解释金额 | 与 `explain_settlement` 返回一致 |
| AG-11 | 模型输出错误金额 | 前端以工具结果为准；测试记录 |
| AG-12 | 提示注入 | 不执行越权/不改规则 |
| AG-13 | 调用确认工具 | 模型 tools 列表无该工具；拒绝 |
| AG-14 | 多步超限 | 达到 `AGENT_MAX_STEPS` 后停止，不继续 |
| AG-15 | 非法 JSON/工具参数 | 不执行；返回错误 |
| AG-16 | 历史实收缺失 | 追问，不用自动基线填充 |
| AG-17 | 上个月 | 服务端解析，不让模型算日期 |
| AG-18 | 导出未结算 | 提示先生成结算 |

### 6.1 FakeProvider 设计

- 脚本化返回：
  - 文本；
  - 一个/多个工具调用；
  - 非法参数；
  - 异常；
  - 超时。
- 记录调用顺序，断言模型只看到允许的工具。
- 不依赖外网、不消耗 token。

### 6.2 金额一致性测试

- 读取工具返回的 `amount_cents`/`display`；
- 断言助手消息中的关键金额与工具结果一致；
- 对差额 `balance_cents` 做逐人核对；
- 禁止模型输出中出现未由工具返回的金额（可用固定脚本/正则做辅助断言，避免过度脆弱）。

---

## 7. 前端与端到端测试

### 7.1 前端单元（可选）

- 金额格式化/解析；
- 错误码到文案；
- 状态 store 的 reducer；
- 确认卡片的状态机。

### 7.2 Playwright 冒烟（建议阶段 7）

| ID | 场景 |
|---|---|
| E2E-01 | 登录 → 选择账本 → 看到账期 |
| E2E-02 | 修改预览（不保存）→ 取消 |
| E2E-03 | 新增账单 → 预览 → 确认 → 刷新后仍在 |
| E2E-04 | 修改规则 → 预览 → 未确认不生效 |
| E2E-05 | 登记付款 → 确认 → 历史记录出现 |
| E2E-06 | 锁定 → 结算 → 历史结算可查 |
| E2E-07 | 未登录访问 → 跳登录 |
| E2E-08 | 网络错误 → 提示 + 重试，不丢表单 |
| E2E-09 | Agent 聊天 → 预览卡片 → 点击确认 |
| E2E-10 | 调用旧 DOM `data-testid` 的回归检查 |

- 只保留 8–10 个关键路径，避免 E2E 维护成本过高。
- 使用测试数据库和固定种子，不接触真实数据。

---

## 8. 部署与恢复测试

| ID | 场景 | 期望 |
|---|---|---|
| DP-01 | 空 Postgres + `alembic upgrade head` | 成功，无手工 DDL |
| DP-02 | 按 README 全新环境启动 | 服务健康，能登录 |
| DP-03 | 容器重启 | 数据仍在（命名卷） |
| DP-04 | `docker compose down`（不删卷） | 数据保留 |
| DP-05 | 备份 → 新库恢复 | 行数/合计/登录验证通过 |
| DP-06 | 恢复后迁移 | 可升级到 head |
| DP-07 | GitHub Actions | lint + 迁移 + 测试通过 |
| DP-08 | 健康检查 | 不泄露配置 |
| DP-09 | 反向代理 HTTPS | 证书/跳转/HSTS 正确 |
| DP-10 | 非 root/只读容器 | 启动/运行正常 |

> 当前环境没有 Docker；这些测试在阶段 7 执行，未执行前不写“已通过”。

### 8.1 备份恢复验证 SQL（示例）

- 每个账单：`SUM(bill_allocations.amount_cents) = bills.amount_cents`；
- 每个结算：`SUM(settlement_lines.allocated_cents) = settlements.bills_total_cents`；
- 每个结算：`SUM(settlement_lines.paid_cents) = settlements.payments_total_cents`；
- 每个账期 final 数 ≤ 1；
- 跨账本外键计数 = 0；
- 关键表行数与备份清单一致。

---

## 9. 安全测试

| ID | 场景 | 期望 |
|---|---|---|
| SE-01 | 无 CSRF 写 | 403 |
| SE-02 | 跨站 Origin | 403 |
| SE-03 | 存储型 XSS（姓名/备注/聊天） | 不执行，纯文本 |
| SE-04 | SQL 注入（搜索/排序） | 参数化/白名单 |
| SE-05 | IDOR | 404/403 |
| SE-06 | 暴力登录 | 锁定/429 |
| SE-07 | 越权 Agent | 拒绝 |
| SE-08 | 提示注入 | 不写/不改规则 |
| SE-09 | 日志/secrets | 不含密钥/Token/密码 |
| SE-10 | 健康检查 | 不泄露配置 |
| SE-11 | CSV 公式注入 | 前缀转义 |
| SE-12 | 依赖漏洞 | pip-audit 通过/有记录 |
| SE-13 | 密钥扫描 | gitleaks 通过 |

---

## 10. CI 设计（阶段 7 落地）

```yaml
# 规划，不是已运行配置
jobs:
  test:
    services:
      postgres:
        image: postgres:16
        env: ...
    steps:
      - checkout
      - setup Python 3.12
      - install uv
      - uv sync --frozen --extra dev
      - alembic upgrade head
      - ruff check .
      - ruff format --check .
      - pytest --cov ...
      - pip-audit
      - gitleaks
```

- 所有 action 固定版本；`permissions: contents: read`。
- 测试失败阻断合并。
- 不在日志打印 `.env`/secrets。
- 可选 nightly：备份恢复、依赖审计、容器扫描。

---

## 11. 测试数据与隐私

- 使用虚构姓名/金额；不使用真实账单、真实手机号、真实收款账号。
- 示例数据：
  - 人员 `lin/zhe/zhou`；
  - 金额 287.65/96.40/89.00/20.00；
  - 18/30/30 天。
- 明确标注“演示数据，不代表真实收款”。
- 测试夹具中的密码是测试专用，不得用于生产。
- 备份/测试输出不得包含真实用户数据。

---

## 12. 阶段 2–8 测试门禁

| 阶段 | 必须通过 |
|---|---|
| 2 分摊引擎 | AL-01..20、属性测试、金额解析、无浮点 |
| 3 数据库/账单/付款/结算 | 迁移、HI-01..14、事务、幂等、结算并发 |
| 4 登录/权限/审计 | AU-01..18、隔离、CSRF、审计 |
| 5 Agent | AG-01..18、提示注入、模型失败、确认 |
| 6 前端 | 关键 E2E、旧 data-testid 回归、错误提示 |
| 7 部署/CI/恢复 | DP-01..10、备份恢复、CI 绿 |
| 8 文档/发布 | README 命令实际验证、无 secrets、许可证确认 |

---

## 13. 测试验收定义

- 不以“测试数量”代替“关键行为覆盖”。
- 每个失败必须能定位到具体业务规则。
- 测试输出保留：
  - 命令；
  - 环境（Python/Postgres 版本）；
  - 结果；
  - 失败日志；
  - 修复提交。
- 任何“已通过”的表述必须有可复现命令和输出。
- 当前阶段只确认阶段 0 审计结果；其余标注“计划”。
