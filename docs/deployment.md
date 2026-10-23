# 部署、运维与备份恢复

- 目标环境：一台 Linux 主机（2 vCPU / 2 GB 内存起步，家用规模足够），Docker Engine + Docker Compose v2。
- 拓扑：Caddy（HTTPS）→ FastAPI 单体 → PostgreSQL。
- 当前状态：**Dockerfile、Compose、Caddyfile、CI、备份恢复脚本已创建；Compose/Caddy/Dockerfile 静态验证通过**。
- 当前 Windows 主机没有 Docker daemon；已用 QEMU TCG + boot2docker 19.03 执行 **docker build/run**（镜像 215MB、容器 healthy、UI 登录通过），但 **compose up 和 Docker 内 Caddy 未执行**。Caddy 已用内部 CA 在 `https://localhost:8443` 做真实 TLS/反代测试，公网 ACME 未验证。不得声称已生产部署。
- 备份恢复已在本地 PostgreSQL 16.15 真实演练，见 [backup-restore.md](backup-restore.md)。

---

## 1. 部署拓扑

```text
Internet
  │ 80/443
  ▼
Caddy (TLS, 安全响应头, 反向代理)
  │ 内部网络 :8000
  ▼
FastAPI / Uvicorn (非 root)
  │ 内部网络 :5432
  ▼
PostgreSQL 16 (命名卷 pgdata)
```

- 只发布 Caddy 的 80/443。
- Postgres 不映射宿主机端口。
- API 不直接暴露公网。
- 静态前端由 API 提供（同源，简化 CSRF/CORS）。
- 备份由宿主机 cron/systemd timer 执行，输出到宿主机受控目录。

---

## 2. 前置条件

| 项目 | 要求 |
|---|---|
| 操作系统 | Linux（Ubuntu 22.04/24.04、Debian 12 等） |
| Docker | Engine 24+ |
| Compose | v2 |
| 域名 | 公网部署建议有域名；内网可用内部 CA |
| 端口 | 80/443 可达 |
| 磁盘 | 至少 20 GB；备份空间另算 |
| 时间 | 主机启用 NTP |
| 时区 | 主机 UTC 或固定时区；应用按账本时区显示 |

检查：

```bash
docker --version
docker compose version
```

---

## 3. 容器与服务设计

### 3.1 服务

| 服务 | 镜像/构建 | 暴露 | 作用 |
|---|---|---|---|
| `db` | `postgres:16.15-bookworm` | 否 | 数据库 |
| `api` | 本地 Dockerfile | 仅内部 8000 | FastAPI + 静态文件；启动时执行迁移 |
| `caddy` | `caddy:2-alpine` | 80/443 | HTTPS、反代、响应头 |

### 3.2 Dockerfile 实际实现

- 多阶段：`python:3.12-slim` builder + runtime；
- `pip install --prefix=/install .` 安装项目及依赖；
- 非 root：`USER 10001:10001`；
- 复制 `migrations/`、`alembic.ini`、`web/`；
- `WEB_DIR=/app/web`（安装包不在 repo 根时也能找到前端）；
- `HEALTHCHECK` 调用 `/health/ready`；
- 入口：`alembic upgrade head && uvicorn ... --proxy-headers`；
- `.dockerignore` 排除 `.env`、测试、备份、`.venv` 等。

### 3.3 Compose 实际实现

- `docker-compose.yml`：db + api + caddy，生产拓扑；
- `docker-compose.dev.yml`：db + api，API 绑定 `127.0.0.1:8000`；
- `db` 不发布宿主机端口，只在 `internal` 网络；
- `api` 只在 `expose: 8000`；`read_only`、`cap_drop: ALL`、`no-new-privileges`；
- `caddy` 是唯一发布 80/443 的服务；
- `env_file` 为可选 `.env`，缺少时由 Compose 插值变量提供；
- 日志轮转、健康检查、stop grace period 已配置；
- API 启动时执行迁移（单实例）；多实例部署时应拆独立 migrate 并加锁。

`docker compose ... config --quiet` 已实际验证（无 Docker daemon）。

