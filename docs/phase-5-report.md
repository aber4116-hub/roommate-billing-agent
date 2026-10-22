# 阶段 5 报告：Agent、模型适配、工具网关与确认流程

- 状态：**阶段 5 核心已完成；后续阶段 6 前端已实现，见 `phase-6-report.md`**。
- 本阶段不包含前端页面、Docker/CI、真实模型 Key 的生产调用。
- 模型不可用时，账单/付款/结算 API 仍独立可用。

---

## 1. 本阶段目标

1. 会话与消息持久化；
2. 模型 Provider 抽象（OpenAI-compatible + Fake + Disabled）；
3. 白名单工具网关；
4. 写操作只生成待确认动作；
5. 用户确认后只执行一次；
6. 确认幂等、内容哈希绑定、权限复核；
7. 模型失败/禁用降级；
8. 用 FakeProvider 和 HTTP mock 做可重复测试。

---

## 2. 数据层

新增迁移：`f9d42243af3a_agent_conversations_and_pending_actions.py`。

新增 3 张表：

- `agent_conversations`：用户/账本/标题/时间；
- `agent_messages`：user/assistant/tool、内容、tool_calls、token 用量、client_message_id；
- `pending_actions`：动作类型、payload、payload_hash、preview、状态、过期时间、结果。

当前共 **20 张表**，Alembic head `f9d42243af3a`。
已验证 `upgrade head → downgrade base → upgrade head`。

---

## 3. Agent 结构

```text
Agent API
  -> AgentService（会话、历史、循环、最大步数）
     -> Provider（OpenAI-compatible / Fake / Disabled）
     -> ToolGateway（白名单、参数校验、权限）
        -> 读工具：ledger/period/preview/explain/history/export
        -> 准备写工具：create_bill/update_bill/void_bill/set_occupancies/
                        record_payment/create_settlement/propose_rule_change
           -> PendingAction（不写正式账）
  -> Action API
     -> confirm（哈希 + 权限 + 幂等）
        -> 既有服务层（账单/付款/规则/结算）
```

### 3.1 Provider

- `OpenAICompatibleProvider`：同步 HTTP `/chat/completions`，支持 tool calls；
- `FakeProvider`：测试脚本；
- `DisabledProvider`：`LLM_ENABLED=false` 或缺少 Key 时返回 503；
- 超时、HTTP 错误、非法 JSON、非法工具参数均转为 `ProviderError`；
- 不在日志中输出 API Key。

### 3.2 工具白名单

读：

- `get_current_ledger`
- `get_billing_period`
- `preview_split`
- `explain_settlement`
- `get_settlement_history`
- `export_settlement`

准备写：

- `create_bill`
- `update_bill`
- `void_bill`
- `set_occupancies`
- `record_payment`
- `create_settlement`
- `propose_rule_change`

**`confirm_rule_change` 不在工具 schema 中**。模型无法确认。

### 3.3 工具安全

- 工具名白名单；
- 金额必须是整数分，拒绝布尔/浮点/字符串；
- 入住天数 0–31；
- 账期/人员限当前账本；
- 普通成员只能准备自己的付款；
- 管理员工具在准备和执行时都检查角色；
- 缺参数/非法参数返回结构化错误给模型，不崩溃；
- 未知工具返回 `TOOL_NOT_ALLOWED`；
- 工具结果不直接写账。

---

## 4. 待确认动作

- 有效 10 分钟；
- `payload_hash` 绑定内容；
- 动作包含完整 preview；
- API 返回 `pending_action_id`、`payload_hash`、preview、过期时间；
- 确认必须提供 `expected_payload_hash` 与 `Idempotency-Key`；
- 确认时再次检查：动作属于当前用户/管理员、未过期、状态 pending、哈希一致、角色有效；
- 确认后调用既有服务层；
- 已确认动作重复确认返回同一结果，不重复执行；
- 取消后确认返回 409；
- 哈希不一致返回 409；
- 确认/取消写审计。

支持的动作：

`create_bill`、`update_bill`、`void_bill`、`set_occupancies`、`record_payment`、
`create_settlement`、`confirm_rule_change`。

---

## 5. API

新增 6 个 path：

