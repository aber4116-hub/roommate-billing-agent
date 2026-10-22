# 备份与恢复演练

- 状态：**已在本地 PostgreSQL 16.15 上真实执行 pg_dump → pg_restore → 数据比对 → 应用健康检查**。
- Docker 环境未运行；本页记录的是同一 PostgreSQL 版本、同一 custom-format 备份格式的本地演练。
- 脚本：`scripts/backup_postgres.sh`、`scripts/restore_postgres.sh`、PowerShell 版本。

---

## 1. 策略

| 项目 | 方案 |
|---|---|
| 备份格式 | `pg_dump -Fc`（custom，支持并行/选择性恢复） |
| 频率 | 每日一次；重要结算前手动一次 |
| 保留 | 默认 14 天；`BACKUP_RETENTION_DAYS` |
| 校验 | 每个 dump 旁生成 SHA-256 |
| 存放 | 宿主机受控目录/对象存储，**不放数据库容器内** |
| 恢复 | 恢复到新库/新实例，先校验，再切换 |
| 加密 | 生产建议备份目录加密/对象存储 SSE |
| 演练 | 每月至少一次；本页记录首次 |

---

## 2. 备份命令

Linux/macOS/Git Bash：

```bash
PG_DATABASE_URL='postgresql://roommate:<password>@127.0.0.1:5432/roommate_billing' \
BACKUP_DIR=/srv/roommate-backups \
./scripts/backup_postgres.sh
```

PowerShell：

```powershell
$env:PG_DATABASE_URL = "postgresql://roommate:<password>@127.0.0.1:5432/roommate_billing"
.\scripts\backup_postgres.ps1 `
  -DatabaseUrl $env:PG_DATABASE_URL `
  -BackupDir "D:\roommate-backups" `
  -PgDump "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe"
```

输出：

- `roommate-YYYYMMDDTHHMMSSZ.dump`
- `roommate-....dump.sha256`

Docker 部署下，可以在宿主机用 `pg_dump` 连接容器内数据库；不建议把备份只放在 `db_data` 卷里。

---

## 3. 恢复命令

恢复到**新库**，确认后再切换：

```bash
createdb -h 127.0.0.1 -U roommate roommate_restore
CONFIRM_RESTORE=YES \
PG_RESTORE_URL='postgresql://roommate:<password>@127.0.0.1:5432/roommate_restore' \
./scripts/restore_postgres.sh /srv/roommate-backups/roommate-....dump
```

PowerShell：

```powershell
.\scripts\restore_postgres.ps1 `
  -File "D:\roommate-backups\roommate-....dump" `
  -RestoreUrl "postgresql://roommate:<password>@127.0.0.1:5432/roommate_restore" `
  -PgRestore "C:\Program Files\PostgreSQL\16\bin\pg_restore.exe" `
  -ConfirmRestore
```

`restore_postgres.sh` 要求 `CONFIRM_RESTORE=YES`；PowerShell 要求 `-ConfirmRestore`。
如果 checksum 文件存在，先校验 SHA-256。

---

## 4. 本机真实演练结果（2026-10-23）

环境：

- PostgreSQL 16.15；
- 源库 `roommate_backup_src`；
- 目标库 `roommate_backup_restore`；
- 演示数据：1 用户/1 账本/3 人员/1 账期/4 账单/12 分摊/1 实收/9 审计；
- Alembic `f9d42243af3a`。

备份：

```text
backup=...\roommate-20261022T203231Z.dump
sha256=0c747bf22c5603621ac4ce112f9a5014bbce62728d06b00a377309857c1b7825
```

恢复：

```text
restored=...\roommate-20261022T203231Z.dump
```

源库与恢复库逐表比对：

```json
{
  "bills": 4,
  "bill_allocations": 12,
  "occupancies": 3,
  "payments": 1,
  "audit_logs": 9,
  "users": 1,
  "households": 1,
  "people": 3,
  "rule_versions": 1,
  "rule_version_items": 5,
  "billing_periods": 1,
  "settlements": 0,
  "settlement_lines": 0,
  "pending_actions": 0,
  "agent_conversations": 0,
  "agent_messages": 0,
  "auth_sessions": 0,
  "household_invites": 0,
  "household_members": 1,
  "idempotency_keys": 0
}
```

聚合值：

```text
bill_cents      = 49305
payment_cents   = 12000
audit_count     = 9
alembic_version = f9d42243af3a
equal           = true
```

恢复库启动应用：

```text
GET /health/ready -> 200 {"status":"ok"}
GET /              -> 200
GET /api/v1/meta   -> {"version":"0.1.0","api_version":"v1"}
```

结论：**备份、校验、恢复、数据一致性和应用健康检查均实际通过**。

---

## 5. 未验证

- Docker 容器内 `pg_dump`/`pg_restore`：当前机器无 Docker；
- 对象存储/异地备份：未接入；
- 备份加密：未实现；
- 恢复后切换 DNS/反向代理的完整生产演练：未执行。

这些不会被描述为“已完成”。