---

## 4. 环境变量

```env
# 应用
APP_ENV=production
APP_BASE_URL=https://billing.example.com
APP_SECRET_KEY=<至少32字节随机值>
SESSION_COOKIE_SECURE=true
ALLOW_REGISTRATION=false
LOG_LEVEL=INFO

# 数据库
POSTGRES_DB=roommate_billing
POSTGRES_USER=roommate
POSTGRES_PASSWORD=<强随机密码>
DATABASE_URL=postgresql+psycopg://roommate:<密码>@db:5432/roommate_billing

# Agent（可关闭）
LLM_ENABLED=false
LLM_BASE_URL=https://api.example.com/v1
LLM_API_KEY=<服务端密钥>
LLM_MODEL=model-with-tool-calling
LLM_TIMEOUT_SECONDS=30
AGENT_MAX_STEPS=8

# 部署
DOMAIN=billing.example.com
ACME_EMAIL=admin@example.com
BACKUP_RETENTION_DAYS=14
WEB_DIR=/app/web
```

规则：

- `.env` 权限 600，属主为部署用户。
- `.env` 不进 Git；`.env.example` 只放占位符。
- `DATABASE_URL` 中的密码含特殊字符时 URL 编码，或使用 Compose 分段变量拼接。
- 不在 `docker inspect`/日志/CI 输出中打印 env。
- 生产建议 Docker secrets 或 systemd `EnvironmentFile`。
- `LLM_ENABLED=false` 时，所有核心功能仍可用。

生成密钥示例：

```bash
openssl rand -hex 32
```

（只需生成一次；不要提交/截图/发到聊天。）

---

## 5. 首次部署步骤（阶段 7 验证）

> 以下命令已按仓库中的真实文件编写；Docker 构建/启动仍需在有 Docker daemon 的环境执行，本机未执行。

### 5.1 获取代码

```bash
git clone <repository-url> roommate-billing-agent
cd roommate-billing-agent
```

### 5.2 配置

```bash
cp .env.example .env
chmod 600 .env
# 编辑 .env：域名、数据库密码、APP_SECRET_KEY、LLM 配置
```

### 5.3 构建

```bash
docker compose build
```

### 5.4 构建并启动

```bash
docker compose up -d --build
docker compose ps
```

- API 容器入口执行 `alembic upgrade head`，然后启动 uvicorn；
- 单实例下可接受；多实例应拆独立 migrate 并加锁。
- 迁移失败时不要启动新版本；查看日志，修复后重试。
- 不要用 `docker compose down -v`（会删数据库卷）。

### 5.5 创建首个管理员

```bash
docker compose exec api \
  python -m roommate_billing.cli create-user \
  --email admin@example.com \
  --name 管理员
```

- 交互输入密码；不把密码写在命令行历史。
- 注册默认关闭，后续通过邀请添加成员。

### 5.6 健康检查

```bash
curl -fsS https://billing.example.com/health/live
curl -fsS https://billing.example.com/health/ready
```

期望：

```json
{"status":"ok"}
```

- 不返回数据库版本/DSN/密钥。
- 若 503，查看 `docker compose logs api db caddy`，但不要把日志原文贴到公开渠道。

### 5.7 首次业务配置

1. 登录；
2. 创建账本；
3. 创建人员（lin/zhe/zhou）；
4. 创建账期；
5. 初始化规则版本 V1；
6. 录入真实账单和真实历史收款；
7. 锁定/结算；
8. 导出核对。

> 旧页面的自动基线不得作为真实收款导入。

---

## 6. HTTPS 与 Caddy

### 6.1 公网域名

- DNS A/AAAA 指向主机。
- 防火墙开放 80/443。
- Caddy 自动申请/续期证书。
- 不需要额外 Certbot。

Caddyfile（已实现并通过 `caddy validate`）：

```caddyfile
{
    email {$ACME_EMAIL}
    admin off
}

{$DOMAIN} {
    encode zstd gzip
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "no-referrer"
        Permissions-Policy "camera=(), microphone=(), geolocation=()"
        X-Robots-Tag "noindex, nofollow"
        -Server
    }
    request_body { max_size 1MB }
    reverse_proxy api:8000
    log { output stdout format json }
}
```