- `GET /api/v1/households/{hid}/agent/conversations`
- `POST /api/v1/households/{hid}/agent/conversations`
- `GET /api/v1/households/{hid}/agent/conversations/{cid}`
- `PATCH /api/v1/households/{hid}/agent/conversations/{cid}`
- `GET /api/v1/households/{hid}/agent/conversations/{cid}/messages`
- `POST /api/v1/households/{hid}/agent/conversations/{cid}/messages`
- `GET /api/v1/households/{hid}/actions/{aid}`
- `POST /api/v1/households/{hid}/actions/{aid}/confirm`
- `POST /api/v1/households/{hid}/actions/{aid}/cancel`

当前 **46 个 OpenAPI path**。

会话按用户隔离；同一账本的另一个成员看不到别人的对话。

---

## 6. 测试结果

### 6.1 命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pytest --cov=roommate_billing --cov-report=term:skip-covered
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\alembic.exe check
```

### 6.2 实测

```text
157 passed, 1 warning in 52.58s
coverage: 88% (3143 statements, 365 missed)
ruff check: All checks passed
ruff format --check: 108 files formatted
alembic check: No new upgrade operations detected
Alembic: f9d42243af3a (head)
upgrade → downgrade base → upgrade: OK
uv lock --check: 48 packages
pip check: No broken requirements
compileall: OK
```

带覆盖率耗时 70.01s。

### 6.3 Agent 覆盖场景

- 模型调用 `create_bill` → 只生成 pending action，账单数不变；
- 用户确认 → 账单增加；
- 同 Idempotency-Key 重放 → 返回同一结果，不重复写；
- 新 Key 重放已确认动作 → 不重复写；
- 哈希不匹配 → 409；
- 取消后确认 → 409；
- `create_settlement` 准备/确认；
- `propose_rule_change` 准备/确认，规则版本变为 2；
- `update_bill` / `void_bill` / `set_occupancies` / `record_payment` 确认执行；
- 成员不能确认 owner 的动作；
- 模型尝试 `confirm_rule_change` → `TOOL_NOT_ALLOWED`；
- 缺金额 → `MISSING_ARGUMENT`，不落账；
- 模型未启用 → 503，核心账务 API 仍 200；
- 模型 Provider 失败 → 502，不产生账单或 pending action；
- 重复 client_message_id → 不重复调用模型；
- 最大 8 步后终止；
- 会话按用户隔离；
- 读工具：当前账本、账期、分摊预览、结算解释、历史、导出路径；
- OpenAI-compatible Provider 的请求构造/工具解析/错误路径（HTTP mock，无外网）。

---

## 7. 已知限制

1. **没有前端聊天/确认界面**：阶段 6。
2. **没有真实模型 Key/真实模型调用**：只验证了 Fake 与 HTTP mock；需要用户提供 Key 才能做真实联调。
3. **没有流式输出**：一次性返回。
4. **没有 tool-call 级去重**：同一轮重复调用写工具会生成多个 pending action（仍不落正式账）。
5. **没有过期 pending action 清理任务**：过期后确认返回 409，但记录保留。
6. **没有真正的提示注入评测集**：目前只有工具白名单/确认工具不可见/缺参数测试。
7. **没有多 Agent/长期记忆**：单会话、单 Agent。
8. **没有 token 成本预算与配额**：只有最大步数和输入长度。
9. **没有前端 CSP/HTTPS**：阶段 6/7。
10. **一个 TestClient/httpx 弃用 warning**：不影响测试。

---

## 8. 文件清单

```text
migrations/versions/f9d42243af3a_agent_conversations_and_pending_actions.py
src/roommate_billing/db/models/agent.py
src/roommate_billing/agent/types.py
src/roommate_billing/agent/providers.py
src/roommate_billing/agent/tools.py
src/roommate_billing/agent/loop.py
src/roommate_billing/services/actions.py
src/roommate_billing/api/v1/agent.py
src/roommate_billing/api/v1/actions.py
tests/integration/test_agent.py
tests/integration/test_agent_tools.py
tests/integration/test_agent_action_types.py
tests/unit/test_providers.py
```

---

## 9. 阶段 6 开始条件

- 用户验收本报告；
- 确认前端技术栈（原生 ES modules）与需要保留的旧版 DOM/data-testid；
- 确认 Agent 聊天的展示方式（pending action 卡片 + 确认按钮）；
- 许可证仍待选择，不影响开发。

阶段 6 已在后续实现，见 `phase-6-report.md`。