- CSP 由应用中间件统一加；阶段 6 已移除内联脚本/样式并通过严格 CSP 静态测试。
- 不建议在 Caddy 中做复杂业务限流；应用层限流 + 网关基础限制。
- 内网无域名：
  - 使用 `tls internal`，客户端需信任内部 CA；
  - 或使用内部 DNS + 企业证书；
  - 不要长期用明文 HTTP 保存真实收款。

### 6.2 代理头

- Caddy 设置 `X-Forwarded-For/Proto/Host`。
- 应用只信任 Caddy 网段；不要让公网直接访问 API 端口。
- `TRUSTED_PROXY` 配置。

---

## 7. 数据库迁移

### 7.1 开发/测试

```bash
alembic upgrade head
alembic current
alembic history
```

### 7.2 生产

- 当前单实例：API 容器入口先 `alembic upgrade head` 再启动 uvicorn。
- 部署顺序：
  1. 备份；
  2. `docker compose build`；
  3. `docker compose up -d`（API 入口执行迁移）；
  4. 冒烟测试；
  5. 观察日志/健康检查。
- 迁移失败：
  - 不启动新 API；
  - 保留旧容器/镜像；
  - 根据备份/迁移脚本恢复。
- 破坏性迁移（删列/改类型）必须：
  - 先扩展后收缩（expand/contract）；
  - 分多个发布；
  - 有回滚/恢复方案；
  - 不直接 `DROP` 有数据的列。

### 7.3 迁移测试

- 空库 `upgrade head`；
- 旧版本快照升级；
- 可选 `downgrade` 测试（破坏性迁移需人工确认）；
- CI 中自动执行。

---

## 8. 备份

实际脚本：

- `scripts/backup_postgres.sh`
- `scripts/backup_postgres.ps1`
- `scripts/restore_postgres.sh`
- `scripts/restore_postgres.ps1`

策略：

- 每日 `pg_dump -Fc` + SHA-256；
- 默认保留 14 天（`BACKUP_RETENTION_DAYS`）；
- 备份目录权限 600/700；
- 生产建议异地/对象存储 + 加密 + 失败告警（未接入）。

宿主机示例：

```bash
PG_DATABASE_URL='postgresql://roommate:<password>@127.0.0.1:5432/roommate_billing' \
BACKUP_DIR=/srv/roommate-backups \
./scripts/backup_postgres.sh
```

Docker 部署时可从宿主机连接数据库，或临时 `docker compose exec -T db pg_dump ... > file`；不要把备份只放在数据库卷内。

## 9. 恢复

```bash
createdb -h 127.0.0.1 -U roommate roommate_restore
CONFIRM_RESTORE=YES \
PG_RESTORE_URL='postgresql://roommate:<password>@127.0.0.1:5432/roommate_restore' \
./scripts/restore_postgres.sh /srv/roommate-backups/roommate-....dump
```

- 先恢复到新库，不直接覆盖生产；
- checksum 存在时先校验；
- 验证表行数、账单/实收合计、Alembic head、`/health/ready`；
- 确认后再按 runbook 切换连接/重建容器；
- `docker compose down -v` 会删除数据卷，禁止在生产无备份时执行。

**2026-10-23 本地实际演练结果见 [backup-restore.md](backup-restore.md)**：20 张表行数一致、`bill_cents=49305`、`payment_cents=12000`、恢复库 `/health/ready` 200。

---

## 10. 升级与回滚

### 10.1 升级

```bash
# 1. 备份
# 2. 拉取新版本
git fetch --tags
git checkout vX.Y.Z
docker compose build
docker compose up -d
curl -fsS https://.../health/ready
```

- 先在 staging 验证迁移/测试。
- 生产变更窗口执行。
- 保留上一版本镜像 tag。

### 10.2 回滚

- 应用回滚：切回上一镜像 tag/commit，重启 API。
- 数据库回滚：
  - 优先使用向前兼容迁移；
  - 若必须回退 schema，使用升级前备份恢复到新库；
  - 不直接 `downgrade` 生产，除非迁移明确可逆且已验证。
- 回滚后再次冒烟：登录、账期、结算查询、导出。

### 10.3 版本策略

- SemVer：`MAJOR.MINOR.PATCH`。
- 数据库迁移与 API 版本分开；API `/api/v1`。
- Release notes 说明迁移、配置、破坏性变更。

---

## 11. 运行与监控

### 11.1 日常检查

```bash
docker compose ps
docker compose logs --tail=100 api
curl -fsS https://.../health/ready
```

- 容器重启策略 `unless-stopped`。
- 磁盘空间（数据库/备份/日志）告警。
- 证书到期（Caddy 自动续期，但需监控）。
- 备份文件生成与大小。
- 登录失败/429 异常增加。
- API 5xx、数据库连接池耗尽。
- Agent 模型超时/费用。

### 11.2 日志

- 驱动 `json-file` + 轮转，防止磁盘打满。
- 不记录请求体/密码/Token/API Key。
- 生产日志保留 14–30 天；审计单独保留。
- 集中日志（可选）：Loki/rsyslog；v1 不引入。

### 11.3 维护窗口

- 迁移、恢复、升级前通知用户。
- 维护页可由 Caddy 返回静态页/503。
- 不在结算/备份期间执行破坏性操作。

---

## 12. 本地开发

> 非 Docker 路径已在当前机器实际运行（uvicorn + 本地 PostgreSQL 16.15 + Chrome E2E）；Docker 路径待有 daemon 的环境。

```bash
# Python 3.12 + uv
uv sync --frozen --extra dev
# 配置 DATABASE_URL/APP_SECRET_KEY/APP_BASE_URL
alembic upgrade head
uv run uvicorn roommate_billing.main:app --reload
```

- 前端静态文件由 FastAPI 提供，无需 Node 构建；
- Node 仅用于前端纯函数测试。
- 测试数据库独立；不用开发库跑测试。
- 本地 `SESSION_COOKIE_SECURE=false`，仅 localhost。
- 本地 Caddy 可选；直接 8000 端口即可。
- 不把本地 `.env` 提交。

---

## 13. 故障处理

| 症状 | 排查 |
|---|---|
| 502/503 | `docker compose ps`；api 健康；Caddy 到 api 网络 |
| 数据库连接失败 | db 健康；密码/DSN；网络；磁盘 |
| 迁移失败 | 迁移日志；备份；不要启动新 API |
| 证书失败 | DNS/80/443；Caddy 日志；防火墙 |
| 登录失败 | 时钟/NTP；限流；会话表；密码策略 |
| 结算 409 | 账期状态/版本/预览哈希；是否已有 final |
| 备份失败 | 磁盘；权限；数据库连接；`pg_dump` 退出码 |
| 磁盘满 | 日志轮转；旧备份；WAL；临时文件 |

---

## 14. 已知限制（v1）

- 单实例优先；多实例需要共享限流/会话/任务。
- 无邮件服务；邀请码/密码重置需手工传递/CLI。
- 无 MFA。
- 无自动 WAL/PITR；只有每日逻辑备份。
- 无银行流水自动对账/OCR。
- 无多币种。
- Agent 非流式；模型不可用时仅核心账务可用。
- 无移动 App/推送。
- 备份恢复需人工执行 runbook。

---

## 15. 部署验收标准

- [ ] 全新环境按 README 可启动。
- [ ] `docker compose config` 无明文密钥输出到日志。
- [ ] 空库迁移成功。
- [ ] 健康检查正常且不泄露配置。
- [ ] HTTPS 证书有效，HTTP 跳转 HTTPS。
- [ ] Postgres 未暴露公网。
- [ ] 容器非 root、cap_drop、no-new-privileges。
- [ ] 重启后数据保留。
- [ ] 备份文件可恢复并通过一致性检查。
- [ ] 升级/回滚流程演练。
- [ ] 日志不含 secrets。
- [ ] README 命令与实际一致（阶段 8 最终验证）。
